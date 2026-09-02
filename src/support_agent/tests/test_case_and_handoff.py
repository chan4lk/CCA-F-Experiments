import pytest
from case import Case
from conftest import unwrap
from handoff import render, summarise
from tools import escalate_to_human


def test_case_block_holds_amounts_and_ids_verbatim():
    case = Case()
    case.verify("CUS-1001")
    case.record_order({"order_id": "ORD-55120", "status": "delivered", "total": 128.40, "currency": "GBP"})

    block = case.block()

    assert "CUS-1001" in block and "ORD-55120" in block and "128.4" in block
    assert "do not summarise" in block


def test_an_empty_case_still_renders():
    assert "(none yet)" in Case().block()


def test_multiple_concerns_are_tracked_separately():
    case = Case()
    case.open_issue("refund for the keyboard")
    case.open_issue("wrong billing address")
    case.resolve_issue(0)

    assert len(case.unresolved) == 1
    assert case.unresolved[0]["description"] == "wrong billing address"


def test_refunds_reach_the_case_block():
    case = Case()
    case.refunds.append({"refund_id": "REF-9001", "order_id": "ORD-55120", "amount": 128.40})
    assert "REF-9001" in case.block()


def test_handoff_carries_what_the_human_cannot_see():
    summary = summarise(
        {
            "customer_id": "CUS-1001",
            "reason_code": "over_ceiling",
            "root_cause": "Monitor never delivered; carrier confirms loss.",
            "recommended_action": "Refund 940 in full.",
            "amount": 940,
            "order_ids": "ORD-55121",
        }
    )

    assert summary["customer_id"] == "CUS-1001"
    assert summary["amount"] == 940.0
    assert summary["order_ids"] == ["ORD-55121"]
    assert summary["reason"] == "Refund exceeds the policy ceiling"


def test_handoff_survives_a_missing_reason_code():
    assert summarise({})["reason_code"] == "no_progress"


def test_handoff_renders_case_facts_alongside_the_summary():
    summary = summarise({"customer_id": "CUS-1001", "reason_code": "policy_gap"}, {"order_total": 128.40})
    assert "order_total = 128.4" in render(summary)


@pytest.mark.asyncio
async def test_escalating_returns_the_filed_handoff():
    result = unwrap(
        await escalate_to_human.handler(
            {
                "customer_id": "CUS-1001",
                "reason_code": "customer_request",
                "root_cause": "Customer asked for a person.",
                "recommended_action": "Take the call.",
                "amount": 0,
                "order_ids": "",
            }
        )
    )

    assert result["escalated"]
    assert result["handoff"]["reason"] == "Customer asked for a human"
