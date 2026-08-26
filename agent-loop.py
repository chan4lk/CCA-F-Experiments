import anthropic
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# --------------------------------------------------------------------- log ---
# Everything below is instrumentation only - it does not change the loop.
# Run with LOG=0 to silence the trace:  LOG=0 uv run agent-loop.py

LOG = os.environ.get("LOG", "1") != "0"


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


def block_type(block):
    """Content blocks are SDK objects when they come FROM the API,
    and plain dicts when we build them ourselves. Handle both."""
    return block["type"] if isinstance(block, dict) else block.type


def describe_messages(messages):
    """Show the conversation array we are about to send.

    This is the thing worth watching: the API is stateless, so every turn
    re-sends the ENTIRE history. This list only ever grows.
    """
    lines = []
    for i, msg in enumerate(messages):
        content = msg["content"]
        if isinstance(content, str):
            shape = f"str -> {preview(content, 50)}"
        else:
            types = ", ".join(block_type(b) for b in content)
            shape = f"{len(content)} block(s) -> [{types}]"
        lines.append(f"    [{i}] {msg['role']:<9} {shape}")
    return "\n".join(lines)


# -------------------------------------------------------------------- tool ---

def get_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_books_browwed(date):
    return f"Books borrowed on {date} are Harry potter"


def run_tool(name, input):
    log(f"  [tool] dispatching name={name!r} input={input!r}")
    if name == "get_time":
        result = get_time()
    elif name == "get_books_browwed":
        result = get_books_browwed(input["date"])
    else:
        result = "Unknown tool"
    log(f"  [tool] returned {result!r}")
    return result


def main():
    client = anthropic.Anthropic()
    user_input = input("Enter your message: ")
    tools = [
        {
            "name": "get_time",
            "description": "Get the current time",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "get_books_browwed",
            "description": "Get the books borrowed on a specific date",
            "input_schema": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check"
                    }
                },
                "required": ["date"]
            }
        }
    ]
    messages = [
        {
            "role": "user",
            "content": user_input
        }
    ]

    rule("SETUP")
    log(f"  model          : claude-haiku-4-5")
    log(f"  tools declared : {[t['name'] for t in tools]}")
    log(f"  first message  : {preview(user_input)}")

    turn = 0
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    while True:
        turn += 1

        # ---- what we SEND -------------------------------------------------
        rule(f"TURN {turn}  >>>  REQUEST")
        log(f"  sending {len(messages)} message(s):")
        log(describe_messages(messages))

        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1024,
            system="You are a helpful assistant.",
            tools=tools,
            messages=messages
        )

        # ---- what we GET BACK ---------------------------------------------
        u = response.usage
        totals["input"] += u.input_tokens
        totals["output"] += u.output_tokens
        totals["cache_read"] += u.cache_read_input_tokens or 0
        totals["cache_write"] += u.cache_creation_input_tokens or 0

        rule(f"TURN {turn}  <<<  RESPONSE")
        log(f"  stop_reason : {response.stop_reason}")
        log(f"  usage       : in={u.input_tokens} out={u.output_tokens} "
            f"cache_read={u.cache_read_input_tokens or 0} "
            f"cache_write={u.cache_creation_input_tokens or 0}")
        log(f"  content     : {len(response.content)} block(s)")
        for i, block in enumerate(response.content):
            if block.type == "text":
                log(f"    [{i}] text     : {preview(block.text)}")
            elif block.type == "tool_use":
                log(f"    [{i}] tool_use : name={block.name} "
                    f"id={block.id} input={block.input!r}")
            else:
                log(f"    [{i}] {block.type}")

        # ---- the exit condition -------------------------------------------
        if response.stop_reason == "end_turn":
            log("\n  -> stop_reason is 'end_turn': Claude is done. BREAKING.")
            log("     NOTE: we break BEFORE appending this reply to `messages`,")
            log("     so the final answer never lands in the array.")
            break

        log(f"\n  -> stop_reason is {response.stop_reason!r}: not done, loop again.")

        messages.append({
            "role": "assistant",
            "content": response.content
        })
        log(f"  appended assistant turn -> messages is now {len(messages)} long")

        # ---- run the tools Claude asked for --------------------------------
        tool_results = []
        requested = [b for b in response.content if b.type == "tool_use"]
        log(f"\n  executing {len(requested)} tool call(s):")
        for block in response.content:
            if block.type == "tool_use":
                result = run_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        messages.append({
            "role": "user",
            "content": tool_results
        })
        log(f"\n  appended {len(tool_results)} tool_result(s) as a 'user' turn "
            f"-> messages is now {len(messages)} long")

    rule("DONE")
    log(f"  turns taken        : {turn}")
    log(f"  messages in array  : {len(messages)}")
    log(f"  cumulative tokens  : in={totals['input']} out={totals['output']} "
        f"cache_read={totals['cache_read']} cache_write={totals['cache_write']}")
    log(f"  about to print messages[-1] -> role={messages[-1]['role']!r}")
    log()

    print(messages[-1]['content'])


if __name__ == "__main__":
    main()
