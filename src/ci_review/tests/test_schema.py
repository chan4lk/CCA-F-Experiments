from schema import FINDING, FINDINGS, TESTS


def test_findings_schema_is_closed():
    assert FINDINGS["additionalProperties"] is False
    assert FINDING["additionalProperties"] is False
    assert set(FINDING["required"]) == set(FINDING["properties"])


def test_every_finding_must_name_a_failing_input():
    assert "failure_input" in FINDING["required"]


def test_every_finding_carries_a_pattern_slug():
    assert "detected_pattern" in FINDING["required"]


def test_severity_and_category_are_closed_enums():
    assert FINDING["properties"]["severity"]["enum"] == ["blocking", "important", "minor"]
    assert "style" not in FINDING["properties"]["category"]["enum"]


def test_test_proposals_must_justify_themselves():
    item = TESTS["properties"]["tests"]["items"]
    assert "why_uncovered" in item["required"]
