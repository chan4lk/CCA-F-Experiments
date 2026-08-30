"""A fake Messages Batches API.

Every batch test drives the real code through this: it records the requests it
was given, hands back scripted messages, and lets a test decide when a batch
"ends". Nothing here talks to the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# --- message shapes -------------------------------------------------------

@dataclass
class Block:
    """A content block that behaves like the SDK's pydantic ones."""

    data: dict[str, Any]

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if exclude_none:
            return {k: v for k, v in self.data.items() if v is not None}
        return dict(self.data)

    @property
    def type(self) -> str:
        return self.data.get("type", "")


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class Message:
    content: list[Block]
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    stop_details: Any = None


def text_message(text: str, stop_reason: str = "end_turn") -> Message:
    return Message([Block({"type": "text", "text": text})], stop_reason)


def tool_call(name: str, args: dict, call_id: str = "toolu_1",
              thinking: str | None = None) -> Message:
    blocks = []
    if thinking is not None:
        blocks.append(Block({"type": "thinking", "thinking": thinking,
                             "signature": "sig-abc"}))
    blocks.append(Block({"type": "tool_use", "id": call_id, "name": name, "input": args}))
    return Message(blocks, "tool_use")


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


# --- an HTTP stub for the client-side tools -------------------------------

class FakeResponse:
    def __init__(self, body: bytes, content_type="text/html", status=200,
                 location=None):
        self.content = body
        self.status_code = status
        self.headers = {"content-type": content_type}
        if location:
            # A redirect the caller is expected to resolve itself: fetch()
            # follows hops by hand so it can re-check each one.
            self.headers["location"] = location

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        import json as _json
        return _json.loads(self.text)


class FakeHTTP:
    """Serves a fixed page for any URL, and records what was asked for."""

    def __init__(self, pages: dict[str, FakeResponse] | None = None,
                 default: FakeResponse | None = None):
        self.pages = pages or {}
        self.default = default or FakeResponse(b"<p>A maximum of 10 tools is supported.</p>")
        self.requested: list[str] = []

    def get(self, url, params=None, headers=None):
        self.requested.append(url)
        return self.pages.get(url, self.default)

    def post(self, url, content=None, data=None, headers=None):
        self.requested.append(url)
        return self.pages.get(url, self.default)
