"""Wiring."""

import prompts
import tools
from case import Case
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher
from dotenv import load_dotenv
from hooks import Gate, Normalizer
from settings import MAX_BUDGET_USD, MODEL

# Puts ANTHROPIC_API_KEY from .env into os.environ, which the CLI subprocess the SDK
# spawns inherits. Without it a local run authenticates only if the key is already exported.
load_dotenv()


def build_options(case: Case | None = None, model: str = MODEL) -> tuple[ClaudeAgentOptions, Case]:
    case = case or Case()
    gate, normalizer = Gate(case), Normalizer(case)

    options = ClaudeAgentOptions(
        system_prompt=prompts.with_case(case.block()),
        mcp_servers={tools.SERVER_NAME: tools.server()},
        allowed_tools=tools.ALLOWED_TOOLS,
        model=model,
        max_budget_usd=MAX_BUDGET_USD,
        hooks={
            "PreToolUse": [HookMatcher(matcher=None, hooks=[gate])],
            "PostToolUse": [HookMatcher(matcher=None, hooks=[normalizer])],
        },
        # None of the developer's settings. Without this the CLI loads the local
        # CLAUDE.md and every installed plugin into a customer support session.
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
    )
    return options, case


async def run(message: str, case: Case | None = None):
    options, case = build_options(case)
    async with ClaudeSDKClient(options=options) as client:
        await client.query(message)
        async for event in client.receive_response():
            yield event
