# CCAF — a study repo for **Claude Certified Architect · Foundations** (CCAR-F)

Every one of the six scenarios on the CCAR-F exam, built as running, tested code.
**1,939 tests. No slideware.**

The exam is scenario-based. It does not ask you to recite what a `PreToolUse` hook is —
it asks whether you would reach for a hook or a prompt when a refund must never exceed
$500. You answer that question well only if you have written both and watched one of them
fail. That is what this repo is: the six exam scenarios, implemented, so that every task
statement in the guide has something here you can run and read.

I passed CCAR-F. This README is the path I took, compressed into four weeks, plus the code
that made the abstractions concrete.

— [Chandima Ranaweera](mailto:chandima@bistecglobal.com)

---

## 1. The exam at a glance

| | |
|---|---|
| **Credential** | Claude Certified Architect – Foundations |
| **Exam code** | CCAR-F (v1.0, effective July 2026) |
| **Items** | 60, multiple-choice and multiple-response — each item states how many to select |
| **Structure** | 4 scenarios drawn at random from a bank of 6 |
| **Time** | 120 minutes |
| **Pass mark** | **720** on a scaled 100–1,000 |
| **Fee** | $125 USD |
| **Delivery** | Proctored — online or Pearson VUE test centre |
| **Valid for** | 12 months (free non-proctored renewal if you do it on time) |

Download the current exam guide from Anthropic and **read it end to end.** It is the
authoritative source, it is unusually specific — §17 lists the in-scope and out-of-scope
topics almost item by item — and it is explicitly *subject to change without notice*, so
get a fresh copy rather than a shared one. Keep it at `docs/` locally; it is not committed
here.

### Domain weights

| # | Domain | Weight |
|---|---|---|
| 1 | Agentic Architecture & Orchestration | **27%** |
| 2 | Tool Design & MCP Integration | 18% |
| 3 | Claude Code Configuration & Workflows | 20% |
| 4 | Prompt Engineering & Structured Output | 20% |
| 5 | Context Management & Reliability | 15% |

Domain 1 is more than a quarter of the exam. If you are short on time, spend it on the
agentic loop, coordinator/subagent orchestration, hooks, and session state.

---

## 2. Start here — the path

Nine steps, in the order I did them. Steps 1 and 2 are not optional and not reorderable.

### 1. Register first

