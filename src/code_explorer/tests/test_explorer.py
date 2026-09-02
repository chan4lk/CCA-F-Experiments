import explorer
import prompts
import session as sessions
from agents import EXPLORE
from scratchpad import Finding
from settings import SUBAGENT_MODEL


def test_the_subagent_tool_is_granted_under_its_current_name():
    options = explorer.build_options(sessions.Plan(sessions.FRESH, None, "", []), mcp_servers={})
    assert "Agent" in options.allowed_tools


def test_a_delegation_is_detected_under_both_names():
    assert explorer.is_delegation("Agent")
    assert explorer.is_delegation("Task")
    assert not explorer.is_delegation("Read")


def test_mcp_servers_are_granted_alongside_the_builtins():
    options = explorer.build_options(sessions.Plan(sessions.FRESH, None, "", []), mcp_servers={"github": {}})
    assert "mcp__github" in options.allowed_tools
    assert "Grep" in options.allowed_tools


def test_a_resume_plan_sets_the_resume_option():
    options = explorer.build_options(sessions.Plan(sessions.RESUME, "sess-1", "", []), mcp_servers={})
    assert options.resume == "sess-1"


def test_a_fresh_plan_resumes_nothing():
    options = explorer.build_options(sessions.Plan(sessions.FRESH, None, "", []), mcp_servers={})
    assert options.resume is None


def test_the_session_loads_none_of_the_developers_settings():
    options = explorer.build_options(sessions.Plan(sessions.FRESH, None, "", []), mcp_servers={})
    assert options.setting_sources == [] and options.skills == [] and options.strict_mcp_config


def test_resuming_cleanly_sends_only_the_goal(pad, manifest):
    plan = sessions.Plan(sessions.RESUME, "sess-1", "", [])
    assert explorer.opening_message("why is X slow", plan, pad, manifest) == "why is X slow"


def test_resuming_after_edits_leads_with_what_changed(pad, manifest):
    plan = sessions.Plan(sessions.RESUME_WITH_CHANGES, "sess-1", "", ["gate/verify.py"])
    message = explorer.opening_message("why is X slow", plan, pad, manifest)

    assert message.startswith("These files have changed")
    assert "why is X slow" in message


def test_a_fresh_start_injects_the_summary_not_the_transcript(pad, manifest):
    pad.append(Finding("detail", "body", ["x.py:1"]))
    plan = sessions.Plan(sessions.FRESH, None, "stale", [])
    message = explorer.opening_message("why is X slow", plan, pad, manifest)

    assert "## Established" in message
    assert message.rstrip().endswith("why is X slow")


def test_the_subagent_is_read_only_and_cheap():
    assert set(EXPLORE.tools) == {"Read", "Grep", "Glob"}
    assert EXPLORE.model == SUBAGENT_MODEL


def test_the_subagent_sets_no_effort_level():
    """Haiku 4.5 rejects `effort`; the setting would fail the whole delegation."""
    assert EXPLORE.effort is None


def test_the_subagent_prompt_is_self_contained():
    prompt = prompts.subagent_prompt("where is the gate", "four copies exist", "the file and line")

    assert "no access to the parent conversation" in prompt
    assert "where is the gate" in prompt and "four copies exist" in prompt
    assert "path:line" in prompt


def test_the_system_prompt_teaches_tool_selection_not_guessing():
    assert "Grep for CONTENT" in prompts.SYSTEM
    assert "Glob for PATHS" in prompts.SYSTEM
    assert "Read the file and Write it back" in prompts.SYSTEM


def test_the_system_prompt_forbids_reading_everything_first():
    assert "Reading every file first" in prompts.SYSTEM


def test_the_system_prompt_expects_the_plan_to_change():
    assert "re-rank" in prompts.SYSTEM.lower()


def test_dotenv_is_loaded_at_import(monkeypatch):
    """The Agent SDK spawns the `claude` CLI, which inherits os.environ. Without this a
    local run authenticates only if the key is already exported by hand.

    load_dotenv() resolves the .env from this module's own directory upward, so it finds
    the repo root one whatever the cwd. The call is what is asserted; asserting on the
    key's value would print a real secret on failure.
    """
    import importlib

    import dotenv

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append(True))

    import explorer

    importlib.reload(explorer)

    assert calls, "explorer must call load_dotenv() at import"


def test_the_model_is_pinned_to_a_full_id(monkeypatch):
    """Full ids, not aliases - an alias moves under you between runs."""
    import importlib

    import settings

    monkeypatch.delenv("EXPLORER_MODEL", raising=False)
    importlib.reload(settings)

    assert settings.MODEL == "claude-haiku-4-5"


def test_the_model_can_be_overridden_per_run(monkeypatch):
    import importlib

    import settings

    monkeypatch.setenv("EXPLORER_MODEL", "claude-sonnet-5")
    importlib.reload(settings)
    try:
        assert settings.MODEL == "claude-sonnet-5"
    finally:
        monkeypatch.delenv("EXPLORER_MODEL", raising=False)
        importlib.reload(settings)


def test_the_subagent_model_is_pinned_too(monkeypatch):
    import importlib

    import settings

    monkeypatch.delenv("EXPLORER_SUBAGENT_MODEL", raising=False)
    importlib.reload(settings)

    assert settings.SUBAGENT_MODEL == "claude-haiku-4-5"
