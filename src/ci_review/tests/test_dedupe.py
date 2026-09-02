from conftest import finding
from dedupe import by_pattern, fingerprint, new_only


def test_an_already_posted_finding_is_dropped():
    prior = [finding()]
    assert new_only([finding()], prior) == []


def test_a_new_pattern_in_the_same_file_survives():
    prior = [finding()]
    fresh = finding(detected_pattern="divide-by-len", category="correctness")
    assert new_only([fresh], prior) == [fresh]


def test_the_same_pattern_in_another_file_survives():
    prior = [finding(file="src/orders.py")]
    fresh = finding(file="src/billing.py")
    assert new_only([fresh], prior) == [fresh]


def test_line_movement_does_not_resurrect_a_finding():
    prior = [finding(line=42)]
    assert new_only([finding(line=57)], prior) == []


def test_duplicates_within_one_run_collapse():
    assert len(new_only([finding(), finding()], [])) == 1


def test_fingerprint_ignores_wording():
    assert fingerprint(finding(issue="rephrased")) == fingerprint(finding())


def test_patterns_are_counted_most_frequent_first():
    findings = [finding(), finding(file="b.py"), finding(file="c.py", detected_pattern="divide-by-len")]
    assert list(by_pattern(findings)) == ["fstring-in-execute", "divide-by-len"]


def test_a_finding_without_a_pattern_is_still_counted():
    assert by_pattern([{"severity": "minor"}]) == {"unknown": 1}
