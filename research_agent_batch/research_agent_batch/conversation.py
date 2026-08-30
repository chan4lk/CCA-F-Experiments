"""One agent's conversation, advanced one turn per batch round.

The Batches API returns `stop_reason: "tool_use"` and stops. Nothing executes
the tool and nothing continues the turn — that is the whole difference from an
agent harness. So the loop is here:

    build request -> batch -> result -> execute tools -> append -> build request

Each pass is one round, and one batch carries the next turn of *every* agent
still working. Nine researchers taking six turns each is six batches, not
fifty-four requests, and every one of those requests is billed at half price.

A Conversation is plain data on purpose: it round-trips through JSON so a run
can stop between rounds and resume tomorrow, which matters when a batch may take
up to 24 hours.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .settings import cost_usd
from .tools import Retrieval, execute

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
class Conversation:
    """One agent, mid-flight."""

    custom_id: str
    role: str
    model: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    output_config: dict[str, Any] | None = None
    max_rounds: int = 6
    max_tokens: int = 16000
    # Set for validators: the only host this agent's web_fetch may reach.
    allowed_domains: list[str] | None = None
    # What this conversation is about — a sub-question id, a claim id — so the
    # orchestrator can match a result back to the work that produced it.
    key: str = ""

    round: int = 0
    # Resubmissions that produced no result at all — an expired batch, a server
    # error. These do not advance the conversation, so they cannot be bounded by
    # `max_rounds`; without their own ceiling a dead request is retried forever.
    retries: int = 0
    status: str = ACTIVE
    text: str = ""
    parsed: dict[str, Any] | None = None
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.model, self.input_tokens, self.output_tokens)

    # --- the batch request -------------------------------------------------

    def params(self) -> dict[str, Any]:
        """This conversation's next turn, as Messages params.

        `max_tokens` can be generous: a batch request is never streamed and
        never held open, so the timeout pressure that caps a live request does
        not exist here.
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

    def advance(self, message: Any, http: Any = None) -> list[Retrieval]:
        """Fold one batch result in. Returns what running its tools retrieved.

        Either the agent asked for tools — in which case they run here and the
        conversation stays active for the next round — or it answered, and the
        structured output is parsed and kept.
        """
        usage = getattr(message, "usage", None)
        if usage is not None:
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0

        content = _as_blocks(message)
        self.messages.append({"role": "assistant", "content": content})
        self.round += 1

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":
            return self._fail("the model declined this request "
                              f"({_refusal_category(message)})")

        calls = [b for b in content if b.get("type") == "tool_use"]
        if not calls:
            return self._finish(content, stop_reason)

        results, retrievals = [], []
        for call in calls:
            outcome = execute(call.get("name", ""), call.get("input") or {},
                              allowed_domains=self.allowed_domains,
                              # This conversation's own grant. The name in a
                              # tool_use block is model-supplied; the request's
                              # tools array is not.
                              granted=[t.get("name", "") for t in self.tools],
                              http=http)
            retrievals.extend(outcome.retrievals)
            results.append({
                "type": "tool_result",
                "tool_use_id": call.get("id"),
                "content": outcome.content,
                "is_error": outcome.is_error,
            })

        # All tool_results go back in ONE user message. Splitting them across
        # several silently trains the model out of asking for parallel calls.
        self.messages.append({"role": "user", "content": results})

        if self.round >= self.max_rounds:
            self._fail(f"hit its {self.max_rounds}-round ceiling still calling tools")
        return retrievals

    def _finish(self, content: list[dict], stop_reason: str | None) -> list[Retrieval]:
        self.text = "\n".join(b.get("text", "") for b in content
                              if b.get("type") == "text").strip()
        if stop_reason == "max_tokens" and not self.text:
            return self._fail("ran out of output tokens before answering")

        self.parsed = _parse(self.text)
        if self.parsed is None:
            return self._fail("returned no readable JSON object")
        self.status = DONE
        return []

    def retry(self, why: str) -> bool:
        """Count one resubmission that produced no result. False when spent."""
        self.retries += 1
        if self.retries > MAX_RETRIES:
            self._fail(f"gave up after {MAX_RETRIES} retries: {why}")
            return False
        return True

    def _fail(self, why: str) -> list[Retrieval]:
        self.status = FAILED
        self.error = why
        return []

    # --- persistence -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        return cls(**data)


def _as_blocks(message: Any) -> list[dict[str, Any]]:
    """Assistant content as plain dicts, ready to send back.

    Thinking blocks are kept verbatim rather than stripped: on every model in
    this pipeline except haiku, thinking is on by default, and a thinking block
    must be echoed back unchanged when the conversation continues on the same
    model.
    """
    blocks = []
    for block in getattr(message, "content", None) or []:
        if hasattr(block, "model_dump"):
            blocks.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            blocks.append({k: v for k, v in block.items() if v is not None})
    return blocks


def _refusal_category(message: Any) -> str:
    details = getattr(message, "stop_details", None)
    return getattr(details, "category", None) or "no category given"


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