Book the slot before you study. A date on the calendar is the only thing that reliably
converts intent into a pass. Scheduling, rescheduling and accommodations all go through
[Pearson VUE](https://www.pearsonvue.com/us/en/anthropic.html); name corrections go to
`certifications-support@anthropic.com`.

### 2. Write the primitives yourself

Before reading anything, write the boring code. Not from a tutorial — from the API
reference, badly, until it runs. The root of this repo is exactly that:

| File | The one thing it isolates |
|---|---|
| [`main.py`](main.py) | A single `POST /v1/messages` call |
| [`prefil.py`](prefil.py) | Assistant **prefill** — steering output by starting the reply for Claude |
| [`cache.py`](cache.py) | **Prompt caching** and the cache-read/cache-write token counters |
| [`batch.py`](batch.py) | **Message Batches API** — `custom_id`, submit, poll, correlate |
| [`agent-loop.py`](agent-loop.py) | The **agentic loop** by hand: `stop_reason == "tool_use"` → execute → append result → repeat |
| [`coordinator.py`](coordinator.py) | The same loop given away — coordinator + subagent on the **Claude Agent SDK** |

`agent-loop.py` is the important one. Domain 1.1 asks you to distinguish looping on
`stop_reason` from the anti-patterns — parsing natural language for "I'm done", capping
iterations as the primary stop, checking whether assistant text exists. Write the loop by
hand once and those distractors stop being plausible.

Then read [`AGENT_FLOW.md`](AGENT_FLOW.md), which is the walkthrough for `coordinator.py`
and collects the traps — §5 on `Agent` vs `Task`, §8 on snake_case vs camelCase.

```bash
uv sync
uv run main.py
uv run agent-loop.py
uv run coordinator.py "What changed in the EU AI Act for 2026?"
```

### 3. Read the official guide, then build the scenarios

Read the PDF end to end. Then have Claude implement all six scenarios **and read every
line of the generated code.** Reading the code is the step that does the work; generating
it is not. When Claude writes a `PostToolUse` hook that normalises Unix timestamps to ISO
8601, you learn more from asking *why not just tell the model the format?* than from any
number of practice questions.

That work is already done here — see [§3, the six scenarios](#3-the-six-scenarios--the-code-that-implements-them).
Clone it, read it, then delete a piece and rebuild it yourself.

### 4. `code.claude.com/docs/en/agents` — end to end

[Agents docs](https://code.claude.com/docs/en/agents). Subagents, `AgentDefinition`,
context isolation, tool restrictions. Covers most of Domain 1.2 and 1.3.

### 5. `code.claude.com/docs/en/agent-sdk/overview` — end to end

[Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview). Hooks, sessions,
MCP wiring, permissions. Domains 1.5, 1.7, 2.4.

### 6. Six full practice exams

[Udemy — Anthropic Claude Certified Architect, 3 full practice exams](https://www.udemy.com/course/anthropic-claude-certified-architect-3-full-practice-exams).
Do all of them. Not for the score — for the **explanations**. Read the rationale on every
question you got right too; several of mine were right for the wrong reason.

### 7. The foundations course video

[youtube.com/watch?v=O94JiAuQ9zY](https://www.youtube.com/watch?v=O94JiAuQ9zY) — not on
the official path, but genuinely good on the mental models.

### 8. Coverage sweep

[youtube.com/watch?v=reDRM0tqhNs](https://www.youtube.com/watch?v=reDRM0tqhNs) — dull, but
it touches everything. Play it at 1.5× as a checklist: anything that sounds unfamiliar is a
gap, go fix it.

### 9. Read the cookbook, then sit the exam

[anthropic/claude-cookbooks — `claude_agent_sdk/research_agent`](https://github.com/anthropics/claude-cookbooks/tree/main/claude_agent_sdk/research_agent).
The canonical shape of Scenario 3. Compare it to the four implementations in this repo and
notice what each one trades away.

Then sit it.

---

## 3. The six scenarios → the code that implements them

This is what this repo is for. Each exam scenario has working code here.

| # | Exam scenario | Primary domains | Implemented in | Tests |
|---|---|---|---|---|
| 1 | Customer Support Resolution Agent | 1, 2, 5 | [`src/support_agent/`](src/support_agent/) | 53 |
| 2 | Code Generation with Claude Code | 3, 5 | [`.claude/`](.claude/) + [`docs/claude-code-workflows.md`](docs/claude-code-workflows.md) | config |
| 3 | Multi-Agent Research System | 1, 2, 5 | **four separate ports** — see [§4](#4-one-pipeline-four-engines) | 1,743 |
| 4 | Developer Productivity with Claude | 2, 3, 1 | [`src/code_explorer/`](src/code_explorer/) | 45 |
| 5 | Claude Code for Continuous Integration | 3, 4 | [`src/ci_review/`](src/ci_review/) + [`.github/workflows/`](.github/workflows/) | 53 |
| 6 | Structured Data Extraction | 4, 5 | [`src/extraction/`](src/extraction/) | 45 |

[`docs/backlog/2026-09-02-ccar-f-scenarios.md`](docs/backlog/2026-09-02-ccar-f-scenarios.md)
maps each build back to the individual task statements it exercises — 1.4, 2.2, 4.3 and so
on. **Read that file next.** It is the index from exam objective to line of code.

A few things in there worth going to directly, because they are the ones the exam probes
and the ones a tutorial will not show you:

- **`src/support_agent/`** — a `PreToolUse` hook that blocks `process_refund` until
  `get_customer` has returned a verified id. The tests assert the *call was denied*, not
  that the model chose not to make it. That distinction is Domain 1.4 and 1.5 in one line.
- **`src/extraction/`** — nullable optional fields so absent data is not fabricated,
  `"other"` + detail string, `"unclear"` for ambiguity, and retry-with-error-feedback that
  classifies *absent information* as non-retryable. Domain 4.3 and 4.4.
- **`src/ci_review/`** — `claude -p` with `--output-format json` and `--json-schema`, prior
  findings passed in context so a re-run only reports what is new. Domain 3.6.
- **`.claude/rules/`** — path-scoped rules with `paths:` glob frontmatter, so a test
  convention loads only when you edit `**/test_*.py`. Domain 3.1 and 3.3.

### Known caveats, stated plainly

Every suite passes offline against injected fakes. **Nothing here has been exercised
against the live API** — the workspace key used to build it is rate-limited to 0 req/min.
So: the logic is tested, the wire calls are not. The `paths:` frontmatter key in
`.claude/rules/` is written as the exam guide documents it and has not been confirmed
against the shipping CLI; if the key is wrong the rule still loads, just unconditionally.
Both are noted in the backlog doc too. Trust the tests; verify the live behaviour yourself.

---

## 4. One pipeline, four engines

Scenario 3 — the multi-agent research system — is implemented **four times** on four
execution engines. Same design, same blocking verification gate, four completely different
substrates. Comparing them is the point.

| Directory | Engine | Who owns the agent loop | Tools |
|---|---|---|---|
| [`plugins/proposal-research/`](plugins/proposal-research/) | Claude Code plugin (markdown agents + hooks) | a model orchestrates | the harness's |
| [`research-agent/`](research-agent/) | Claude Agent SDK | the SDK provides it | built-ins + in-process MCP |
| [`research_agent_batch/`](research_agent_batch/) | Message Batches API | rebuilt — one batch per round | written and executed locally |
| [`research_agent_batch_server_tools/`](research_agent_batch_server_tools/) | Message Batches API | none needed | Anthropic-hosted `web_search` / `web_fetch` |

Each README opens with the trade it makes. The short version:

- Moving the orchestrator **from a model to a Python function** turns rules into
  properties. Its context cost becomes structurally zero, and a validator *cannot* be
  handed the quote it is checking, because its prompt is built from three fields and the
  quote is not one of them.
- Moving to **batches** halves token cost and survives a closed laptop.
- Moving the tools **server-side** deletes the loop rather than rebuilding it.

All four enforce the same invariants — quotes verbatim, validators blind and on a
different model, a gate that *raises* rather than advises, and no rendered vault for a
failed pack. If you want to understand Domain 1 properly, read the same gate in all four
places and watch what changes.

> The vendored files (`ledger/`, `gate/verify.py`, `vault/build.py`, `ingest.py`) are
> **copies**, not shared code. A fix in one is not a fix in the others.

---

## 5. Four-week schedule — sit it by Wednesday 30 September 2026

Roughly 6–8 hours a week. **Register by Wednesday 10 September** — Pearson VUE slots fill,
and an unbooked exam is an exam you sit in November.

| Week | Dates | Do this | Steps |
|---|---|---|---|
| **0** | by Thu 10 Sep | **Book the exam.** Then `uv sync` and run the six root demos. | 1–2 |
| **1** | 8–14 Sep | Guide PDF end to end. `agent-loop.py` by hand. `AGENT_FLOW.md`. Domain 1. | 2–3 |
| **2** | 15–21 Sep | Agents + Agent SDK docs. Read `src/support_agent/` and `src/code_explorer/`. Domains 1, 2. | 4–5 |
| **3** | 22–26 Sep | Read `src/extraction/`, `src/ci_review/`, `.claude/`. Practice exams 1–3. Domains 3, 4. | 6 |
| **4** | 27–29 Sep | Practice exams 4–6. The two videos at 1.5×. Cookbook. Re-read the guide's §17 scope lists. | 7–9 |
| — | **Wed 30 Sep** | **Sit the exam.** | |

Weak-spot rule: after each practice exam, map every wrong answer to its domain number,
then open the code in this repo for that domain and read it. Do not re-read the docs.

---

## 6. What else is in here

Two kinds of thing live here and **they do not share code**.

**Root-level demos** — `main.py`, `prefil.py`, `cache.py`, `batch.py`, `agent-loop.py`,
`coordinator.py`, plus `transcript.py` / `message_handler.py` / `subagent_tracker.py`
supporting the coordinator. Each isolates one API feature. Deliberately standalone.

**Agent projects** under [`src/`](src/) — `extraction/`, `ci_review/`, `support_agent/`,
`code_explorer/`. Each is self-contained with its own `pytest.ini`, `conftest.py` and
README.

### The two SDKs — do not conflate them

Half the exam's distractors live in this gap.

| | `anthropic` | `claude-agent-sdk` |
|---|---|---|
| What it is | HTTPS client for `POST /v1/messages` | Claude Code packaged as a library |
| How it runs | direct API call, in-process | spawns the `claude` CLI as a subprocess |
| Tools | only what you define, plus server tools | built-in `Read`/`Bash`/`WebSearch`/`Agent`/… |
| The agent loop | **you write it** | **the SDK owns it** |
| Subagents | hand-rolled | `AgentDefinition` + the `Agent` tool |
| External deps | none | Node and the `claude` CLI on `PATH` |

`AgentDefinition` and `ClaudeAgentOptions` live in `claude_agent_sdk`, **never** in
`anthropic`.

### Two naming traps that are still live in the code

1. The subagent tool was renamed `Task` → `Agent` in Claude Code v2.1.63. Put `"Agent"` in
   `allowed_tools` — but **match both** when detecting delegations, because `system:init`
   and `permission_denials[].tool_name` still say `Task`. The exam guide's appendix still
   says `Task`.
2. `ClaudeAgentOptions` uses **snake_case**; `AgentDefinition` uses **camelCase** for its
   multi-word fields (`disallowedTools`, `mcpServers`, `maxTurns`, `permissionMode`),
   because those match the wire format.

And one that is not a naming trap but bites just as hard: `load_dotenv()` is load-bearing.
It puts `ANTHROPIC_API_KEY` into `os.environ`, and the SDK merges its `env` option into the
inherited environment — which is how the CLI subprocess gets the key at all.

---

## 7. Setup and running things

Python 3.13, managed by [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/chan4lk/CCA-F-Experiments.git && cd CCA-F-Experiments
uv sync
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env    # gitignored
```

The Agent SDK paths additionally need Node and the `claude` CLI on `PATH`.

### Tests

Nothing is pip-installed; each `conftest.py` puts its own directory on `sys.path`. So
**run each suite from its own directory**:

```bash
cd src/extraction               && uv run --project ../.. pytest    #  45
cd src/ci_review                && uv run --project ../.. pytest    #  53
cd src/support_agent            && uv run --project ../.. pytest    #  53
cd src/code_explorer            && uv run --project ../.. pytest    #  45

cd research-agent                        && uv run --project .. pytest   # 421
cd research_agent_batch                  && uv run --project .. pytest   # 480
cd research_agent_batch_server_tools     && uv run --project .. pytest   # 476

uv run pytest plugins/proposal-research/tests/                           # 366 (from repo root)
```

Or just `/check` inside Claude Code, which runs all of them plus the linter.

`asyncio_mode = strict`, so async tests need an explicit `@pytest.mark.asyncio`.
`filterwarnings = error::DeprecationWarning`, so a new deprecation warning fails the suite.

### Running the pipelines

```bash
# Agent SDK — synchronous; needs Node + the claude CLI
cd research-agent
python -m research_agent "Can Copilot Studio host our claims-triage assistant?" \
  --client "Northwind Mutual" --audience "technical buyer" \
  --constraints "no new licences; must run in the existing tenant"
python -m research_agent draft --workspace research/<slug>   # after you read the pack

# Batches — submit, exit, resume. Survives a closed laptop via batch-state.json
cd research_agent_batch
python -m research_agent_batch "<question>" --client "..." --audience "..."
python -m research_agent_batch status
python -m research_agent_batch resume [--wait]
```

---

## 8. Reading order, if you only have an afternoon

1. [`docs/backlog/2026-09-02-ccar-f-scenarios.md`](docs/backlog/2026-09-02-ccar-f-scenarios.md) — objectives → code
2. [`AGENT_FLOW.md`](AGENT_FLOW.md) — the coordinator walkthrough and the traps
3. [`agent-loop.py`](agent-loop.py) — the loop, by hand
4. [`src/support_agent/`](src/support_agent/) — hooks as enforcement, not advice
5. [`research-agent/README.md`](research-agent/README.md) — then the other three, for the contrast
6. [`CLAUDE.md`](CLAUDE.md) — how this repo is meant to be worked on

---

## Contributing

Commits: `type(scope): lowercase subject`. Work on `feat/<name>` branches, merged via PR.
New Python goes under `src/`, never the repo root — see
[`.claude/rules/repository-layout.md`](.claude/rules/repository-layout.md).

Found a gap between this code and what the exam actually asked you? Open a PR. That is the
most useful thing you can do for the next person sitting it.

**Good luck. Book the slot first.**
