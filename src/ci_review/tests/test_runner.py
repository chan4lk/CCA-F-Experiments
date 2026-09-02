import json

import pytest
from conftest import Completed, FakeCLI
from runner import ReviewError, build_command, parse_envelope, run
from schema import FINDINGS


def test_print_flag_is_present_so_ci_cannot_hang():
    assert "-p" in build_command("system", FINDINGS)


def test_output_is_json_constrained_by_the_schema():
    command = build_command("system", FINDINGS)
    assert command[command.index("--output-format") + 1] == "json"
    assert json.loads(command[command.index("--json-schema") + 1]) == FINDINGS


def test_the_reviewer_is_read_only():
    command = build_command("system", FINDINGS)
    tools = command[command.index("--allowed-tools") + 1 :]
    assert "Write" not in tools and "Edit" not in tools and "Bash" not in tools


def test_budget_is_capped():
    assert "--max-budget-usd" in build_command("system", FINDINGS)


def test_envelope_result_may_be_an_object():
    stdout = json.dumps({"is_error": False, "result": {"findings": []}})
    assert parse_envelope(stdout) == {"findings": []}


def test_envelope_result_may_be_a_json_string():
    stdout = json.dumps({"is_error": False, "result": json.dumps({"findings": [1]})})
    assert parse_envelope(stdout) == {"findings": [1]}


def test_cli_error_flag_is_surfaced():
    stdout = json.dumps({"is_error": True, "result": "budget exceeded"})
    with pytest.raises(ReviewError, match="budget exceeded"):
        parse_envelope(stdout)


def test_non_json_output_is_surfaced():
    with pytest.raises(ReviewError, match="did not return JSON"):
        parse_envelope("Usage: claude [options]")


def test_non_zero_exit_is_surfaced():
    cli = FakeCLI(returncode=1, stderr="boom")
    with pytest.raises(ReviewError, match="exited 1"):
        run("prompt", "system", FINDINGS, runner=cli)


def test_prompt_is_passed_on_stdin_not_argv():
    cli = FakeCLI()
    run("the prompt", "system", FINDINGS, runner=cli)
    assert cli.prompts == ["the prompt"]
    assert "the prompt" not in cli.commands[0]


def test_completed_helper_defaults_are_success():
    assert Completed().returncode == 0


def test_dotenv_is_loaded_at_import(monkeypatch):
    """The `claude` subprocess inherits os.environ, so ANTHROPIC_API_KEY has to be in
    os.environ before it is spawned - a .env the parent never read reaches nothing.

    load_dotenv() resolves the .env from this module's own directory upward, so it finds
    the repo root one whatever the cwd. The call is what is asserted; asserting on the
    key's value would print a real secret on failure.
    """
    import importlib

    import dotenv

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append(True))

    import runner

    importlib.reload(runner)

    assert calls, "runner must call load_dotenv() at import"


def test_the_model_is_pinned_to_a_full_id(monkeypatch):
    """Full ids, not aliases - an alias moves under you between runs."""
    import importlib

    import settings

    monkeypatch.delenv("CI_REVIEW_MODEL", raising=False)
    importlib.reload(settings)

    assert settings.MODEL == "claude-haiku-4-5"


def test_the_model_can_be_overridden_per_run(monkeypatch):
    import importlib

    import settings

    monkeypatch.setenv("CI_REVIEW_MODEL", "claude-sonnet-5")
    importlib.reload(settings)
    try:
        assert settings.MODEL == "claude-sonnet-5"
    finally:
        monkeypatch.delenv("CI_REVIEW_MODEL", raising=False)
        importlib.reload(settings)
