# Proposal Research Plugin — Design

**Date:** 2026-08-29
**Status:** Approved design, pending implementation plan
**Author:** Chandima Ranaweera (with Claude)

## Problem

Building a client proposal for a product or solution — e.g. *"a ServiceNow agent built on
Copilot Studio with an MCP server, versus ServiceNow's native AI Studio agents"*, or
*"AML solutions for Sri Lankan banks"* — requires research that currently fails in two
distinct ways:

1. **Fabrication.** The research emits confident statements that are not true. In vendor
   and architecture proposals the most damaging of these are not invented from nothing;
   they are *technically true and materially wrong* — the feature is preview-only, GA in
   three regions, gated behind an unpriced licence tier, or deprecated last quarter.
2. **Missed coverage.** Details that were findable are not found. The research does not
   know what it failed to look for.

Both failures survive into the proposal, where they are expensive: a false capability
claim shapes an architecture and a price.

## Goal

A Claude Code plugin, `proposal-research`, that produces a **cited evidence pack** and then
— behind a human approval gate — a **draft proposal**, where every material factual claim is
mechanically traceable to a page that was provably retrieved during the run.

The guarantee is structural, not exhortative. Prompts that say "do not hallucinate" are not
the mechanism; file contracts, tool restrictions, and a blocking gate are.

## Non-goals

- Not a replacement for `agent-accelerator:research-studio` (company/person -> PRD set).
  This plugin's deliverable is an evidence pack and a proposal, not PRDs.
- No Perplexity/Grok dependency in v1. Baseline web tools plus Microsoft Learn only.
- No local vault/repo ingestion in v1.
- Caveman integration deferred (see Deferred, below).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Form factor | Claude Code plugin in this repo | Distributable to the team; matches the existing `chan4lk` marketplace layout (`./plugins/<name>`) |
| Deliverable | Evidence pack + proposal, two gates | The proposal cannot inherit unvetted claims |
| Validation bar | Tiered — hard-verify material claims | Best rigour/cost balance; context claims pass flagged |
| Coverage strategy | Generic decomposition + dedicated gap-hunter | Adaptive; avoids the fixed blind spots of pre-scripted playbooks |
| Sources | WebSearch, WebFetch, `microsoft_docs_mcp` | First-party vendor docs beat blogs for material claims |
| Enforcement | Claim ledger + hooks + blocking verify script | Approach A + C |
| Token strategy | Headroom MCP + model tiering | Caveman deferred — not installed on this machine |

## Architecture

### Pipeline

```
/proposal-research:research "<proposal question>"
   |
 0 Intake .......... orchestrator asks: client, audience, hard constraints, incumbent tech
 1 planner ......... no web tools -> plan.md: self-contained sub-questions, tier-tagged
 2 researcher xN || . WebSearch/WebFetch/MS-Learn -> APPEND rows to claims.jsonl
 3 validator  xN || . BLIND re-fetch -> verdicts.jsonl
 4 gap-hunter ...... reads confirmed set -> gaps.md -> loop to 2 (max 2 rounds)
 5 synthesizer ..... no web tools -> evidence-pack.md, every fact carries [C012]
 6 verify_pack.py .. HARD GATE — non-zero exit blocks progress
   |
 == HUMAN GATE — review evidence-pack.md + verify-report.md, approve or correct ==
   |
 7 proposal-writer . no web tools, approved pack only -> proposal.md -> gate re-runs
```

### Agent roster

| Agent | Model | Tools | Key constraint |
|---|---|---|---|
| `planner` | sonnet | Read, Write | Cannot search — decomposition only |
| `researcher` xN (parallel) | sonnet | WebSearch, WebFetch, MS-Learn, Write, Headroom | Must quote verbatim, never paraphrase |
| `validator` xN (parallel) | haiku | WebFetch, MS-Learn fetch, Write | **No WebSearch** — cannot shop for a friendlier source |
| `gap-hunter` | opus | Read, WebSearch, Write | Names what a domain expert would expect and isn't there |
| `synthesizer` | **fable** | Read, Write | No web tools — cannot add a fact absent from the ledger |
| `proposal-writer` | **fable** | Read, Write | Reads the approved pack only |

