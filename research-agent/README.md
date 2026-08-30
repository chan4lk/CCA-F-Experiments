# research-agent

The `proposal-research` Claude Code plugin, rebuilt as a Claude Agent SDK application.

It researches a product or solution proposal question across the web and produces three
things: a **cited evidence pack**, a **verification report** proving every cited page was
actually retrieved, and a self-contained **Obsidian vault**. Six agents do the work. A
blocking gate stands between the research and anything a client would read.

```bash
python -m research_agent "Can Copilot Studio host our claims-triage assistant?" \
  --client "Northwind Mutual" \
  --audience "technical buyer" \
  --constraints "no new licences; must run in the existing tenant"

# read the pack and the report, then:
python -m research_agent draft --workspace research/can-copilot-studio-host-our-claims-triage-assistant
```

---

## Why it was ported

The plugin worked, and its design was sound: quotes must be verbatim, validators must be
blind, nothing reaches the pack without two independent confirmations. But it asked a
**model** to enforce that design. The SKILL.md was 240 lines of instructions to an
orchestrator that could, at any point, skip a step.

Three costs followed from that, all measured in the plugin's own first real run:

| | In the plugin | Here |
|---|---|---|
| **The orchestrator's own context** | Grew 107K → 706K over 488 turns. Cache reads are turns × context: 172M tokens, **65% of the entire run**, against 90M for all ninety subagents combined. ~500K of the growth was the orchestrator's own prose. | The orchestrator is a Python function. It has no context, so this cost is zero — not reduced, absent. |
| **Agent identity** | Recovered from a hook payload, keyed by a session id written to `research/.active.json`. A wrong key silently emptied `fetch-log.jsonl`, and every claim then failed the gate an hour later. | Minted before dispatch and closed over by the hook. There is no lookup to get wrong, and no `.active.json`. |
| **Verdict authorship** | Inferred from a cumulative fetch log, which cannot tell two validators of one page apart once both have opened it. The workaround was an ordering constraint on the orchestrator. | The orchestrator writes the verdict and knows who it dispatched. No inference, no ordering constraint. |

The general shape of the change: **rules became properties.**

- *"Do not proceed past a failing gate"* is now an exception that blocks phases 6b and 7.
- *"Never paste a researcher's quote into a validator's prompt"* — the sharpest rule in the
  plugin, because that one shortcut destroys the only independent check in the system — is
  now unavailable. The validator prompt is built from three fields, and the quote is not
  one of them. There is nothing to leak. ([`test_orchestrator.py`](tests/test_orchestrator.py)
  asserts it.)
- *"Batch the verdicts, this is the largest cost lever"* is no longer advice. Recording a
  verdict costs nothing, because no model is in that loop.

---

## The pipeline

| Phase | What runs | Model | Enforced by |
|---|---|---|---|
| 0 | Intake — client, audience, constraints | — | CLI flags |
| 0.5 | Ingest local notes and prior runs | — | `ingest.py`, a file walk |
| 1 | `planner` decomposes into 6–12 self-contained sub-questions | `claude-sonnet-5` | no search tools |
| 2 | one `researcher` per sub-question, in parallel | `claude-sonnet-5` | disjoint claim-id blocks |
| 3 | one `validator` per claim, then a **second on a different model** for every material claim | `claude-haiku-4-5`, then `claude-sonnet-5` | tool grant + `validator_guard` |
| 4 | `gap-hunter` names what a domain expert would expect and does not find | `claude-opus-5` | capped at 2 rounds |
| 5 | `synthesizer` writes the evidence pack | `claude-fable-5` | no web tools |
| 6 | **the gate** — eight checks | — | a function that raises |
| 6b | the Obsidian vault | — | only after the gate passes |
| — | **HUMAN GATE** | — | `draft` is a separate invocation |
| 7 | `proposal-writer` drafts from the approved pack; gate re-runs over the draft | `claude-fable-5` | no web tools |

Models are pinned to full ids in `settings.py` and overridable per role
(`RESEARCH_AGENT_MODEL_VALIDATOR=claude-sonnet-5`).

### The gate

A non-zero result blocks everything downstream. The checks:

