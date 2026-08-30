"""How one dispatch is configured. No model is called; the options are the unit."""
import pytest

from research_agent.agents import PLANNER, RESEARCHER, SYNTHESIZER, VALIDATOR
from research_agent.runner import AgentRun, _options, agent_budget_usd, record_run
from research_agent.ledger.workspace import read_jsonl


def options(role, tmp_path, schema=None):
    return _options(role, tmp_path, f"{role.name}-1", tmp_path, schema)


def test_a_headless_run_never_waits_on_a_permission_prompt(tmp_path):
    """"dontAsk" denies what is outside the grant instead of prompting. With no
    human at the keyboard, a prompt is a hang."""
    assert options(VALIDATOR, tmp_path).permission_mode == "dontAsk"


def test_everything_in_the_grant_is_pre_allowed(tmp_path):
    """Otherwise `dontAsk` would deny the agent's own tools."""
    opts = options(RESEARCHER, tmp_path)
    assert set(opts.allowed_tools) >= set(opts.tools or [])


def test_the_builtin_tool_list_is_the_grant_minus_mcp(tmp_path):
    """`tools` is what exists at all; MCP tools arrive through mcp_servers."""
    opts = options(RESEARCHER, tmp_path)
    assert opts.tools == ["WebSearch", "WebFetch"]
    assert "mcp__ledger__add_claim" in opts.allowed_tools


def test_the_session_loads_none_of_the_users_settings(tmp_path):
    """Without this the CLI loads settings, CLAUDE.md and installed plugins —
    including the proposal-research plugin this was ported from, whose hooks
    would then fire alongside these ones and double every fetch-log row."""
    opts = options(PLANNER, tmp_path)
    assert opts.setting_sources == []
    assert opts.skills == []
    assert opts.strict_mcp_config is True


def test_only_the_researcher_is_given_the_ledger_server(tmp_path):
    assert "ledger" in options(RESEARCHER, tmp_path).mcp_servers
    for role in (PLANNER, VALIDATOR, SYNTHESIZER):
        assert "ledger" not in options(role, tmp_path).mcp_servers, role.name


def test_each_role_carries_its_own_turn_ceiling_and_model(tmp_path):
    for role in (PLANNER, RESEARCHER, VALIDATOR, SYNTHESIZER):
        opts = options(role, tmp_path)
        assert opts.max_turns == role.max_turns
        assert opts.model == role.model


def test_every_dispatch_has_a_spend_ceiling(tmp_path):
    """One agent that runs away costs this much and then stops, rather than
    taking the whole run's budget with it."""
    assert options(VALIDATOR, tmp_path).max_budget_usd == agent_budget_usd() > 0


def test_the_budget_is_overridable(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_BUDGET_USD", "0.25")
    assert agent_budget_usd() == 0.25


def test_a_nonsense_budget_falls_back_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_BUDGET_USD", "cheap please")
    assert agent_budget_usd() > 0


def test_only_the_validator_carries_the_blindness_guard(tmp_path):
    assert len(options(VALIDATOR, tmp_path).hooks["PreToolUse"]) == 2
    assert len(options(RESEARCHER, tmp_path).hooks["PreToolUse"]) == 1


def test_an_output_schema_is_passed_through(tmp_path):
    schema = {"type": "json_schema", "schema": {"type": "object"}}
    assert options(VALIDATOR, tmp_path, schema).output_format == schema
    assert options(RESEARCHER, tmp_path).output_format is None


# --- cost accounting -----------------------------------------------------

def test_a_dispatch_is_recorded_with_what_it_cost(tmp_path):
    record_run(tmp_path, AgentRun(
        role="validator", agent_id="v1", model="claude-haiku-4-5", cost_usd=0.0123,
        num_turns=3, usage={"input_tokens": 100, "output_tokens": 20,
                            "cache_read_input_tokens": 4000}))
    row = read_jsonl(tmp_path / "run-log.jsonl")[0]
    assert row["role"] == "validator" and row["agent_id"] == "v1"
    assert row["cost_usd"] == 0.0123 and row["cache_read_input_tokens"] == 4000


def test_the_gate_reports_what_the_agents_cost(tmp_path):
    """The plugin measured the orchestrator's context, because the orchestrator
    was a model and its own prose was 65% of the bill. This orchestrator has no
    context to grow, so the agents are the whole bill."""
    from research_agent.gate.verify import _run_economics
    for role, cost in [("validator", 0.01), ("validator", 0.02), ("researcher", 0.5)]:
        record_run(tmp_path, AgentRun(role=role, agent_id="a", model="m",
                                      cost_usd=cost, num_turns=2))
    economics = _run_economics(tmp_path)
    assert economics["dispatches"] == 3
    assert economics["cost_usd"] == pytest.approx(0.53)
    assert economics["by_role"]["validator"]["dispatches"] == 2


def test_no_run_log_means_no_economics_section(tmp_path):
    from research_agent.gate.verify import _run_economics
    assert _run_economics(tmp_path) is None


def test_an_errored_dispatch_is_counted(tmp_path):
    from research_agent.gate.verify import _run_economics
    record_run(tmp_path, AgentRun(role="researcher", agent_id="r1", model="m",
                                  is_error=True, stop_reason="max_turns"))
    assert _run_economics(tmp_path)["errors"] == 1


def test_agent_run_reports_ok():
    assert AgentRun(role="r", agent_id="a", model="m").ok
    assert not AgentRun(role="r", agent_id="a", model="m", is_error=True).ok
