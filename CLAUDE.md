# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout rules

@.claude/rules/repository-layout.md

## What this repo is

CCAF is an experiments repo for building on Anthropic's two Python SDKs. It contains two
kinds of thing, and they do not share code:

1. **Root-level single-concept demos** (`main.py`, `prefil.py`, `cache.py`, `batch.py`,
   `agent-loop.py`, `coordinator.py`) — each one isolates a single API feature. They are
   deliberately standalone.
2. **One real multi-agent pipeline, `proposal-research`, implemented four times** on four
   different execution engines. Same design, same gate, four engines. Comparing them is the
   point of the repo.

`AGENT_FLOW.md` is the primary orientation doc for the demos; each pipeline directory has its
own README that opens with the trade it is making.

## The two SDKs — do not conflate them

| | `anthropic` | `claude-agent-sdk` |
|---|---|---|
| What it is | HTTPS client for `POST /v1/messages` | Claude Code packaged as a library |
| How it runs | direct API call in-process | spawns the `claude` CLI as a subprocess |
| Tools | only what you define + server tools | built-in `Read`/`Bash`/`WebSearch`/`Agent`/… |
| The agent loop | you write it | the SDK owns it |
| Subagents | hand-rolled | `AgentDefinition` + the `Agent` tool |

`AgentDefinition` / `ClaudeAgentOptions` live in `claude_agent_sdk`, **never** in `anthropic`.
The `claude_agent_sdk` path has a real external dependency the others don't: Node and the
`claude` CLI on `PATH`.

Two naming traps documented in `AGENT_FLOW.md` §5 and §8 and still live in the code:

- The subagent tool was renamed `Task` → `Agent` in Claude Code v2.1.63. Put `"Agent"` in
  `allowed_tools`, but **match both** when detecting delegations — `system:init` and
  `permission_denials[].tool_name` still say `Task`.
- `ClaudeAgentOptions` uses snake_case; `AgentDefinition` uses camelCase for its multi-word
  fields (`disallowedTools`, `mcpServers`, `maxTurns`, `permissionMode`) because those match
  the wire format.

`load_dotenv()` is load-bearing, not decoration: it puts `ANTHROPIC_API_KEY` from `.env` into
`os.environ`, and the Python SDK merges its `env` option into the inherited environment so the
CLI subprocess inherits the key.

## The four proposal-research implementations

All four research a proposal question, verify every claim against the page it came from, run a
blocking gate, and emit an evidence pack plus an Obsidian vault.

| Directory | Engine | The agent loop | Tools |
|---|---|---|---|
| `plugins/proposal-research/` | Claude Code plugin (markdown agents + hooks + scripts) | a model orchestrates | the harness's |
| `research-agent/` | Claude Agent SDK | the SDK provides it | the SDK's built-ins + in-process MCP |
| `research_agent_batch/` | Message Batches API | rebuilt: one batch per round | written and executed locally (`tools/`) |
| `research_agent_batch_server_tools/` | Message Batches API | none needed | Anthropic-hosted `web_search` / `web_fetch` |

The ports exist to make one architectural argument each, recorded in their READMEs: moving the
orchestrator from a model to a Python function turns rules into properties (its context cost
becomes structurally zero, and a validator cannot be handed the quote it is checking because
its prompt is built from three fields and the quote is not one of them); moving to batches
halves token cost and survives a closed laptop; moving the tools server-side deletes the loop
rather than rebuilding it.

### Invariants shared by all four

Preserve these when changing any implementation — most of the test suites exist to defend them:

- **Quotes are verbatim.** Researchers never paraphrase into the ledger.
- **Validators are blind.** A validator sees a claim id, a claim, and a URL — never the
  researcher's quote, never the ledger. Enforced by tool grant plus `validator_guard`, not by
  instruction. Every material claim gets a second validator **on a different model**.
- **The gate is a function that raises**, not advice. Eight checks: `citations-resolve`,
  `verdict-admission`, `fetch-provenance`, `validator-blindness`,
  `validator-tool-restrictions`, `uncited-prose`, `source-mix`, `claim-quote`.
- **The vault is built only after the gate passes** — a rendered vault is the artefact a
  reader trusts most, so one must never exist for a failed pack.