| Check | Catches |
|---|---|
| `citations-resolve` | a `[C012]` with no ledger row |
| `verdict-admission` | a material claim missing its escalation, or both verdicts from one validator |
| `fetch-provenance` | a cited URL nothing ever retrieved — the signature of a fabricated citation |
| `validator-blindness` | a verdict recorded for a page its validator never opened |
| `validator-tool-restrictions` | a validator that searched instead of fetching what it was given |
| `uncited-prose` | an assertion with no claim behind it — bullets and table rows count |
| `source-mix` | a pack leaning on blogs where first-party docs exist |
| `claim-quote` | a cited row with no verbatim quote, or one over 50 words |

The vault is built **after** the gate, never before: a fully rendered vault is the artefact
a reader trusts most, so one must never exist for a pack that failed.

---

## Blindness, mechanically

A validator sees a claim id, a claim, and a URL. It has no `Read`, no `Grep`, no `Glob`,
and no `WebSearch`. It does have `Bash`, because 57% of the claims in the plugin's first
real run cited PDFs and `WebFetch` cannot decode a PDF binary — and `cat claims.jsonl` is a
read. So `hooks.validator_guard` denies any `Bash` command that names a ledger or reaches
the workspace, and denies search and filesystem reads outright.

Its independence is a property of what it cannot do, and the gate re-checks the result
against the fetch log afterwards.

---

## What else changed, and why

**The researcher holds no shell.** In the plugin it held `Bash` only to run
`add_claim.py`. That grant carried a real cost: a page read with `curl` is invisible to the
retrieval recorder, and one run lost 17 claims to exactly that. Here `add_claim` is an
in-process MCP tool (`tools.py`), bound to this run's workspace, and the researcher's
entire write surface is that one validated call.

**Carried claims are re-fetched in groups of five** rather than one researcher per claim.
Same rows in the ledger, roughly a fifth of the dispatches.

**`verify-report.md` gained a "Run economics" section.** The plugin measured the
orchestrator's context growth, because the orchestrator was a model and its own prose was
most of the bill. That number is now structurally zero, so the honest thing to report moved:
cost per role, per dispatch, from `run-log.jsonl`.

**Every dispatch has a turn ceiling and a spend ceiling.** A researcher that has not
finished in 40 turns is looping, not researching. `RESEARCH_AGENT_BUDGET_USD` (default
`$2.00`) caps any single agent.

**Permission mode is `dontAsk`.** In a pipeline with nobody at the keyboard, a permission
prompt is a hang. Each agent's grant is pre-allowed and everything else is denied.

**Sessions load none of your settings** (`setting_sources=[]`, `skills=[]`,
`strict_mcp_config=True`). Without that the CLI would load your `CLAUDE.md` and installed
plugins — including the `proposal-research` plugin this was ported from, whose hooks would
then fire alongside these ones and double every fetch-log row.

The plugin at `plugins/proposal-research/` is untouched and still works.

---

## Optional MCP servers

`microsoft_docs_mcp` and `headroom` sharpen the researcher but are not required. Point
`RESEARCH_AGENT_MCP_CONFIG` at a JSON file (either `{name: config}` or Claude Code's
`{"mcpServers": {...}}` shape) and their tools are granted. Without it those tools are
filtered out of each agent's grant and the pipeline runs on `WebSearch` and `WebFetch`
alone — a missing optional server costs the tools, not the run.

---

## Layout

```
research_agent/
  settings.py       model pinning, optional MCP servers, tool filtering
  agents.py         the six roles as AgentDefinitions — the tool grants are the design
  prompts/          one markdown prompt per role
  tools.py          the in-process MCP ledger server
  hooks.py          retrieval recorder, ledger guard, validator guard — bound per dispatch
  runner.py         one dispatch: role in, AgentRun out
  orchestrator.py   phases 0-7
  cli.py            research / draft / verify
  ledger/           workspace, claims, verdicts        ] vendored from the plugin,
  gate/verify.py    the eight checks                   ] import paths rewritten,
  vault/build.py    the deterministic vault builder    ] behaviour unchanged
  ingest.py         phase 0.5
```

## Tests

```bash
pytest                       # from research-agent/
```

421 tests. 280 are the plugin's own suite, ported with import rewrites only — the vendored
ledger, gate, vault and ingest modules still have to satisfy every assertion they did
before. The remaining 141 cover what is new: the tool grants, the hook callbacks, the
in-process ledger server, dispatch configuration, the phase driver, and the CLI.
