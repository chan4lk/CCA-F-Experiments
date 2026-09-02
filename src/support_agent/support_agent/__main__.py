import asyncio
import sys

import agent
from case import Case
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from hooks import bare


async def main(message: str) -> int:
    case = Case()
    async for event in agent.run(message, case):
        if isinstance(event, AssistantMessage):
            for block in event.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    print(f"  [tool] {bare(block.name)} {block.input}", file=sys.stderr)
        elif isinstance(event, ResultMessage):
            print(f"\n  cost ${event.total_cost_usd or 0:.4f}", file=sys.stderr)

    print("\n" + case.block(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('usage: python -m support_agent "<customer message>"', file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(sys.argv[1])))
