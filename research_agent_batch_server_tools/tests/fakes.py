"""A fake Messages Batches API, and the response shapes server tools produce.

Every batch test drives the real code through this: it records the requests it
was given, hands back scripted messages, and lets a test decide when a batch
"ends". Nothing here talks to the network.

`research_agent_batch` needs an HTTP stub alongside this, because its tools run
in its own process and the tests have to serve them pages. There is none here.
A server tool's work arrives already done, inside the message, so the thing to
fake is the *result blocks* — which is what `searched()` and `fetched()` build.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# --- message shapes -------------------------------------------------------

@dataclass
class Block:
    """A content block that behaves like the SDK's pydantic ones.

    Fields are reachable as attributes as well as through `model_dump`, because
    that is how the real blocks are read: `provenance.retrievals` walks
    `block.tool_use_id` and `block.content` off the response directly.
    """

    data: dict[str, Any]

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if exclude_none:
            return {k: v for k, v in self.data.items() if v is not None}
        return dict(self.data)

    @property
    def type(self) -> str:
        return self.data.get("type", "")

    def __getattr__(self, name: str) -> Any:
        try:
            return self.__dict__["data"][name]
        except KeyError:
            raise AttributeError(name) from None


@dataclass
class ServerToolUse:
    web_search_requests: int = 0
    web_fetch_requests: int = 0


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 50
    server_tool_use: Any = None


@dataclass
class Message:
    content: list[Block]
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    stop_details: Any = None


def text_message(text: str, stop_reason: str = "end_turn") -> Message:
    return Message([Block({"type": "text", "text": text})], stop_reason)


def tool_call(name: str, args: dict, call_id: str = "toolu_1") -> Message:
    """A *client-side* tool call — the shape this engine must never see.

    Kept so a test can prove the engine says so rather than hanging on a turn
    nothing in this process can continue.
    """
    return Message([Block({"type": "tool_use", "id": call_id,
                           "name": name, "input": args})], "tool_use")


# --- what a server tool leaves in the message -----------------------------

def searched(query: str, urls: list[str] | None = None, call_id: str = "srvtoolu_1",
             error_code: str = "") -> list[Block]:
    """The block pair a `web_search` leaves behind: the request, then the result."""
    content = ({"type": "web_search_tool_result_error", "error_code": error_code}
               if error_code else
               [{"type": "web_search_result", "url": url, "title": url,
                 "encrypted_content": "..."} for url in (urls or [])])
    return [
        Block({"type": "server_tool_use", "id": call_id, "name": "web_search",
               "input": {"query": query}}),
        Block({"type": "web_search_tool_result", "tool_use_id": call_id,
               "content": content}),
    ]


def fetched(url: str, call_id: str = "srvtoolu_2", resolved: str = "",
            error_code: str = "", retrieved_at: str = "2026-08-30T10:00:00Z"
            ) -> list[Block]:
    """The block pair a `web_fetch` leaves behind.

    `resolved` is the URL the content came from when a redirect made it differ
    from the one the model asked for.
    """
    content = ({"type": "web_fetch_tool_result_error", "error_code": error_code}
               if error_code else
               {"type": "web_fetch_result", "url": resolved or url,
                "retrieved_at": retrieved_at,
                "content": {"type": "document", "title": url}})
    return [
        Block({"type": "server_tool_use", "id": call_id, "name": "web_fetch",
               "input": {"url": url}}),
        Block({"type": "web_fetch_tool_result", "tool_use_id": call_id,
               "content": content}),
    ]


def answered(text: str, *retrievals: list[Block], stop_reason: str = "end_turn",
             thinking: str | None = None, web_searches: int = 0) -> Message:
    """One finished server-tool turn: what it retrieved, then its answer.

    This is the normal message in this engine — the searching, the fetching and
    the answer all in one response, because they all happened inside one
    request.
    """
    blocks: list[Block] = []
    if thinking is not None:
        blocks.append(Block({"type": "thinking", "thinking": thinking,
                             "signature": "sig-abc"}))
    for group in retrievals:
        blocks.extend(group)
    blocks.append(Block({"type": "text", "text": text}))
    return Message(blocks, stop_reason,
                   Usage(server_tool_use=ServerToolUse(web_searches)))


def paused(*retrievals: list[Block]) -> Message:
    """A turn the server paused mid-flight. Resubmitting it continues it."""
    blocks: list[Block] = []
    for group in retrievals:
        blocks.extend(group)
    return Message(blocks, "pause_turn")


# --- the batch API --------------------------------------------------------

@dataclass
class Counts:
    succeeded: int = 0
    errored: int = 0
    canceled: int = 0
    expired: int = 0
    processing: int = 0

    def model_dump(self):
        return dict(self.__dict__)


@dataclass
class Batch:
    id: str
    processing_status: str
    request_counts: Counts


@dataclass
class Errored:
    error: Any
    type: str = "errored"


@dataclass
class Succeeded:
    message: Message
    type: str = "succeeded"


@dataclass
class Item:
    custom_id: str
    result: Any


class ErrorResponse:
    """Mirrors the SDK: the error object is one level inside the response."""

    def __init__(self, error_type: str, message: str = ""):
        self.error = type("Err", (), {"type": error_type, "message": message})()


Responder = Callable[[str, dict, int], Message]


class FakeBatches:
    def __init__(self, responder: Responder, *,
                 fail: dict[str, tuple[str, str]] | None = None,
                 ends_after_polls: int = 0):
        self.responder = responder
        self.fail = fail or {}
        self.ends_after_polls = ends_after_polls
        self.submitted: list[list[dict]] = []
        self.polls: dict[str, int] = {}
        self._rounds: dict[str, int] = {}
        self._counter = 0

    def create(self, requests):
        self._counter += 1
        batch_id = f"msgbatch_{self._counter:02d}"
        rows = [{"custom_id": r["custom_id"], "params": dict(r["params"])}
                for r in requests]
        self.submitted.append(rows)
        self._batches = getattr(self, "_batches", {})
        self._batches[batch_id] = rows
        return Batch(batch_id, "in_progress", Counts(processing=len(rows)))

    def retrieve(self, batch_id: str):
        self.polls[batch_id] = self.polls.get(batch_id, 0) + 1
        rows = self._batches[batch_id]
        if self.polls[batch_id] > self.ends_after_polls:
            return Batch(batch_id, "ended", Counts(succeeded=len(rows)))
        return Batch(batch_id, "in_progress", Counts(processing=len(rows)))

    def results(self, batch_id: str):
        for row in self._batches[batch_id]:
            custom_id = row["custom_id"]
            if custom_id in self.fail:
                error_type, message = self.fail[custom_id]
                yield Item(custom_id, Errored(ErrorResponse(error_type, message)))
                continue
            round_number = self._rounds.get(custom_id, 0)
            self._rounds[custom_id] = round_number + 1
            yield Item(custom_id,
                       Succeeded(self.responder(custom_id, row["params"], round_number)))


class FakeClient:
    def __init__(self, responder: Responder, **kwargs):
        self.messages = type("M", (), {"batches": FakeBatches(responder, **kwargs)})()

    @property
    def batches(self) -> FakeBatches:
        return self.messages.batches
