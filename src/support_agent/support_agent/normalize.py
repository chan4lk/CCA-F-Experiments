"""Format normalisation and context trimming, applied to tool output before the model
sees it.

Three backends, three time formats, one numeric status enum. Asking the model to hold
that in a system prompt works most of the time, which is another way of saying it fails
some of the time and the failure is a wrong refund date. A transform is deterministic.
"""

from datetime import UTC, datetime

from backend import STATUS_CODES
from settings import ORDER_FIELDS_KEPT


def iso(value) -> str | None:
    """Unix seconds, unix milliseconds, or an ISO string in - ISO 8601 UTC out."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    seconds = value / 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def status(code) -> str:
    if isinstance(code, str):
        return code
    return STATUS_CODES.get(code, f"unknown-{code}")


def order(record: dict, keep: list[str] | None = None) -> dict:
    """Normalise, then trim. Forty fields per lookup is tokens spent in proportion to
    what the warehouse tracks rather than to what the conversation needs, and it pushes
    the customer's actual problem toward the middle of the context where it is read
    least reliably."""
    normalised = {
        **record,
        "status": status(record.get("status_code", record.get("status"))),
        "placed_at": iso(record.get("placed_at")),
        "delivered_at": iso(record.get("delivered_at")),
    }
    normalised.pop("status_code", None)
    return {k: normalised[k] for k in (keep or ORDER_FIELDS_KEPT) if k in normalised}


def customer(record: dict) -> dict:
    return {**record, "created_at": iso(record.get("created_at"))}
