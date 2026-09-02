import pytest
from conftest import denied, payload, reason
from hooks import Gate


@pytest.mark.asyncio
async def test_refund_is_blocked_before_identity_is_verified(case):
    gate = Gate(case)
    result = await gate(payload("process_refund", customer_id="CUS-1001", order_id="ORD-55120", amount=50), "t", None)

    assert denied(result)
    assert "get_customer" in reason(result)


@pytest.mark.asyncio
async def test_refund_is_allowed_after_verification(verified_case):
    gate = Gate(verified_case)
    result = await gate(payload("process_refund", customer_id="CUS-1001", order_id="ORD-55120", amount=50), "t", None)

    assert not denied(result)


@pytest.mark.asyncio
async def test_refund_for_a_different_customer_is_blocked(verified_case):
    gate = Gate(verified_case)
    result = await gate(payload("process_refund", customer_id="CUS-1003", order_id="ORD-55190", amount=10), "t", None)

    assert denied(result)
    assert "CUS-1003" in reason(result) and "CUS-1001" in reason(result)


@pytest.mark.asyncio
async def test_amount_above_the_ceiling_is_blocked(verified_case):
    gate = Gate(verified_case, ceiling=500)
    result = await gate(payload("process_refund", customer_id="CUS-1001", order_id="ORD-55121", amount=940), "t", None)

    assert denied(result)
    assert "escalate_to_human" in reason(result)
    assert "over_ceiling" in reason(result)


@pytest.mark.asyncio
async def test_amount_at_the_ceiling_is_allowed(verified_case):
    gate = Gate(verified_case, ceiling=500)
    result = await gate(payload("process_refund", customer_id="CUS-1001", order_id="ORD-55121", amount=500), "t", None)

    assert not denied(result)


@pytest.mark.asyncio
async def test_reads_are_never_gated(case):
    gate = Gate(case)
    for tool in ("get_customer", "lookup_order", "escalate_to_human"):
        assert not denied(await gate(payload(tool), "t", None))


@pytest.mark.asyncio
async def test_denials_are_recorded_for_observability(case):
    gate = Gate(case)
    await gate(payload("process_refund", customer_id="CUS-1001", amount=10), "t", None)

    assert gate.denials and gate.denials[0][0] == "process_refund"


@pytest.mark.asyncio
async def test_the_unqualified_tool_name_is_matched_too(case):
    gate = Gate(case)
    result = await gate({"tool_name": "process_refund", "tool_input": {"amount": 10}}, "t", None)

    assert denied(result)
