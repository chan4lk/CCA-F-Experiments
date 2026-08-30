"""Argument handling, workspace resolution, and the two gates the CLI keeps shut."""
import pytest

from research_agent_batch_server_tools import state as st
from research_agent_batch_server_tools.cli import (
    build_parser,
    latest_workspace,
    main,
    normalize_argv,
    resolve_workspace,
)


def parse(argv):
    return build_parser().parse_args(argv)


def test_a_bare_question_means_research():
    args = parse(normalize_argv(["how does X price?"]))
    assert args.command == "research" and args.question == "how does X price?"


def test_an_explicit_subcommand_is_left_alone():
    assert normalize_argv(["resume", "--wait"])[0] == "resume"
    assert normalize_argv(["--help"]) == ["--help"]
    assert normalize_argv([]) == []


def test_the_five_subcommands_exist():
    for command in ("research", "resume", "status", "draft", "verify"):
        assert parse([command] + (["q"] if command == "research" else [])).command == command


def test_research_takes_the_intake_the_plugin_asked_for_interactively():
    args = parse(["research", "q", "--client", "Acme", "--audience", "procurement",
                  "--constraints", "no new licences", "--context", "./notes",
                  "--prior", "./old"])
    assert args.client == "Acme" and args.audience == "procurement"
    assert args.context == ["./notes"] and args.prior == ["./old"]


def test_only_the_long_running_commands_take_wait():
    """`status` and `verify` never wait on anything."""
    for command in ("research", "resume", "draft"):
        argv = [command, "q", "--wait"] if command == "research" else [command, "--wait"]
        assert parse(argv).wait is True
    with pytest.raises(SystemExit):
        parse(["status", "--wait"])


def test_research_has_no_workspace_flag():
    """A run derives its workspace from the question's slug; pointing it
    elsewhere would put two runs' claims in one ledger."""
    with pytest.raises(SystemExit):
        parse(["research", "q", "--workspace", "somewhere"])


# --- workspace resolution -------------------------------------------------

def test_the_most_recent_run_is_the_default(tmp_path):
    import os
    for name, mtime in [("old-run", 1_700_000_000), ("new-run", 1_800_000_000)]:
        (tmp_path / "research" / name).mkdir(parents=True)
        os.utime(tmp_path / "research" / name, (mtime, mtime))
    assert latest_workspace(tmp_path).name == "new-run"


def test_no_runs_means_no_workspace(tmp_path):
    assert latest_workspace(tmp_path) is None


def test_a_missing_run_is_reported_rather_than_guessed(tmp_path):
    with pytest.raises(SystemExit, match="no run found"):
        resolve_workspace(parse(["resume", "--cwd", str(tmp_path)]))


def test_an_explicit_workspace_wins(tmp_path):
    args = parse(["verify", "--workspace", str(tmp_path), "--cwd", str(tmp_path)])
    assert resolve_workspace(args) == tmp_path


# --- the human gate -------------------------------------------------------

def test_draft_refuses_a_run_that_has_not_reached_the_gate(tmp_path):
    """The proposal must not inherit claims nobody looked at — so `draft` is a
    separate invocation and it checks the run actually got there."""
    workspace = tmp_path / "research" / "run-a"
    workspace.mkdir(parents=True)
    st.RunState(slug="run-a", workspace=str(workspace),
                intake=st.Intake(question="q"), phase=st.RESEARCH).save()
    with pytest.raises(SystemExit, match="not 'awaiting-approval'"):
        main(["draft", "--cwd", str(tmp_path)])


def test_verify_exits_nonzero_on_a_failing_pack(tmp_path, capsys):
    workspace = tmp_path / "research" / "run-a"
    workspace.mkdir(parents=True)
    (workspace / "evidence-pack.md").write_text("Unsupported assertion [C999].")
    assert main(["verify", "--cwd", str(tmp_path)]) == 1
    assert "GATE: FAIL" in capsys.readouterr().out
    assert (workspace / "verify-report.md").is_file()


def test_verify_exits_zero_on_a_passing_pack(tmp_path, capsys):
    from fixtures.build import make_workspace
    make_workspace(tmp_path)
    assert main(["verify", "--cwd", str(tmp_path)]) == 0
    assert "GATE: PASS" in capsys.readouterr().out


def test_status_and_verify_need_no_api_key(tmp_path, capsys, monkeypatch):
    """The client is built lazily so the two offline commands stay offline."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fixtures.build import make_workspace
    make_workspace(tmp_path)
    assert main(["verify", "--cwd", str(tmp_path)]) == 0
