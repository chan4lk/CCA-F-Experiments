import json

import pytest
from conftest import response
from hooks import Normalizer


def output(result):
    return json.loads(result["hookSpecificOutput"]["updatedMCPToolOutput"]["content"][0]["text"])


@pytest.mark.asyncio
async def test_unix_timestamps_become_iso_before_the_model_sees_them(case):
    hook = Normalizer(case)
    raw = {"found": True, "orders": [{"order_id": "ORD-1", "status_code": 30, "placed_at": 1771286400, "delivered_at": None}]}

    result = await hook(response("lookup_order", raw), "t", None)
    order = output(result)["orders"][0]

    assert order["placed_at"] == "2026-02-17T00:00:00Z"
    assert order["delivered_at"] is None


@pytest.mark.asyncio
async def test_numeric_status_codes_become_names(case):
    hook = Normalizer(case)
    raw = {"found": True, "orders": [{"order_id": "ORD-1", "status_code": 20, "placed_at": 1771286400}]}

    assert output(await hook(response("lookup_order", raw), "t", None))["orders"][0]["status"] == "shipped"


@pytest.mark.asyncio
async def test_verbose_fields_are_trimmed_out_of_context(case):
    hook = Normalizer(case)
    raw = {
        "found": True,
        "orders": [
            {
                "order_id": "ORD-1",
                "status_code": 30,
                "placed_at": 1771286400,
                "route_hash": "9f2c11ab",
                "picker_id": "EMP-224",
                "insurance_band": 2,
            }
        ],
    }
    order = output(await hook(response("lookup_order", raw), "t", None))["orders"][0]

    assert "route_hash" not in order and "picker_id" not in order
    assert order["order_id"] == "ORD-1"


@pytest.mark.asyncio
async def test_verification_is_captured_from_the_tool_result(case):
    hook = Normalizer(case)
    raw = {"found": True, "verified": True, "customer": {"customer_id": "CUS-1001", "created_at": "2024-11-02T09:14:00Z"}}

    await hook(response("get_customer", raw), "t", None)

    assert case.verified_customer_id == "CUS-1001"


@pytest.mark.asyncio
async def test_a_multiple_match_result_does_not_verify_anyone(case):
    hook = Normalizer(case)
    await hook(response("get_customer", {"errorCategory": "validation", "match_count": 2}, is_error=True), "t", None)

    assert not case.verified


@pytest.mark.asyncio
async def test_order_facts_are_captured_for_the_case_block(case):
    hook = Normalizer(case)
    raw = {"found": True, "orders": [{"order_id": "ORD-1", "status_code": 30, "placed_at": 1771286400, "total": 128.4, "currency": "GBP"}]}

    await hook(response("lookup_order", raw), "t", None)

    assert case.orders["ORD-1"]["total"] == 128.4


@pytest.mark.asyncio
async def test_non_json_tool_output_passes_through_untouched(case):
    hook = Normalizer(case)
    result = await hook({"tool_name": "lookup_order", "tool_response": {"content": [{"type": "text", "text": "not json"}]}}, "t", None)

    assert result == {}
