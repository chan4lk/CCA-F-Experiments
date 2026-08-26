# Simple Agent Flow — coordinator + subagent with the Claude Agent SDK

A guide for finishing `coordinator.py` yourself. Everything here is verified against the installed
SDKs and the current docs (`code.claude.com/docs/en/agent-sdk/python` and `/subagents`).

---

## 1. First, why your stub can't run

```python
from anthropic import AgentDefinition   # ImportError
```

I checked the installed package: `anthropic` 1.0.0 exports no `AgentDefinition`. That name lives in
**`claude-agent-sdk`** — a *different product*. The two are easy to conflate:

| | `anthropic` (what `main.py`/`cache.py`/`agent-loop.py` use) | `claude-agent-sdk` (what your stub reaches for) |
|---|---|---|
| What it is | HTTPS client for `POST /v1/messages` | Claude Code packaged as a library |
| How it runs | direct API call from your process | spawns the `claude` CLI as a subprocess |
| Tools | only tools you define + server tools | built-in `Read`/`Bash`/`WebSearch`/`Agent`/… |
| The agent loop | you write it (`agent-loop.py`) | the SDK owns it |
| Subagents | you hand-roll them | first-class: `AgentDefinition` + the `Agent` tool |

You picked the Agent SDK, so the flow below is Claude Code's. Note the shape change this forces:
**`query()` is an async generator**, so `main()` becomes `async def` driven by `asyncio.run()`.
That's the one place this file will look unlike the rest of the repo.

### Three concrete bugs to fix

| In the stub | Problem | Fix |
|---|---|---|
| `from anthropic import AgentDefinition` | wrong package | `from claude_agent_sdk import ...` |
| `coodinator = AgentDefinition(prompt=..., allowed_tools=[...])` | **the coordinator is not an `AgentDefinition`** — and `AgentDefinition` has no `allowed_tools` field | the coordinator *is* `ClaudeAgentOptions` |
| `client.messages.create(...)` + `"{" + response.content[0].text` | leftover paste from `main.py`'s prefill demo | delete both |

Also: `soruces` → `sources`, `coodinator` → `coordinator`, `prodice` → `produce`.

---

## 2. Prerequisites — all already satisfied here

The Agent SDK shells out to the Claude Code CLI, so it needs more than a pip install:

- **Node** — v25.5.0 ✅
- **Claude Code CLI on `PATH`** — 2.1.246 at `/Users/chandima/.local/bin/claude` ✅
- **Python ≥ 3.10** — `.python-version` says 3.13 ✅
- **Auth** — `.env` has `ANTHROPIC_API_KEY`; `load_dotenv()` puts it in `os.environ`, and the Python
  SDK **merges** its `env` option into the inherited environment, so the CLI subprocess inherits the
  key. Keep `load_dotenv()` — it's load-bearing here, not decoration.

```bash
uv add claude-agent-sdk     # edits pyproject.toml + refreshes uv.lock
```

---

## 3. The mental model

Three pieces, and the delegation is *implicit* — you never call the subagent yourself:

```
ClaudeAgentOptions          ← the coordinator. system_prompt, model, which tools it may use.
  └── agents={...}          ← a dict of AgentDefinition. Each is a subagent Claude MAY spawn.
        └── "Agent" tool    ← how Claude spawns one. Must be in allowed_tools to auto-approve.
```

Claude decides *when* to delegate by reading each `AgentDefinition.description`. You don't write
dispatch logic — you write a good description and let the model route.

**Context isolation is the whole point.** A subagent starts with a fresh context window. It receives
only its own `prompt` plus the task string Claude wrote for it — *not* your conversation. It can burn
40k tokens searching and reading, and **only its final message returns to the coordinator** as the
`Agent` tool result. That's what makes delegation worth the round-trip.

---

## 4. Wiring the coordinator

```python
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

MODEL = "claude-haiku-4-5"

search_agent = AgentDefinition(
    description="Searches the web for primary sources. Give it ONE self-contained "
                "question; it returns findings with a source URL for every claim.",
    prompt="You are a research search agent. Search, read, and report concise "
           "findings. Every claim must carry the URL you got it from.",
    tools=["WebSearch", "WebFetch"],
    model=MODEL,
)

options = ClaudeAgentOptions(
    system_prompt="Goal: produce a cited report. Break the question into independent "
                  "sub-questions and delegate each one to the search-agent. You cannot "
                  "search yourself. Synthesize their reports into a report where every "
                  "claim carries a source URL.",
    model=MODEL,
    agents={"search-agent": search_agent},
    tools=["Agent"],                                   # ← see below
    allowed_tools=["Agent", "WebSearch", "WebFetch"],  # ← see below
)
```

**`tools` vs `allowed_tools`** — different jobs, and the distinction bites people:

- `tools=["Agent"]` — *which tools exist* for the coordinator. Giving it only `Agent` means it
  **physically cannot search** and must delegate. Your architecture is enforced, not merely requested.
- `allowed_tools=[...]` — *which tool calls auto-approve* without a permission prompt. This is
  session-level, so the subagent's `WebSearch`/`WebFetch` belong here too. Approval and availability
  are separate axes; `AgentDefinition.tools` is what scopes the subagent itself.

> `tools=` on `ClaudeAgentOptions` is the least-exercised knob in this config. If it misbehaves,
> `disallowed_tools=["WebSearch", "WebFetch", "Bash", "Write", "Edit"]` reaches the same end.

**Leave `setting_sources` unset** (the default). It keeps `.claude/settings.local.json` and any
`CLAUDE.md` out of the run, so the demo stays self-contained and reproducible.

