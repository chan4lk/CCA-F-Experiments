"""Structured tool errors.

A uniform "Operation failed" tells the agent nothing it can act on, so it either retries
a permanent failure or gives up on a transient one. Every failure here carries a category,
whether retrying is worth anything, and a sentence the agent can say to a customer.
"""

import json
from typing import Any

TRANSIENT = "transient"      # timeout, upstream 503 - retrying may work
VALIDATION = "validation"    # malformed input - retrying identical input will not
BUSINESS = "business"        # a policy said no - the agent must change course, not retry
PERMISSION = "permission"    # this tool may not do this - escalate


def ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


def fail(
    category: str,
    message: str,
    *,
    retryable: bool | None = None,
    customer_message: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if retryable is None:
        retryable = category == TRANSIENT
    payload = {
        "errorCategory": category,
        "isRetryable": retryable,
        "description": message,
        **extra,
    }
    if customer_message:
        payload["customerMessage"] = customer_message
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": True}


def empty(what: str, **extra: Any) -> dict[str, Any]:
    """A query that ran and matched nothing. NOT an error - conflating the two makes the
    agent retry a successful lookup, or report an outage when the customer simply has no
    orders."""
    return ok({"found": False, "reason": f"no {what} matched", **extra})
