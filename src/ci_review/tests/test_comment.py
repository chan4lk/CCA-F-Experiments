from comment import body, review_payload
from conftest import finding


def test_comment_anchors_to_file_and_line():
    payload = review_payload([finding()])
    assert payload["comments"] == [
        {"path": "src/orders.py", "line": 42, "body": payload["comments"][0]["body"]}
    ]


def test_comment_carries_the_failing_input():
    assert "1 OR 1=1" in body(finding())


def test_comment_exposes_the_pattern_slug_for_dismissal_tracking():
    assert "fstring-in-execute" in body(finding())
    assert "not-an-issue" in body(finding())


def test_findings_are_posted_as_one_review():
    payload = review_payload([finding(), finding(file="b.py")])
    assert payload["event"] == "COMMENT"
    assert len(payload["comments"]) == 2


def test_summary_counts_by_severity():
    payload = review_payload([finding(severity="blocking"), finding(file="b.py", severity="minor")])
    assert payload["body"] == "2 finding(s): 1 blocking, 1 minor."


def test_a_clean_review_says_so():
    assert review_payload([])["body"] == "No findings in the reportable categories."
