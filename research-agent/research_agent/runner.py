"""One dispatch: role in, AgentRun out.

This is where the port earns its keep. In the plugin an agent's identity was
something the pipeline *recovered* — Claude Code stamped an `agent_id` onto the
hook events fired inside a Task-spawned subagent, and the gate read it back out
of the fetch log to prove a validator had opened the page it ruled on. When that
recovery broke, it broke silently and the whole run failed at the gate.

Here identity is minted before the agent starts and closed over by its hooks. A
verdict cannot carry an author it did not have, because the orchestrator writes
the verdict and the orchestrator is what dispatched the validator.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .agents import Role
from .hooks import hooks_for
from .ledger.workspace import append_jsonl, utc_now
from .settings import external_mcp_servers
from .tools import ledger_server

# Per-dispatch spend ceiling. A single agent that runs away costs this much and
# then stops, rather than taking the run's whole budget with it.
DEFAULT_AGENT_BUDGET_USD = 2.0


def agent_budget_usd() -> float:
    try:
        return float(os.environ.get("RESEARCH_AGENT_BUDGET_USD", DEFAULT_AGENT_BUDGET_USD))
    except ValueError:
        return DEFAULT_AGENT_BUDGET_USD


@dataclass
class AgentRun:
    """What one dispatch produced, and what it cost."""

    role: str
    agent_id: str
    model: str
    text: str = ""
    structured: Any = None
    cost_usd: float = 0.0
    num_turns: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    stop_reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.is_error


def _options(role: Role, workspace: Path, agent_id: str, cwd: Path,
             output_schema: dict[str, Any] | None) -> ClaudeAgentOptions:
    servers = external_mcp_servers()
    definition = role.definition(servers)

    mcp_servers: dict[str, Any] = dict(servers)
    if role.name == "researcher":
        # Bound to this run's workspace, so a researcher cannot append to another.
        mcp_servers["ledger"] = ledger_server(workspace)

    builtin = [t for t in (definition.tools or []) if not t.startswith("mcp__")]

    return ClaudeAgentOptions(
        system_prompt=definition.prompt,
        model=definition.model,
        # `tools` is what exists; `allowed_tools` is what runs without a prompt.
        # Both are set: the first is the grant, the second keeps a headless run
        # from stalling on a permission request that no one is there to answer.
        tools=builtin,
        allowed_tools=list(definition.tools or []),
        # "dontAsk" denies anything outside the grant instead of prompting. In a
        # pipeline with no human at the keyboard, a prompt is a hang.
        permission_mode="dontAsk",
        mcp_servers=mcp_servers,
        strict_mcp_config=True,
        # SDK isolation. Without this the CLI loads the user's settings, CLAUDE.md
        # and installed plugins — including the proposal-research plugin this was
        # ported from, whose hooks would then fire alongside these ones.
        setting_sources=[],
        skills=[],
        cwd=str(cwd),
        max_turns=role.max_turns,
        max_budget_usd=agent_budget_usd(),
        hooks=hooks_for(role.name, workspace, agent_id),
        output_format=output_schema,
    )


async def run_agent(role: Role, prompt: str, workspace: Path, cwd: Path | None = None,
                    model: str | None = None, agent_id: str | None = None,
                    output_schema: dict[str, Any] | None = None) -> AgentRun:
    """Dispatch one agent and collect its result.

    ``model`` overrides the role's pinned model — the escalation validator is the
    same role on a different model, and the gate checks that both the id and the
    model differ before it admits a material claim.
    """
    workspace = Path(workspace)
    cwd = Path(cwd) if cwd else Path.cwd()
    agent_id = agent_id or f"{role.name}-{uuid.uuid4().hex[:12]}"

    options = _options(role, workspace, agent_id, cwd, output_schema)
    if model:
        options.model = model

    run = AgentRun(role=role.name, agent_id=agent_id, model=options.model or role.model)
    chunks: list[str] = []

    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            chunks.extend(b.text for b in message.content if isinstance(b, TextBlock))
        elif isinstance(message, ResultMessage):
            run.cost_usd = message.total_cost_usd or 0.0
            run.num_turns = message.num_turns
            run.usage = message.usage or {}
            run.structured = message.structured_output
            run.is_error = message.is_error
            run.stop_reason = message.terminal_reason or message.stop_reason
            if message.result:
                chunks.append(message.result)

    run.text = "\n".join(c for c in chunks if c).strip()
    record_run(workspace, run)
    return run


def record_run(workspace: Path, run: AgentRun) -> None:
    """Append one dispatch to run-log.jsonl.

    The plugin measured the orchestrator's context growth from a hook, because
    the orchestrator was a model and nothing else could see what it cost. This
    orchestrator is a Python function with no context to grow, so the honest
    thing to measure is what the *agents* cost — which is now the whole bill.
    """
    append_jsonl(Path(workspace) / "run-log.jsonl", {
        "ts": utc_now(),
        "role": run.role,
        "agent_id": run.agent_id,
        "model": run.model,
        "cost_usd": round(run.cost_usd, 6),
        "num_turns": run.num_turns,
        "input_tokens": run.usage.get("input_tokens"),
        "output_tokens": run.usage.get("output_tokens"),
        "cache_read_input_tokens": run.usage.get("cache_read_input_tokens"),
        "is_error": run.is_error,
        "stop_reason": run.stop_reason,
    })
