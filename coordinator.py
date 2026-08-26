import os
import sys
from dotenv import load_dotenv

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    query,
    SystemMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

load_dotenv()

# --------------------------------------------------------------------- log ---
# Instrumentation only - it does not change the flow.
# Run with LOG=0 to print just the final cited report:  LOG=0 uv run coordinator.py "..."

LOG = os.environ.get("LOG", "1") != "0"

MODEL = "claude-haiku-4-5"
SUBAGENT = "search-agent"

# The tool was renamed from `Task` to `Agent` in Claude Code v2.1.63, but the
# old name still surfaces in some payloads. Match both when detecting delegations.
DELEGATION_TOOLS = ("Task", "Agent")


def log(msg=""):
    if LOG:
        print(msg)


def rule(title):
    log(f"\n{'=' * 68}")
    log(title)
    log("=" * 68)


def preview(value, limit=90):
    """Collapse any value to one capped line so the trace stays readable."""
    s = " ".join(str(value).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def blocks_of(message):
    """`content` is normally a list of blocks, but can arrive as a plain str."""
    content = getattr(message, "content", None) or []
    if isinstance(content, str):
        return [TextBlock(text=content)]
    return content


def main_prompt():
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    return input("Enter your question: ")


async def main():
    question = main_prompt()

    search_agent = AgentDefinition(
        description=(
            "Searches the web for primary sources. Give it ONE self-contained "
            "question; it returns findings with a source URL for every claim."
        ),
        prompt=(
            "You are a research search agent. Use WebSearch and WebFetch to "
            "search, read, and report concise findings. Every claim must carry "
            "the URL you got it from. Never answer from memory - if you did not "
            "fetch it, do not claim it."
        ),
        tools=["WebSearch", "WebFetch"],
        model=MODEL,
    )

    options = ClaudeAgentOptions(
        system_prompt=(
            "Goal: produce a cited report.\n"
            "Break the question into independent sub-questions and delegate each "
            f"one to the '{SUBAGENT}' subagent using the Agent tool.\n"
            f"You MUST pass subagent_type='{SUBAGENT}' on every Agent call. "
            "Never use subagent_type='general-purpose' - it has no web access "
            "and will refuse.\n"
            "Always pass run_in_background=false so you receive the findings "
            "themselves rather than a launch receipt.\n"
            "You cannot search the web yourself; delegation is your only route to "
            "sources. If a subagent returns nothing usable, delegate again with a "
            "sharper question rather than answering from memory.\n"
            "Synthesize their reports into a report where every claim carries a "
            "source URL. Never cite a URL that a subagent did not actually return."
        ),
        model=MODEL,
        agents={SUBAGENT: search_agent},
        # `tools` = which tools EXIST, and it is SESSION-wide, not
        # coordinator-only. WebSearch/WebFetch must stay listed here or the
        # subagent cannot have them either and will refuse the task.
        tools=["Agent", "WebSearch", "WebFetch"],
        # `allowed_tools` = which calls auto-approve. Also session-level, so the
        # subagent's WebSearch/WebFetch belong here too.
        allowed_tools=["Agent", "WebSearch", "WebFetch"],
        # Close every OTHER escape hatch. WebSearch/WebFetch cannot go here -
        # disallowed_tools is session-wide and would gag the subagent too, so
        # the coordinator's "delegate, don't search" rule is prompt-enforced.
        disallowed_tools=["Bash", "Write", "Edit", "Read", "Glob", "Grep"],
        # Keep the user's MCP servers (playwright, etc.) out of the run, or the
        # coordinator will reach for a browser instead of delegating.
        mcp_servers={},
        strict_mcp_config=True,
        max_budget_usd=1.00,
        env={
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "5",
        },
    )

    rule("SETUP")
    log(f"  model            : {MODEL}")
    log(f"  coordinator tools: {options.tools}")
    log(f"  auto-approved    : {options.allowed_tools}")
    log(f"  subagents        : {list(options.agents)}")
    log(f"  subagent tools   : {search_agent.tools}")
    log(f"  budget cap       : ${options.max_budget_usd}")
    log(f"  question         : {preview(question)}")

    delegations = 0
    subagent_tool_calls = 0
    subagent_chars = 0   # traffic that stayed INSIDE the subagent
    report_chars = 0     # traffic that crossed BACK to the coordinator
    result_message = None

    rule("TRACE")
    try:
        async for message in query(prompt=question, options=options):
            # A truthy parent_tool_use_id means this happened INSIDE a subagent.
            parent = getattr(message, "parent_tool_use_id", None)
            pad = "      " if parent else "  "

            if isinstance(message, SystemMessage):
                if message.subtype == "init":
                    log(f"  [init] session={message.data.get('session_id')}")
                elif message.subtype == "permission_denied":
                    log(f"{pad}[!] DENIED {message.data.get('tool_name')}")
                continue

            if isinstance(message, ResultMessage):
                result_message = message
                continue

            for block in blocks_of(message):
                if isinstance(block, ToolUseBlock):
                    if block.name in DELEGATION_TOOLS:
                        delegations += 1
                        sub = block.input.get("subagent_type")
                        task = block.input.get("prompt", "")
                        log(f"{pad}DELEGATE -> {sub}")
                        log(f"{pad}            task: {preview(task, 120)}")
                    else:
                        if parent:
                            subagent_tool_calls += 1
                        log(f"{pad}[tool] {block.name} {preview(block.input, 70)}")

                elif isinstance(block, ToolResultBlock):
                    size = len(str(block.content or ""))
                    if parent:
                        # search traffic - never enters the coordinator's context
                        subagent_chars += size
                        log(f"{pad}[result] {size} chars (stays in subagent)")
                    else:
                        report_chars += size
                        log(f"{pad}REPORT <- {size} chars"
                            f"{' [ERROR]' if block.is_error else ''}")
                        log(f"{pad}            {preview(block.content, 120)}")

                elif isinstance(block, TextBlock):
                    who = "subagent" if parent else "coordinator"
                    log(f"{pad}[{who}] {preview(block.text, 120)}")

                elif isinstance(block, ThinkingBlock):
                    log(f"{pad}[thinking] {preview(block.thinking, 70)}")

    except Exception as exc:
        # query() raises AFTER yielding its error result, so the totals below
        # are still worth printing.
        log(f"\n  [!] query raised: {type(exc).__name__}: {exc}")

    rule("DONE")
    log(f"  delegations            : {delegations}")
    log(f"  tool calls in subagents: {subagent_tool_calls}")
    log(f"  chars kept in subagents: {subagent_chars}")
    log(f"  chars crossing back    : {report_chars}")
    if subagent_chars and report_chars:
        log(f"  context saved          : {1 - report_chars / subagent_chars:.1%}")
    if result_message:
        log(f"  subtype                : {result_message.subtype}")
        log(f"  num_turns              : {result_message.num_turns}")
        log(f"  duration_ms            : {result_message.duration_ms}")
        log(f"  total_cost_usd         : {result_message.total_cost_usd}")

    if delegations == 0:
        log("\n  [!] ZERO delegations - the coordinator answered from memory.")
    log()

    if result_message and result_message.result:
        print(result_message.result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
