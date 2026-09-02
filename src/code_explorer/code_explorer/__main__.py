import asyncio
import sys

import explorer
import mcp_config
import session as sessions
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from scratchpad import Scratchpad


async def explore(goal: str, changed: list[str]) -> int:
    for name in mcp_config.missing_credentials():
        print(f"  [mcp] {name} is unset — that server's tools will be missing", file=sys.stderr)

    async for plan, event in explorer.run(goal, changed):
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    label = "delegate" if explorer.is_delegation(block.name) else block.name
                    print(f"  [{label}]", file=sys.stderr)
        elif isinstance(event, ResultMessage):
            print(f"\n  {plan.action} ({plan.reason}) · ${event.total_cost_usd or 0:.4f}", file=sys.stderr)
    return 0


def status() -> int:
    manifest = Scratchpad().load()
    if manifest is None:
        print("no investigation in this workspace")
        return 0
    print(f"goal     : {manifest.goal}")
    print(f"session  : {manifest.session_id} ({'stale' if manifest.stale() else 'fresh'})")
    print(f"phase    : {manifest.phase}")
    print(f"files    : {len(manifest.files_seen)} read")
    for question in manifest.open_questions:
        print(f"  open   : {question}")
    return 0


def fork(title: str) -> int:
    manifest = Scratchpad().load()
    if manifest is None or not manifest.session_id:
        print("nothing to fork from", file=sys.stderr)
        return 1
    print(sessions.branch(manifest.session_id, title))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print('usage: python -m code_explorer explore "<goal>" [changed files...] | status | fork <title>', file=sys.stderr)
        return 2

    command, rest = argv[0], argv[1:]
    if command == "status":
        return status()
    if command == "fork":
        return fork(rest[0] if rest else "branch")
    if command == "explore":
        return asyncio.run(explore(rest[0], rest[1:]))

    print(f"unknown command {command!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
