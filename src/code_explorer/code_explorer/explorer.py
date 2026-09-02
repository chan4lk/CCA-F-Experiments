"""Wiring and the run loop."""

import mcp_config
import prompts
import session as sessions
from agents import AGENTS
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from dotenv import load_dotenv
from scratchpad import Manifest, Scratchpad
from settings import MAX_BUDGET_USD, MODEL

# Puts ANTHROPIC_API_KEY from .env into os.environ, which the CLI subprocess the SDK
# spawns inherits. Without it a local run authenticates only if the key is already exported.
load_dotenv()

# Agent is the current name for the subagent tool; system:init and permission denials
# still report it as Task, so anything that DETECTS a delegation must match both.
SUBAGENT_TOOLS = ("Agent", "Task")

BASE_TOOLS = ["Read", "Grep", "Glob", "Agent"]


def build_options(plan: sessions.Plan, mcp_servers: dict | None = None, model: str = MODEL) -> ClaudeAgentOptions:
    servers = mcp_servers if mcp_servers is not None else mcp_config.load()
    return ClaudeAgentOptions(
        system_prompt=prompts.SYSTEM,
        allowed_tools=BASE_TOOLS + [f"mcp__{name}" for name in servers],
        tools=BASE_TOOLS,
        agents=AGENTS,
        mcp_servers=servers,
        model=model,
        max_budget_usd=MAX_BUDGET_USD,
        resume=plan.session_id if plan.resuming else None,
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
    )


def opening_message(goal: str, plan: sessions.Plan, pad: Scratchpad, manifest: Manifest | None) -> str:
    if plan.action == sessions.RESUME:
        return goal
    if plan.action == sessions.RESUME_WITH_CHANGES:
        return f"{sessions.change_notice(plan.changed_files)}\n\n{goal}"
    if manifest is None:
        return goal
    # Fresh session, prior work worth keeping: the summary goes in as context rather
    # than the stale transcript.
    return f"{pad.summary(manifest)}\n\n---\n\n{goal}"


def is_delegation(tool_name: str) -> bool:
    return tool_name in SUBAGENT_TOOLS


async def run(goal: str, changed_files: list[str] | None = None, workspace=None):
    pad = Scratchpad(workspace)
    manifest = pad.load()
    plan = sessions.decide(manifest, changed_files)

    options = build_options(plan)
    manifest = manifest or Manifest(goal=goal)
    manifest.goal = goal

    async with ClaudeSDKClient(options=options) as client:
        await client.query(opening_message(goal, plan, pad, manifest))
        async for event in client.receive_response():
            session_id = getattr(event, "session_id", None)
            if session_id:
                manifest.session_id = session_id
                pad.save(manifest)
            yield plan, event
