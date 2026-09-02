from conftest import make_record
from review import Decision, audit_sample, route
from validate import Issue, validate


def test_clean_high_confidence_record_is_automatic(record):
    assert route(record, validate(record)).route == "auto"


def test_one_low_confidence_field_routes_to_review(record):
    record["field_confidence"]["issue_date"] = 0.4
    decision = route(record, [])

    assert decision.needs_review
    assert any("issue_date" in r for r in decision.reasons)


def test_aggregate_confidence_does_not_rescue_a_weak_field(record):
    record["field_confidence"] = {**record["field_confidence"], "vendor_name": 0.1}
    assert route(record, []).needs_review


def test_unfixable_issues_are_labelled(record):
    decision = route(record, [Issue("vendor_name", "absent from the source document", retryable=False)])
    assert decision.reasons[0].startswith("unfixable:")


def test_conflict_always_reaches_a_human():
    record = make_record(stated_total=700.0, conflict_detected=True, conflict_note="printed total is 100 higher")
    decision = route(record, validate(record))

    assert decision.needs_review
    assert any(r.startswith("conflict:") for r in decision.reasons)


def test_audit_sample_covers_every_stratum():
    decisions = [("invoice", Decision("auto")) for _ in range(100)]
    decisions += [("receipt", Decision("auto")) for _ in range(3)]

    picked = audit_sample(decisions, rate=0.05, seed=1)
    types = {t for t, _ in picked}

    assert types == {"invoice", "receipt"}


def test_audit_sample_ignores_records_already_going_to_review():
    decisions = [("invoice", Decision("review", ["low confidence"])) for _ in range(10)]
    assert audit_sample(decisions, rate=0.5, seed=1) == []
