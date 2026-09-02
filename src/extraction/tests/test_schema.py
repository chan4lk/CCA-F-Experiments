import pytest
from schema import TOOLS, TOOLS_BY_NAME


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_strict_mode_preconditions(tool):
    schema = tool["input_schema"]
    assert tool["strict"] is True
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_optional_fields_are_nullable(tool):
    props = tool["input_schema"]["properties"]
    for name in ("vendor_name", "document_number", "issue_date", "stated_total"):
        assert "null" in props[name]["type"], f"{name} must be nullable or the model invents a value"


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_categorical_enums_are_extensible(tool):
    props = tool["input_schema"]["properties"]
    enums = [p for p in props.values() if "enum" in p]
    assert enums
    for prop in enums:
        assert "unclear" in prop["enum"]
        assert "other" in prop["enum"]


def test_totals_are_two_independent_fields():
    props = TOOLS_BY_NAME["extract_invoice"]["input_schema"]["properties"]
    assert "stated_total" in props and "calculated_total" in props


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t["name"])
def test_confidence_is_per_field(tool):
    confidence = tool["input_schema"]["properties"]["field_confidence"]
    assert len(confidence["properties"]) > 1


def test_descriptions_differentiate_the_two_tools():
    invoice = TOOLS_BY_NAME["extract_invoice"]["description"]
    receipt = TOOLS_BY_NAME["extract_receipt"]["description"]
    assert "extract_receipt" in invoice and "extract_invoice" in receipt
