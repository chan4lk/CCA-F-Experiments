"""Model pinning and MCP degradation."""
import json

from research_agent.settings import (
    MCP_CONFIG_ENV,
    MODELS,
    available_tools,
    external_mcp_servers,
    model_for,
)


def test_every_role_has_a_pinned_model():
    for role in ("planner", "researcher", "validator", "validator-escalation",
                 "gap-hunter", "synthesizer", "proposal-writer"):
        assert MODELS[role].startswith("claude-")


def test_a_model_can_be_overridden_per_role(monkeypatch):
    monkeypatch.setenv("RESEARCH_AGENT_MODEL_VALIDATOR", "claude-sonnet-5")
    assert model_for("validator") == "claude-sonnet-5"
    assert model_for("planner") == MODELS["planner"]


def test_the_escalation_role_maps_to_its_own_env_var(monkeypatch):
    """The hyphen has to become an underscore or the override silently misses."""
    monkeypatch.setenv("RESEARCH_AGENT_MODEL_VALIDATOR_ESCALATION", "claude-opus-5")
    assert model_for("validator-escalation") == "claude-opus-5"


# --- MCP configuration ---------------------------------------------------

def test_no_config_means_no_external_servers(monkeypatch):
    monkeypatch.delenv(MCP_CONFIG_ENV, raising=False)
    assert external_mcp_servers() == {}


def test_a_bare_mapping_is_accepted(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"headroom": {"command": "headroom"}}))
    monkeypatch.setenv(MCP_CONFIG_ENV, str(path))
    assert "headroom" in external_mcp_servers()


def test_the_claude_code_wrapper_shape_is_accepted(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"headroom": {"command": "headroom"}}}))
    monkeypatch.setenv(MCP_CONFIG_ENV, str(path))
    assert "headroom" in external_mcp_servers()


def test_an_unreadable_config_degrades_rather_than_raising(tmp_path, monkeypatch):
    """The pipeline runs on WebSearch and WebFetch alone. A broken optional
    config should cost the optional tools, not the run."""
    path = tmp_path / "mcp.json"
    path.write_text("{ not json")
    monkeypatch.setenv(MCP_CONFIG_ENV, str(path))
    assert external_mcp_servers() == {}

    monkeypatch.setenv(MCP_CONFIG_ENV, str(tmp_path / "missing.json"))
    assert external_mcp_servers() == {}


# --- tool filtering ------------------------------------------------------

def test_builtin_tools_are_never_filtered():
    assert available_tools(["WebFetch", "Bash", "Read"], {}) == ["WebFetch", "Bash", "Read"]


def test_an_mcp_tool_is_dropped_when_its_server_is_absent():
    """An unresolvable tool name is a connect-time error; a missing optional
    server should degrade the agent instead of failing the run."""
    assert available_tools(["WebFetch", "mcp__headroom__headroom_compress"], {}) == ["WebFetch"]


def test_an_mcp_tool_survives_when_its_server_is_present():
    tools = ["mcp__microsoft_docs_mcp__microsoft_docs_search"]
    assert available_tools(tools, {"microsoft_docs_mcp": {}}) == tools


def test_the_in_process_ledger_tool_is_never_filtered_out():
    """It is served from this process, not from a configured server — filtering
    it would leave the researcher with no way to record anything."""
    from research_agent.agents import ADD_CLAIM_TOOL
    assert available_tools([ADD_CLAIM_TOOL], {}) == [ADD_CLAIM_TOOL]


def test_order_is_preserved():
    tools = ["WebSearch", "WebFetch", "mcp__headroom__headroom_compress", "Bash"]
    assert available_tools(tools, {}) == ["WebSearch", "WebFetch", "Bash"]
