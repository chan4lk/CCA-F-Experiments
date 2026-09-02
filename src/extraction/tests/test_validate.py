from conftest import make_record
from validate import Issue, retryable, validate


def test_clean_record_has_no_issues(record):
    assert validate(record) == []


def test_calculated_total_must_equal_the_line_sum(record):
    issues = validate(make_record(calculated_total=650.00, stated_total=650.00))
    assert any(i.field == "calculated_total" and i.retryable for i in issues)


def test_stated_versus_calculated_mismatch_must_be_flagged():
    issues = validate(make_record(stated_total=700.00))
    assert any(i.field == "conflict_detected" for i in issues)


def test_declared_conflict_is_accepted():
    ok = make_record(stated_total=700.00, conflict_detected=True, conflict_note="printed total is 100 higher")
    assert validate(ok) == []


def test_conflict_without_a_note_is_an_issue():
    issues = validate(make_record(conflict_detected=True, conflict_note=None))
    assert any(i.field == "conflict_note" for i in issues)


def test_non_iso_date_is_retryable():
    issues = validate(make_record(issue_date="14/03/2026"))
    assert [i.field for i in issues] == ["issue_date"]
    assert issues[0].retryable


def test_other_enum_requires_a_detail():
    issues = validate(make_record(payment_terms="other", payment_terms_detail=None))
    assert any(i.field == "payment_terms_detail" for i in issues)


def test_detail_without_other_is_an_issue():
    issues = validate(make_record(currency="USD", currency_detail="USD"))
    assert any(i.field == "currency_detail" for i in issues)


def test_line_arithmetic_is_checked():
    record = make_record(
        line_items=[{"description": "Hours", "quantity": 6, "unit_price": 95.0, "amount": 500.0}],
        calculated_total=500.0,
        stated_total=500.0,
    )
    assert any(i.field == "line_items" for i in validate(record))


def test_absent_from_source_is_not_retryable():
    confidence = {**make_record()["field_confidence"], "vendor_name": 0.0}
    issues = validate(make_record(vendor_name=None, field_confidence=confidence))
    absent = [i for i in issues if i.field == "vendor_name"]
    assert absent and absent[0].retryable is False
    assert retryable(issues) == []


def test_missed_field_is_retryable():
    issues = validate(make_record(vendor_name=None))
    missed = [i for i in issues if i.field == "vendor_name"]
    assert missed and missed[0].retryable is True


def test_issue_renders_field_and_message():
    assert str(Issue("issue_date", "bad", True)) == "[issue_date] bad"
