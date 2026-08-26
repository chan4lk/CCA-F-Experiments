import asyncio
from dotenv import load_dotenv
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query, HookMatcher, ClaudeSDKClient
from transcript import setup_session, TranscriptWriter
from subagent_tracker import SubagentTracker
from message_handler import process_assistant_message

load_dotenv()

async def main():
    MODEL = "claude-haiku-4-5"

    transcript_file, session_dir = setup_session()

    transcript = TranscriptWriter(transcript_file)

    tracker = SubagentTracker(transcript_writer=transcript, session_dir=session_dir)

    search_agent = AgentDefinition(
        description="Searches the web for primary sources. Give it ONE self-containeed question." +
        "it returns findings with a source URL for every claim.",
        prompt="You are a research search agent. Search, read, and report concise findings. "+
        "Every claim must carry the URL you got it from.",
        tools=["WebSearch", "WebFetch"],
        model=MODEL
    )

    hooks = {
        "PreToolUse": [
            HookMatcher(
                matcher=None,
                hooks=[tracker.pre_tool_use_hook]
            )
        ],
        "PostToolUse": [
            HookMatcher(
                matcher=None,
                hooks=[tracker.post_tool_use_hook]
            )
        ]
    }

    options = ClaudeAgentOptions(
        system_prompt="Goal: prodice a cited report. Break the question into independent sub-questions "
        "and deletegate each one to the search-agent"
        "You cannot search yourself. Synthesize their reports into a report where every claim carries a source URL.",
        allowed_tools=["Agent", "WebSearch", "WebFetch"],
        agents={"search-agent": search_agent},
        # SESSION-wide, not coordinator-only: WebSearch/WebFetch must be listed
        # here or search-agent cannot have them either and the coordinator
        # ends up doing the searching itself.
        tools=["Agent", "WebSearch", "WebFetch"],
        model=MODEL,
        max_budget_usd=1.0,
        mcp_servers={},
        env={
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENT": "5"
        },
        hooks=hooks
    )

    try:
        async with ClaudeSDKClient(options=options) as client:
            while True:
                try:
                    question = input("Enter your question: ")
                except (EOFError, KeyboardInterrupt):
                    break

                if not question or question.lower() in ["exit", "quit", "q"]:
                    break

                transcript.write(f"User: {question}\n")

                await client.query(prompt=question)

                transcript.write("Assistant: \n", end="")

                async for msg in client.receive_response():
                    if type(msg).__name__ == 'AssistantMessage':
                        process_assistant_message(msg, tracker, transcript)

                # TODO: Call the agent here with the question
                

    except Exception as e:
        print(f"Error: {e}")
    finally:
        transcript.write("\n\nSession ended.\n")
        transcript.close()
        tracker.close()

        print(f"Session ended. Transcript saved to {session_dir}")
        print(f" - Transcript: {transcript_file}")
        print(f" - Tool calls: {session_dir / 'tool_calls.jsonl'}")

if __name__ == "__main__":
    asyncio.run(main())
