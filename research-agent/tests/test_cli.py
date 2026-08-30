"""Argument handling and the two gates the CLI is responsible for keeping shut."""
import pytest

from research_agent.cli import (
    build_parser,
    latest_workspace,
    main,
    normalize_argv,
    resolve_workspace,
)


def parse(argv):
    return build_parser().parse_args(argv)


def test_a_bare_question_means_research():
    """`research_agent "how does X price?"` should not have to say `research`."""
    args = parse(normalize_argv(["how does X price?"]))
    assert args.command == "research" and args.question == "how does X price?"


def test_an_explicit_subcommand_is_left_alone():
    assert normalize_argv(["verify", "--pack", "proposal.md"])[0] == "verify"
    assert normalize_argv(["--help"]) == ["--help"]
    assert normalize_argv([]) == []


def test_the_three_subcommands_exist():
    for command in ("research", "draft", "verify"):
        assert parse([command] + (["q"] if command == "research" else [])).command == command


def test_research_takes_the_intake_the_plugin_asked_for_interactively():
    args = parse(["research", "q", "--client", "Acme", "--audience", "procurement",
                  "--constraints", "no new licences", "--context", "./notes",
                  "--prior", "./old-run"])
    assert args.client == "Acme" and args.audience == "procurement"
    assert args.constraints == "no new licences"
    assert args.context == ["./notes"] and args.prior == ["./old-run"]


def test_repeatable_paths_accumulate():
    args = parse(["research", "q", "--context", "a", "--context", "b"])
    assert args.context == ["a", "b"]


def test_verify_can_target_the_proposal():
    assert parse(["verify", "--pack", "proposal.md"]).pack == "proposal.md"


def test_research_has_no_workspace_flag():
    """A research run derives its workspace from the question's slug. Letting a
    caller point it elsewhere would put two runs' claims in one ledger."""
    with pytest.raises(SystemExit):
        parse(["research", "q", "--workspace", "somewhere"])


# --- workspace resolution ------------------------------------------------

def test_the_most_recent_run_is_the_default(tmp_path):
    import os
    root = tmp_path / "research"
    for name, mtime in [("old-run", 1_700_000_000), ("new-run", 1_800_000_000)]:
        (root / name).mkdir(parents=True)
        os.utime(root / name, (mtime, mtime))
    assert latest_workspace(tmp_path).name == "new-run"


def test_no_runs_means_no_workspace(tmp_path):
    assert latest_workspace(tmp_path) is None


def test_an_explicit_workspace_wins(tmp_path):
    args = parse(["verify", "--workspace", str(tmp_path), "--cwd", str(tmp_path)])
    assert resolve_workspace(args) == tmp_path


def test_a_missing_run_is_reported_rather_than_guessed(tmp_path):
    args = parse(["verify", "--cwd", str(tmp_path)])
    with pytest.raises(SystemExit, match="no run found"):
        resolve_workspace(args)


# --- exit codes ----------------------------------------------------------

def test_verify_exits_nonzero_on_a_failing_pack(tmp_path, capsys):
    workspace = tmp_path / "research" / "run-a"
    workspace.mkdir(parents=True)
    (workspace / "evidence-pack.md").write_text("Unsupported assertion [C999].",
                                                encoding="utf-8")
    assert main(["verify", "--cwd", str(tmp_path)]) == 1
    assert "GATE: FAIL" in capsys.readouterr().out
    assert (workspace / "verify-report.md").is_file()


def test_verify_exits_zero_on_a_passing_pack(tmp_path, capsys):
    from fixtures.build import make_workspace
    make_workspace(tmp_path)
    assert main(["verify", "--cwd", str(tmp_path)]) == 0
    assert "GATE: PASS" in capsys.readouterr().out


def test_the_question_is_recovered_from_the_plan_for_a_later_draft(tmp_path):
    """`draft` may run days later in a fresh process; it should not need the
    original question typed again."""
    from research_agent.cli import _question_of
    workspace = tmp_path / "run-a"
    workspace.mkdir()
    (workspace / "plan.md").write_text("# Copilot Studio MCP limits\n\n## Q1 — x\n")
    assert _question_of(workspace) == "Copilot Studio MCP limits"


def test_a_run_with_no_plan_falls_back_to_its_slug(tmp_path):
    from research_agent.cli import _question_of
    workspace = tmp_path / "mcp-tool-limits"
    workspace.mkdir()
    assert _question_of(workspace) == "mcp tool limits"
