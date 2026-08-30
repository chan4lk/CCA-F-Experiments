"""One agent, as one batch request.

This is the module `research_agent_batch` calls `conversation.py`, and the
difference between them is the point of this port.

There, a custom tool makes the model stop at `stop_reason: "tool_use"` and the
Batches API provides nothing to continue it, so the loop had to be rebuilt:
build request, batch, result, execute tools, append, build request. Nine
researchers taking six turns each was six batches.

Here the tools are server-side, so the searching and the fetching happen inside
the request. It comes back answered. Nine researchers is **one** batch, and a
phase is a batch rather than a stack of them.

## What is left of the loop

One thing. A long server-tool turn can come back `stop_reason: "pause_turn"`:
the work so far is in the message and the turn wants resubmitting to continue.
So a Task can go round again — but a continuation computes nothing, it resends
what came back. There is no tool dispatch here and no `http` argument to thread
through, because nothing in this process retrieves anything.

A Task is plain data on purpose: it round-trips through JSON so a run can stop
between batches and resume tomorrow, which matters when a batch may take up to
24 hours.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .provenance import Retrieval, retrievals
from .settings import cost_usd

ACTIVE, DONE, FAILED = "active", "done", "failed"

MAX_RETRIES = 3

# custom_id must survive a round trip through the API and be readable in a log.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
MAX_CUSTOM_ID = 64


def make_custom_id(phase: str, role: str, key: str) -> str:
    """`p3-validator-C001-b`. Doubles as the agent_id in the provenance log, so a
    fetch can be traced back to the exact batch request that caused it."""
    raw = f"{phase}-{role}-{key}".strip("-")
    return _SAFE_ID.sub("-", raw)[:MAX_CUSTOM_ID]


@dataclass
class Task:
    """One agent's request, and what came back."""

    custom_id: str
    role: str
    model: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    output_config: dict[str, Any] | None = None
    max_continuations: int = 2
    max_tokens: int = 16000
    # What this task is about — a sub-question id, a claim id — so the
    # orchestrator can match a result back to the work that produced it.
    key: str = ""

    # How many times a `pause_turn` sent this request back for more. Zero is the
    # normal outcome: the turn finished inside one request.
    continuations: int = 0
    # Resubmissions that produced no result at all — an expired batch, a server
    # error. These do not advance the task, so they cannot be bounded by
    # `max_continuations`; without their own ceiling a dead request is retried
    # forever.
    retries: int = 0
    status: str = ACTIVE
    text: str = ""
    parsed: dict[str, Any] | None = None
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    # Server-side searches, billed per request on top of tokens.
    web_searches: int = 0

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.model, self.input_tokens, self.output_tokens,
                        self.web_searches)

    # --- the batch request -------------------------------------------------

    def params(self) -> dict[str, Any]:
        """This task's request, as Messages params.

        `max_tokens` can be generous: a batch request is never streamed and
        never held open, so the timeout pressure that caps a live request does
        not exist here. It needs to be — a researcher's turn now contains every
        page it read as well as its answer.
        """
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "messages": self.messages,
        }
        if self.tools:
            params["tools"] = list(self.tools)
        if self.output_config:
            params["output_config"] = self.output_config
        return params

    # --- advancing ---------------------------------------------------------

    def advance(self, message: Any) -> list[Retrieval]:
        """Fold one batch result in. Returns what its server tools retrieved.

        Almost always terminal: the tools already ran, so the message carries
        the finished answer. The exception is `pause_turn`, which leaves the
        task active for a continuation round.
        """
        self._count(message)
        found = retrievals(message)

        content = _as_blocks(message)
        self.messages.append({"role": "assistant", "content": content})

        stop_reason = _field(message, "stop_reason")
        if stop_reason == "refusal":
            self._fail(f"the model declined this request ({_refusal_category(message)})")
            return found

        if stop_reason == "pause_turn":
            # The turn is resubmitted as it came back, with nothing appended:
            # there are no tool results to compute. Anthropic's servers continue
            # from where the paused message stops.
            self.continuations += 1
            if self.continuations > self.max_continuations:
                self._fail(f"still paused after {self.max_continuations} continuation(s)")
            return found

        if stop_reason == "tool_use":
            # Only reachable if a custom tool got into the grant. No agent here
            # has one, and nothing in this process could execute it, so the turn
            # would hang forever rather than fail — say so instead.
            self._fail("stopped on tool_use, which means a client-side tool reached the "
                       "grant; every tool in this engine runs server-side")
            return found

        self._finish(content, stop_reason)
        return found

    def _count(self, message: Any) -> None:
        usage = _field(message, "usage")
        if usage is None:
            return
        self.input_tokens += _field(usage, "input_tokens", 0) or 0
        self.output_tokens += _field(usage, "output_tokens", 0) or 0
        server = _field(usage, "server_tool_use")
        if server is not None:
            self.web_searches += _field(server, "web_search_requests", 0) or 0

    def _finish(self, content: list[dict], stop_reason: str | None) -> None:
        self.text = "\n".join(b.get("text", "") for b in content
                              if b.get("type") == "text").strip()
        if stop_reason == "max_tokens" and not self.text:
            self._fail("ran out of output tokens before answering")
            return

        self.parsed = _parse(self.text)
        if self.parsed is None:
            self._fail("returned no readable JSON object")
            return
        self.status = DONE

    def retry(self, why: str) -> bool:
        """Count one resubmission that produced no result. False when spent."""
        self.retries += 1
        if self.retries > MAX_RETRIES:
            self._fail(f"gave up after {MAX_RETRIES} retries: {why}")
            return False
        return True

    def _fail(self, why: str) -> None:
        self.status = FAILED
        self.error = why

    # --- persistence -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(**data)


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_blocks(message: Any) -> list[dict[str, Any]]:
    """Assistant content as plain dicts, ready to send back.

    Everything is kept, including the `server_tool_use` and result blocks —
    those *are* the retrieved pages, and dropping them from a resubmitted
    `pause_turn` would ask the model to continue a turn whose research it can no
    longer see. Thinking blocks are kept verbatim for the same round trip: on
    every model in this pipeline except haiku, thinking is on by default, and a
    thinking block must be echoed back unchanged when the turn continues on the
    same model.
    """
    blocks = []
    for block in _field(message, "content") or []:
        if hasattr(block, "model_dump"):
            blocks.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            blocks.append({k: v for k, v in block.items() if v is not None})
    return blocks


def _refusal_category(message: Any) -> str:
    details = _field(message, "stop_details")
    return _field(details, "category") or "no category given"


def _parse(text: str) -> dict[str, Any] | None:
    """The structured answer.

    `output_config.format` guarantees the first text block is valid JSON, so the
    plain load is the normal path. The brace scan is for the turn that ended
    some other way — a ceiling, a truncation — where a usable object may still
    be sitting in the text.
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
