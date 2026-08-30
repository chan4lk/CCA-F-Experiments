"""Submit a wave, ask whether it ended, collect what came back.

Everything here is about one batch. The pipeline's shape — which agents are in
which phase — lives in the orchestrator; this module only knows how to put a
list of tasks into the API and get messages back out.

Unchanged from `research_agent_batch_server_tools`, and the one part of that engine this port
does not simplify: a batch is a batch whether the tools inside it run here or on
Anthropic's servers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from .task import Task

ENDED = "ended"

# An errored request is either our fault or theirs, and the difference decides
# whether retrying can possibly help.
FATAL_ERROR_TYPES = {"invalid_request_error", "permission_error",
                     "authentication_error", "not_found_error"}


@dataclass
class Failure:
    custom_id: str
    kind: str            # errored | expired | canceled
    error_type: str = ""
    message: str = ""

    @property
    def retryable(self) -> bool:
        """Expired and canceled requests can be resubmitted unchanged; a server
        error can be retried; a malformed request will fail again identically."""
        if self.kind in ("expired", "canceled"):
            return True
        return self.error_type not in FATAL_ERROR_TYPES


@dataclass
class Collected:
    messages: dict[str, Any] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)


def submit(client: Any, tasks: list[Task]) -> str:
    """Put every active task into one batch. Returns its id.

    Usually every active task is also every task in the phase, and the batch is
    the phase. The exception is a continuation round, where the batch holds only
    the tasks a `pause_turn` sent back.
    """
    active = [c for c in tasks if c.active]
    if not active:
        raise ValueError("nothing to submit: no active tasks")

    batch = client.messages.batches.create(requests=[
        Request(custom_id=c.custom_id,
                params=MessageCreateParamsNonStreaming(**c.params()))
        for c in active
    ])
    return batch.id


def status(client: Any, batch_id: str) -> Any:
    return client.messages.batches.retrieve(batch_id)


def has_ended(batch: Any) -> bool:
    return getattr(batch, "processing_status", None) == ENDED


def counts(batch: Any) -> dict[str, int]:
    """Per-state request counts, for a status line that means something."""
    request_counts = getattr(batch, "request_counts", None)
    if request_counts is None:
        return {}
    if hasattr(request_counts, "model_dump"):
        return request_counts.model_dump()
    return dict(request_counts)


def collect(client: Any, batch_id: str) -> Collected:
    """Every result, keyed by custom_id, with failures kept rather than raised.

    A batch is a set of independent requests: one malformed validator must not
    discard the ninety that succeeded alongside it.
    """
    collected = Collected()
    for item in client.messages.batches.results(batch_id):
        result = item.result
        kind = result.type
        if kind == "succeeded":
            collected.messages[item.custom_id] = result.message
            continue
        collected.failures.append(Failure(
            custom_id=item.custom_id,
            kind="errored" if kind == "errored" else kind,
            error_type=_error_type(result),
            message=_error_message(result),
        ))
    return collected


def _error_type(result: Any) -> str:
    """`result.error` is an ErrorResponse; the error itself is one level in."""
    error = getattr(result, "error", None)
    inner = getattr(error, "error", None)
    return getattr(inner, "type", "") or ""


def _error_message(result: Any) -> str:
    error = getattr(result, "error", None)
    inner = getattr(error, "error", None)
    return getattr(inner, "message", "") or ""
