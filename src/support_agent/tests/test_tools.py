import backend
import errors
import pytest
from conftest import unwrap
from tools import (
    ALLOWED_TOOLS,
    TOOLS,
    get_customer,
    lookup_order,
    process_refund,
    qualified,
)


async def call(tool, **args):
    return await tool.handler(args)


@pytest.mark.asyncio
async def test_single_match_verifies_the_customer():
    result = unwrap(await call(get_customer, email="tomas@example.com"))
    assert result["verified"] and result["customer"]["customer_id"] == "CUS-1003"


@pytest.mark.asyncio
async def test_multiple_matches_withhold_the_records():
    raw = await call(get_customer, email=None, order_id=None, postcode=None)
    assert raw["isError"]

    result = unwrap(await call(get_customer, email="priya@example.com", postcode=None, order_id=None))
    assert result["verified"]


@pytest.mark.asyncio
async def test_ambiguous_identifiers_ask_for_another_one():
    # Two customers share a name; searching by nothing but a shared postcode-free hint
    # is what produces the multi-match path.
    backend.CUSTOMERS.append({**backend.CUSTOMERS[0], "customer_id": "CUS-9999"})
    try:
        raw = await call(get_customer, email="priya@example.com")
        result = unwrap(raw)
        assert raw["isError"]
        assert result["match_count"] == 2
        assert "customer" not in result and "customers" not in result
        assert "postcode" in result["customerMessage"]
    finally:
        backend.CUSTOMERS.pop()


@pytest.mark.asyncio
async def test_no_identifiers_is_a_validation_error():
    raw = await call(get_customer)
    assert raw["isError"]
    assert unwrap(raw)["errorCategory"] == errors.VALIDATION


@pytest.mark.asyncio
async def test_no_match_is_a_successful_empty_result_not_an_error():
    raw = await call(get_customer, email="nobody@example.com")
    assert raw["isError"] is False
    assert unwrap(raw)["found"] is False


@pytest.mark.asyncio
async def test_a_customer_with_no_orders_is_also_empty_not_an_error():
    raw = await call(lookup_order, customer_id="CUS-1002")
    assert raw["isError"] is False
    assert unwrap(raw)["found"] is False


@pytest.mark.asyncio
async def test_lookup_returns_normalised_orders():
    order = unwrap(await call(lookup_order, customer_id="CUS-1001", order_id="ORD-55120"))["orders"][0]

    assert order["status"] == "delivered"
    assert order["placed_at"].endswith("Z")
    assert "picker_id" not in order


@pytest.mark.asyncio
async def test_lookup_without_a_customer_id_says_which_tool_to_call_first():
    raw = await call(lookup_order)
    assert "get_customer" in unwrap(raw)["description"]


@pytest.mark.asyncio
async def test_a_non_refundable_order_is_a_business_error_that_is_not_retryable():
    raw = await call(process_refund, customer_id="CUS-1003", order_id="ORD-55190", amount=62, reason="damaged")
    result = unwrap(raw)

    assert result["errorCategory"] == errors.BUSINESS
    assert result["isRetryable"] is False
    assert "customerMessage" in result


@pytest.mark.asyncio
async def test_refunding_more_than_the_order_total_is_refused():
    raw = await call(process_refund, customer_id="CUS-1001", order_id="ORD-55120", amount=500, reason="x")
    assert unwrap(raw)["errorCategory"] == errors.BUSINESS


@pytest.mark.asyncio
async def test_a_valid_refund_is_recorded():
    result = unwrap(await call(process_refund, customer_id="CUS-1001", order_id="ORD-55120", amount=128.40, reason="damaged"))

    assert result["refunded"] and result["refund_id"].startswith("REF-")
    assert len(backend.REFUNDS) == 1


@pytest.mark.asyncio
async def test_an_order_belonging_to_someone_else_is_refused():
    raw = await call(process_refund, customer_id="CUS-1001", order_id="ORD-55190", amount=10, reason="x")
    assert unwrap(raw)["errorCategory"] == errors.VALIDATION


def test_the_tool_surface_stays_small():
    assert len(TOOLS) == 4


def test_every_tool_is_granted_under_its_qualified_name():
    assert ALLOWED_TOOLS == [qualified(t.name) for t in TOOLS]
    assert all(name.startswith("mcp__support__") for name in ALLOWED_TOOLS)


def test_descriptions_point_at_the_alternative_tool():
    described = {t.name: t.description for t in TOOLS}
    assert "lookup_order" in described["get_customer"]
    assert "get_customer" in described["lookup_order"]
    assert "escalate_to_human" in described["process_refund"]


def test_descriptions_carry_inputs_outputs_and_boundaries():
    for tool in TOOLS:
        assert len(tool.description) > 200
        assert "Returns" in tool.description or "returns" in tool.description