- **A human gate sits between the pack and the draft.** `draft` is a separate invocation.
- **Sessions load none of the developer's settings** (`setting_sources=[]`, `skills=[]`,
  `strict_mcp_config=True`). Without that the CLI loads your `CLAUDE.md` and installed
  plugins — including the `proposal-research` plugin itself, whose hooks would then fire
  alongside the run's own and double every fetch-log row.

### Vendored, not shared

`ledger/`, `gate/verify.py`, `vault/build.py` and `ingest.py` are **copies** in each of the
three Python packages, vendored from the plugin with import paths rewritten and behaviour
unchanged. Their test suites are ported copies too. A fix in one is not a fix in the others —
when changing shared-looking code, decide explicitly which of the four you are changing and
say so.

## Commands

```bash
uv sync                                   # install; Python 3.13, uv-managed

# root demos — each is standalone
uv run main.py
uv run agent-loop.py
uv run coordinator.py "What changed in the EU AI Act for 2026?"
LOG=0 uv run coordinator.py "..."         # LOG=0 silences the trace, prints the report only
```

Each pipeline has its own `pytest.ini` and `conftest.py` (the conftest puts the directory on
`sys.path` — nothing is pip-installed), so **tests run from the package directory**:

```bash
cd research-agent && pytest                          # 421 tests
cd research_agent_batch && pytest                    # 480 tests
cd research_agent_batch_server_tools && pytest       # 476 tests
pytest plugins/proposal-research/tests/ -v           # 366 tests, from the repo root

pytest tests/test_gate.py -v                         # one file
pytest tests/test_gate.py::test_fetch_provenance -v  # one test
pytest -k blindness                                  # by name
```

`asyncio_mode = strict` — async tests need an explicit `@pytest.mark.asyncio`.
`filterwarnings = error::DeprecationWarning` — a new deprecation warning fails the suite.

There is no committed lint or format config; ruff has been run ad hoc (`uvx ruff check .`).

### Running the pipelines

```bash
# Agent SDK — synchronous, needs Node + the claude CLI on PATH
cd research-agent
python -m research_agent "Can Copilot Studio host our claims-triage assistant?" \
  --client "Northwind Mutual" --audience "technical buyer" \
  --constraints "no new licences; must run in the existing tenant"
python -m research_agent draft --workspace research/<slug>    # after reading the pack

# Batches — submit, exit, resume. Survives a closed laptop via batch-state.json
cd research_agent_batch
python -m research_agent_batch "<question>" --client "..." --audience "..."
python -m research_agent_batch status
python -m research_agent_batch resume [--wait]
```

Both batch variants use the same `status` / `resume` verbs under their own module name.

Env vars beyond `ANTHROPIC_API_KEY`, all optional: `RESEARCH_AGENT_MODEL_<ROLE>` (and
`RESEARCH_BATCH_MODEL_*` / `RESEARCH_SERVER_MODEL_*`) to override a role's pinned model,
`RESEARCH_AGENT_BUDGET_USD` (default `$2.00`) to cap a single dispatch,
`RESEARCH_AGENT_MCP_CONFIG` to grant the optional `microsoft_docs_mcp` / `headroom` servers,
`RESEARCH_BATCH_SEARCH_PROVIDER` with `BRAVE_SEARCH_API_KEY` or `SERPER_API_KEY` (local-tools
variant only), and `RESEARCH_*_POLL_SECONDS`. Models are pinned to full ids in each
`settings.py`; a missing optional MCP server costs the tools, not the run.

## Conventions

- Commits: `type(scope): lowercase subject` — e.g. `feat(research-agent): …`,
  `docs(ledger-forensics): …`. Work happens on `feat/<name>` branches merged via PR.
- Design specs and plans live in `docs/superpowers/{specs,plans}/` as `YYYY-MM-DD-<slug>.md`.
  A design is written and reviewed before implementation starts.
- `research/`, `logs/`, `headroom_memory.db` and `.venv` are gitignored — `research/` is
  pipeline output (workspaces), `logs/` is coordinator session transcripts.
- The current branch `feat/ledger-forensics` carries a design spec only
  (`docs/superpowers/specs/2026-08-31-ledger-forensics-design.md`); no plugin code exists yet.
  Its central constraint: no personal data may enter a model context, enforced by database
  permissions first and hooks second — never by a prompt saying "do not read PII".