### `AgentDefinition` fields

`description` and `prompt` are required; everything else is optional. Watch the casing:

```python
description, prompt, tools, model, skills          # snake / plain
disallowedTools, mcpServers, initialPrompt,        # ← camelCase, deliberately:
maxTurns, background, effort, permissionMode       #   these match the wire format
```

`model` takes an alias (`"haiku"`, `"sonnet"`, `"opus"`, `"inherit"`) **or** a full ID like
`"claude-haiku-4-5"`. Use the full ID to stay consistent with the rest of the repo.

---

## 5. ⚠️ The tool is `Agent`, not `Task`

It was renamed in Claude Code v2.1.63. Current SDKs emit `"Agent"` in `tool_use` blocks, but still
say `"Task"` in the `system:init` tool list and in `permission_denials[].tool_name`.

- **Put `"Agent"` in `allowed_tools`.**
- **When detecting delegations, match both:** `block.name in ("Task", "Agent")`.

---

## 6. Reading the stream

```python
async for message in query(prompt=question, options=options):
    ...
```

Message types (import from `claude_agent_sdk`): `SystemMessage`, `AssistantMessage`, `UserMessage`,
`ResultMessage`. Blocks: `TextBlock`, `ToolUseBlock`, `ToolResultBlock`, `ThinkingBlock`.

What to match on, to build a trace in `agent-loop.py`'s style:

| Match | Meaning in the trace |
|---|---|
| `SystemMessage` | session init |
| `AssistantMessage` → `ToolUseBlock` with `name in ("Task","Agent")` | **DELEGATE →** read `block.input["subagent_type"]` and `["prompt"]` |
| any message with a truthy `parent_tool_use_id` | this happened **inside** the subagent — indent it |
| `UserMessage` → `ToolResultBlock` for that call | **REPORT ←** the only thing crossing back; log its size |
| `AssistantMessage` → `TextBlock`, no parent | the coordinator's own reasoning / final report |
| `ResultMessage` | `subtype`, `num_turns`, `duration_ms`, `total_cost_usd`, `usage`, `result` |

`parent_tool_use_id` is the flag that makes context isolation *visible* — it's how you show that the
search traffic never entered the coordinator's context. Put that contrast in your closing summary;
it's the lesson.

Two defensive notes: read blocks as `getattr(message, "content", None) or []` and be ready for
`content` to arrive as a plain `str`; and **wrap the loop in `try/except`** — a single-shot `query()`
*raises after yielding its error result*, so your totals are already printed by the time the handler
runs.

Reuse `log()` / `rule()` / `preview()` from `agent-loop.py` by copying them — that file's hyphen makes
it non-importable, and every file in this repo is deliberately standalone. Then `LOG=0` gives you just
`result_message.result`, the cited report.

---

## 7. Safety rails

Once `Agent` is allowed, Claude decides how many subagents to spawn, and subagents can spawn their
own. One prompt can become a tree.

```python
env={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",   # search-agent can't spawn its own
     "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "5"},
max_budget_usd=1.00,   # compared against total_cost_usd; subagent calls count
```

At the cap you get result subtype `error_max_budget_usd`. Unlike the TypeScript SDK, Python **merges**
`env` into the inherited environment — you don't need to spread the existing env to keep `PATH`.

---

## 8. Gotchas, collected

1. `AgentDefinition` is `claude_agent_sdk`, never `anthropic`.
2. The coordinator is `ClaudeAgentOptions`, not an `AgentDefinition`.
3. `Agent`, not `Task` — but match both when detecting.
4. `query()` is async → `asyncio.run(main())`.
5. `AgentDefinition` uses camelCase for multi-word fields; `ClaudeAgentOptions` uses snake_case.
6. Subagents inherit **no** parent conversation — everything they need must be in the task string
   Claude writes for them. Your `description` is what teaches Claude to write a good one.
7. `tools` (availability) ≠ `allowed_tools` (approval).
8. `query()` raises *after* yielding the error result.
9. Needs Node + the `claude` CLI — this file has a real external dependency the others don't.

---

## 9. Verify it works

```bash
uv run coordinator.py "What are the compliance deadlines in the EU AI Act for 2026?"
```

1. At least one `DELEGATE →` naming `search-agent`. **Zero delegations is the most common failure** —
   the coordinator just answered from memory. Fixes, in order: name it in the prompt ("Use the
   search-agent to…"), sharpen the `description`, confirm `"Agent"` is in `allowed_tools`.
2. Indented `WebSearch`/`WebFetch` calls carrying a `parent_tool_use_id`.
3. A `REPORT ←` whose size is far smaller than the search traffic above it — the isolation payoff.
4. `ResultMessage` `subtype: success`, non-zero `total_cost_usd`.
5. The printed report actually carries URLs.

```bash
LOG=0 uv run coordinator.py "..."     # report only
```

Optional: set `max_budget_usd=0.001` and confirm you get `error_max_budget_usd` — proves the cap binds.

---

## 10. If you'd rather not take the dependency

Worth knowing, since it changes nothing else in the repo: you can build the same orchestrator-worker
flow on the plain `anthropic` SDK you already have. The coordinator runs the loop you wrote in
`agent-loop.py`, with one custom tool — `delegate_research(question)` — whose Python implementation is
a nested `client.messages.create()` carrying the server-side `web_search_20260209` /
`web_fetch_20260209` tools. Context isolation falls out for free: the nested call's search results
live in a separate `messages` array the coordinator never sees.

No new dependency, no subprocess, no beta API — and the delegation boundary is a function call you can
put a breakpoint on. Say the word if you want that version written up too.