Model is passed explicitly on each `Agent` dispatch (`model: "fable"`), not via agent-file
frontmatter — `fable` is documented on the Agent tool's enum; frontmatter support is unverified.

**Validator escalation:** validators run haiku, but any claim of `tier: material` that a haiku
validator marks `CONFIRMED` is re-checked by a sonnet validator. Haiku reliably catches dead
links and contradictions; preview/GA/licence-tier caveats are the subtle read it is weakest at,
and those are precisely the claims that move a proposal.

### The claim ledger

`claims.jsonl` — researchers only ever **append**:

```json
{"id":"C012","sub_q":"Q3","tier":"material",
 "claim":"Copilot Studio MCP tools cap at 10 tools per server connection",
 "url":"https://learn.microsoft.com/...",
 "quote":"<verbatim, <=50 words, copied from the page>",
 "source_type":"vendor_doc","raw_hash":"abc123",
 "fetched_at":"2026-08-29T09:41Z"}
```

Three rules do the anti-hallucination work:

1. **A claim with no verbatim quote is malformed** and is rejected by `ledger_lint.py` before
   it lands. Paraphrase is where fabrication hides.
2. **Validators are blind, mechanically.** A validator receives `{id, claim, url}` in its
   dispatch prompt only — never the researcher's narrative, quote, or `raw_hash`. This is
   enforced by tool restriction rather than instruction: the validator has **no `Read` tool**
   and **no `WebSearch`**, so it cannot open `claims.jsonl` and cannot seek a friendlier
   source. It either stands the claim up at the cited URL or it does not.
3. **The synthesizer has no web tools.** It physically cannot introduce a fact that is not
   in the ledger.

### Verdicts

`CONFIRMED` · `CONTRADICTED` · `NOT_FOUND` · `MISLEADING`

`MISLEADING` exists for claims that are literally present on the page but materially wrong in
context — preview-only, region-limited, licence-gated, deprecated. The validator attaches the
caveat text, and the caveat rides into the pack next to the claim.

Admission rules:
- `tier: material` requires `CONFIRMED` to enter the pack.
- `tier: context` may enter flagged low-confidence if `NOT_FOUND` and nothing contradicts it.
- Everything else lands in an **"Unverified & excluded"** appendix — visible, never silently
  dropped, so the reader can see what the research could not stand up.

### Gap loop

Maximum 2 rounds. After round 2 the gap-hunter's remaining questions become the pack's
"Open questions" section rather than triggering more searching. This bounds runs on
open-ended topics such as "AML for Sri Lankan banks".

## Token strategy

### Headroom

Installed at `/Library/Frameworks/Python.framework/Versions/3.12/bin/headroom`, wired as an
MCP server (`headroom mcp serve`). Tools: `headroom_compress`, `headroom_retrieve`, `headroom_stats`.

Honest scope: subagents already isolate raw page dumps from the orchestrator's context, so
Headroom's marginal saving is smaller than it first appears. It pays in three places:

1. **Inside a researcher's own loop.** A researcher fetching 6-10 pages for one sub-question
   drowns in its own context. Each `WebFetch` -> `headroom_compress` -> retain compressed text
   plus hash, discard raw. The agent stays coherent to the end of its sub-question.
2. **Audit trail.** The `raw_hash` column lets the human gate retrieve *the original page as it
   was when fetched*, without re-fetching. This is not token saving — it is the evidence
   surviving the page changing underneath the proposal weeks later.
3. **Synthesizer and gap-hunter** read the entire confirmed ledger; compressed bodies keep that
   read affordable at 200+ claims.

**Hard exception:** the validator must never read the researcher's compressed blob or `raw_hash`.
Sharing that cache would collapse the blindness that makes validation meaningful.

### Model tiering

Cost concentrates in the two parallel roles. `validator` (highest volume) runs haiku with
targeted sonnet escalation; `researcher` runs sonnet because quote-extraction quality gates
every downstream phase. `fable` is reserved for the two roles whose output is read by a client.

## Enforcement layer

### Probe result (settled 2026-08-29)

An empirical probe on this Claude Code build established:

1. `PostToolUse` hooks **do** fire for tool calls made inside subagents.
2. Subagent invocations carry **`agent_id` and `agent_type`** in the hook payload; main-session
   invocations do not.
