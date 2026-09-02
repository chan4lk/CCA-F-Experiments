import prompts
import tools
from agent import build_options
from case import Case
from settings import REFUND_CEILING_USD


def test_escalation_triggers_are_explicit():
    for trigger in ("asks for a human", "silent or ambiguous", "cannot make meaningful progress"):
        assert trigger in prompts.SYSTEM


def test_the_unreliable_escalation_proxies_are_ruled_out():
    assert "Do not escalate because the customer is angry" in prompts.SYSTEM
    assert "Frustration is not complexity" in prompts.SYSTEM


def test_the_angry_pair_is_shown_both_ways():
    assert prompts.SYSTEM.count("This is ridiculous") == 2


def test_multiple_matches_are_answered_by_asking_not_guessing():
    assert "refunds the wrong person's card" in prompts.SYSTEM


def test_empty_results_are_distinguished_from_failures():
    assert "Empty is an answer" in prompts.SYSTEM


def test_the_ceiling_in_the_prompt_tracks_the_enforced_one():
    assert f"{REFUND_CEILING_USD:.0f}" in prompts.SYSTEM


def test_case_facts_are_injected_into_the_system_prompt():
    case = Case()
    case.verify("CUS-1001")
    assert "CUS-1001" in prompts.with_case(case.block())


def test_the_session_loads_none_of_the_developers_settings():
    options, _ = build_options()
    assert options.setting_sources == []
    assert options.skills == []
    assert options.strict_mcp_config is True


def test_only_the_four_support_tools_are_granted():
    options, _ = build_options()
    assert options.allowed_tools == tools.ALLOWED_TOOLS
    assert not any(t in options.allowed_tools for t in ("Bash", "Read", "WebSearch"))


def test_both_hook_events_are_registered():
    options, _ = build_options()
    assert set(options.hooks) == {"PreToolUse", "PostToolUse"}


def test_the_hooks_share_one_case_with_the_caller():
    case = Case()
    _, returned = build_options(case)
    assert returned is case


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

    import agent

    importlib.reload(agent)

    assert calls, "agent must call load_dotenv() at import"


def test_the_model_is_pinned_to_a_full_id(monkeypatch):
    """Full ids, not aliases - an alias moves under you between runs."""
    import importlib

    import settings

    monkeypatch.delenv("SUPPORT_MODEL", raising=False)
    importlib.reload(settings)

    assert settings.MODEL == "claude-haiku-4-5"


def test_the_model_can_be_overridden_per_run(monkeypatch):
    import importlib

    import settings

    monkeypatch.setenv("SUPPORT_MODEL", "claude-sonnet-5")
    importlib.reload(settings)
    try:
        assert settings.MODEL == "claude-sonnet-5"
    finally:
        monkeypatch.delenv("SUPPORT_MODEL", raising=False)
        importlib.reload(settings)
