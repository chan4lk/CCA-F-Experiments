import pytest


def make_record(**overrides):
    record = {
        "vendor_name": "Northwind Supply Co.",
        "document_number": "INV-2026-0417",
        "issue_date": "2026-03-14",
        "currency": "USD",
        "currency_detail": None,
        "line_items": [
            {"description": "Hosting", "quantity": 1, "unit_price": 420.00, "amount": 420.00},
            {"description": "Support", "quantity": 1, "unit_price": 180.00, "amount": 180.00},
        ],
        "stated_total": 600.00,
        "calculated_total": 600.00,
        "conflict_detected": False,
        "conflict_note": None,
        "payment_terms": "net_30",
        "payment_terms_detail": None,
        "purchase_order": "PO-88213",
        "field_confidence": {
            "vendor_name": 1.0,
            "document_number": 1.0,
            "issue_date": 1.0,
            "currency": 1.0,
            "line_items": 1.0,
            "stated_total": 1.0,
            "payment_terms": 1.0,
        },
    }
    record.update(overrides)
    return record


@pytest.fixture
def record():
    return make_record()


class Block:
    type = "tool_use"

    def __init__(self, name, input):
        self.name = name
        self.input = input


class Response:
    def __init__(self, blocks):
        self.content = blocks


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        name, payload = self.replies.pop(0)
        return Response([Block(name, payload)] if name else [])


class FakeClient:
    """Stands in for anthropic.Anthropic. Every reply is a schema-valid tool_use
    payload, which is what the real API guarantees - so the tests exercise the
    semantic layer, not JSON parsing."""

    def __init__(self, *replies):
        self.messages = FakeMessages(replies)

    @property
    def calls(self):
        return self.messages.calls
