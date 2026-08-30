"""Model pinning and optional external MCP servers.

Models are pinned to full ids rather than the SDK's aliases. The plugin's
SKILL.md named a tier per phase ("model `haiku`") and let Claude Code resolve
it; here the resolution is visible, so a run's cost profile can be read off
one table and changed in one place.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Role -> model. The pairing is the plugin's, unchanged: cheap first-pass
# validation, an escalation on a different model for anything material, and the
# strongest model on the one job that is pure judgement (gap hunting).
MODELS: dict[str, str] = {
    "planner": "claude-sonnet-5",
    "researcher": "claude-sonnet-5",
    "validator": "claude-haiku-4-5",
    # A material claim needs two CONFIRMED rulings from two different validators
    # running two different models. This is the second one.
    "validator-escalation": "claude-sonnet-5",
    "gap-hunter": "claude-opus-5",
    "synthesizer": "claude-fable-5",
    "proposal-writer": "claude-fable-5",
}


def model_for(role: str) -> str:
    """The pinned model for a role, overridable per role from the environment.

    ``RESEARCH_AGENT_MODEL_VALIDATOR=claude-sonnet-5`` overrides the validator.
    """
    env_key = "RESEARCH_AGENT_MODEL_" + role.upper().replace("-", "_")
    return os.environ.get(env_key) or MODELS[role]


# Every external MCP tool an agent may hold, mapped to the server that provides
# it. An agent's declared tools are filtered against the servers actually
# configured, so a missing server degrades the agent instead of erroring at
# connect() with an unresolvable tool name.
MCP_TOOL_SERVERS: dict[str, str] = {
    "mcp__microsoft_docs_mcp__microsoft_docs_search": "microsoft_docs_mcp",
    "mcp__microsoft_docs_mcp__microsoft_docs_fetch": "microsoft_docs_mcp",
    "mcp__headroom__headroom_compress": "headroom",
}

MCP_CONFIG_ENV = "RESEARCH_AGENT_MCP_CONFIG"


def external_mcp_servers() -> dict[str, Any]:
    """External MCP servers, from the JSON file named by RESEARCH_AGENT_MCP_CONFIG.

    Accepts either a bare ``{name: config}`` mapping or a Claude Code style
    ``{"mcpServers": {...}}`` wrapper. Returns ``{}`` when unset or unreadable —
    the pipeline runs without them, on WebSearch and WebFetch alone.
    """
    path = os.environ.get(MCP_CONFIG_ENV)
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    servers = data.get("mcpServers", data)
    return servers if isinstance(servers, dict) else {}


def available_tools(declared: list[str], servers: dict[str, Any] | None = None) -> list[str]:
    """Drop MCP tools whose server is not configured, keeping order."""
    configured = external_mcp_servers() if servers is None else servers
    return [
        tool for tool in declared
        if tool not in MCP_TOOL_SERVERS or MCP_TOOL_SERVERS[tool] in configured
    ]