3. Hook configuration hot-reloads — no session restart needed after install.

Full payload keys observed: `cwd`, `duration_ms`, `hook_event_name`, `permission_mode`,
`prompt_id`, `session_id`, `tool_input`, `tool_name`, `tool_response`, `tool_use_id`,
`transcript_path`, plus `agent_id`/`agent_type` for subagent calls.

Finding 2 materially strengthens the design. The gate's provenance check was originally
*"this URL was fetched by someone this session."* With per-agent attribution it becomes:
**"the validator that confirmed C012 fetched C012's URL itself."** Blind validation becomes a
property provable from the log rather than a promise made in a prompt.

### Hooks

**`record_fetch.py`** — `PostToolUse`, matcher `WebFetch|WebSearch|mcp__microsoft_docs_mcp__.*`.
Appends `{ts, tool, url, query, agent_id, agent_type}` to `fetch-log.jsonl`. A URL appearing in
the pack but never in the fetch log is the exact signature of a hallucinated citation.

**`ledger_lint.py`** — `PostToolUse`, matcher `Write|Edit`, scoped to `claims.jsonl`. Parses each
row and **exits 2** (blocking, with feedback to the agent) if the row is missing `id`, `url`,
`quote`, or `tier`, or if `quote` is empty. The agent is told why and rewrites.

### `verify_pack.py` — the gate

Six checks; non-zero exit on any failure.

1. Every `[Cxxx]` in the pack resolves to a row in `claims.jsonl`
2. Every cited claim has a verdict; `tier: material` claims are `CONFIRMED`
3. Every cited URL appears in `fetch-log.jsonl` — provenance
4. **Every material `CONFIRMED` claim was fetched by each validator that ruled on it**, matched
   by `agent_id` in the fetch log — blindness. Material claims carry two validator `agent_id`s
   (haiku plus the sonnet escalation); both must appear against that claim's URL
5. No factual paragraph outside the "Unverified" appendix lacks a citation
6. Source-mix report: share of vendor-doc / regulator / analyst / blog. A pack leaning on blogs
   for material claims is surfaced as a smell even when it passes

Output is written to `verify-report.md` beside the pack, so the human gate reads both.

## Repository layout

```
CCAF/
├─ .claude-plugin/marketplace.json        # enables `/plugin marketplace add ~/repos/CCAF`
└─ plugins/proposal-research/
   ├─ .claude-plugin/plugin.json
   ├─ README.md
   ├─ agents/
   │   ├─ planner.md         researcher.md      validator.md
   │   └─ gap-hunter.md      synthesizer.md     proposal-writer.md
   ├─ skills/proposal-research/SKILL.md   # orchestrator: phases, dispatch, gates
   ├─ commands/
   │   ├─ research.md   # full pipeline, phases 0-6, stops at the human gate
   │   ├─ draft.md      # phase 7 only, on an approved pack
   │   └─ verify.md     # re-run the gate standalone
   ├─ hooks/
   │   ├─ hooks.json
   │   ├─ record_fetch.py
   │   └─ ledger_lint.py
   └─ scripts/verify_pack.py
```

Per-run workspace: `research/<slug>/` containing `plan.md`, `claims.jsonl`, `verdicts.jsonl`,
`gaps.md`, `fetch-log.jsonl`, `evidence-pack.md`, `verify-report.md`, `proposal.md`.

## Testing

- `verify_pack.py` unit tests against synthetic fixtures — orphan citation, missing verdict,
  unlogged URL, wrong-validator attribution, uncited factual paragraph. Each must fail the gate.
- `ledger_lint.py` fixture — a quote-less row must be rejected with exit 2.
- Blind-validation fixture — a claim deliberately misattributed to a real URL must return
  `NOT_FOUND`, never `CONFIRMED`.
- End-to-end smoke on the ServiceNow / Copilot Studio question: exercises the
  `microsoft_docs_mcp` path and the preview/GA `MISLEADING` case.

## Deferred

- **Caveman** — recommended internally for token saving but not installed on this machine
  (no binary, no npm global, no plugin, no skill). Deferred until its interface can be read
  directly rather than guessed at.
- **Perplexity / Grok discovery**, **local vault ingestion**, **playbook checklists** — all
  considered and consciously left out of v1.
