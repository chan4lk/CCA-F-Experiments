import review as reviewer
from conftest import FakeCLI, FakeGit, finding
from schema import FINDINGS, TESTS


def test_every_changed_file_gets_its_own_pass(monkeypatch):
    monkeypatch.setattr(reviewer, "diff_for", lambda base, path=None, git=None: "diff")
    monkeypatch.setattr(reviewer, "read", lambda path: "source")

    cli = FakeCLI()
    reviewer.review("main", ["a.py", "b.py"], runner=cli)

    assert len(cli.commands) == 3  # two file passes plus one integration pass


def test_the_last_pass_is_the_cross_file_one(monkeypatch):
    monkeypatch.setattr(reviewer, "diff_for", lambda base, path=None, git=None: "diff")
    monkeypatch.setattr(reviewer, "read", lambda path: "source")

    cli = FakeCLI()
    reviewer.review("main", ["a.py"], runner=cli)

    assert "ACROSS files" in cli.prompts[-1]
    assert "ACROSS files" not in cli.prompts[0]


def test_findings_from_all_passes_are_merged(monkeypatch):
    monkeypatch.setattr(reviewer, "diff_for", lambda base, path=None, git=None: "diff")
    monkeypatch.setattr(reviewer, "read", lambda path: "source")

    cli = FakeCLI(payloads=[
        {"findings": [finding(file="a.py")]},
        {"findings": [finding(file="b.py", category="api-contract", detected_pattern="signature-change")]},
    ])
    findings = reviewer.review("main", ["a.py"], runner=cli)

    assert {f["file"] for f in findings} == {"a.py", "b.py"}


def test_prior_findings_are_filtered_out_of_the_result(monkeypatch):
    monkeypatch.setattr(reviewer, "diff_for", lambda base, path=None, git=None: "diff")
    monkeypatch.setattr(reviewer, "read", lambda path: "source")

    cli = FakeCLI(payloads=[{"findings": [finding()]}, {"findings": []}])
    assert reviewer.review("main", ["src/orders.py"], [finding()], runner=cli) == []


def test_changed_files_come_from_the_three_dot_range():
    git = FakeGit(names=["a.py", "b.py"])
    assert reviewer.changed_files("origin/main", git=git) == ["a.py", "b.py"]


def test_diff_for_a_single_file_is_path_scoped():
    seen = []

    def git(command, **kwargs):
        seen.append(command)
        return type("C", (), {"stdout": "diff"})()

    reviewer.diff_for("main", "a.py", git=git)
    assert seen[0][-2:] == ["--", "a.py"]


def test_missing_file_reads_as_empty(tmp_path):
    assert reviewer.read(str(tmp_path / "gone.py")) == ""


def test_blocking_filters_by_severity():
    findings = [finding(severity="blocking"), finding(severity="minor", detected_pattern="x")]
    assert reviewer.blocking(findings) == [findings[0]]


def test_test_proposals_use_the_tests_schema(monkeypatch, tmp_path):
    source = tmp_path / "orders.py"
    source.write_text("def f(): pass")
    tests = tmp_path / "test_orders.py"
    tests.write_text("def test_f(): pass")

    cli = FakeCLI(payloads=[{"tests": [{"target": "f", "name": "test_empty", "why_uncovered": "empty list", "code": "..."}]}])
    proposals = reviewer.propose_tests(str(source), str(tests), runner=cli)

    import json as _json
    schema = _json.loads(cli.commands[0][cli.commands[0].index("--json-schema") + 1])
    assert schema == TESTS and schema != FINDINGS
    assert proposals[0]["why_uncovered"] == "empty list"
