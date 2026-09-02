# Backlog — CCAR-F exam scenarios as runnable code

Source: *Claude Certified Architect – Foundations* exam guide (CCAR-F, v1.0, effective July 2026).
The exam presents 4 of 6 scenarios drawn from a fixed bank. Each backlog item below turns one
scenario into working code in this repo, so every task statement behind it has something to run.

**Scenario 3 (Multi-Agent Research System) has no backlog item** — it is already implemented four
times in `plugins/proposal-research/`, `research-agent/`, `research_agent_batch/` and
`research_agent_batch_server_tools/`. Domains 1, 2 and 5 are exercised there. The five items below
cover the other five scenarios.

Ordered simplest → most complex. Each is independently runnable and independently testable.

| # | Item | Scenario | Domains | Where | Status |
|---|---|---|---|---|---|
| 1 | Structured data extraction | 6 | 4 (20%), 5 (15%) | `src/extraction/` | built · 42 tests |
| 2 | Claude Code in CI | 5 | 3 (20%), 4 (20%) | `src/ci_review/` + `.github/workflows/` | built · 50 tests |
| 3 | Claude Code configuration & workflows | 2 | 3 (20%), 5 (15%) | `.claude/`, `docs/claude-code-workflows.md` | built · config only |
| 4 | Customer support resolution agent | 1 | 1 (27%), 2 (18%), 5 (15%) | `src/support_agent/` | built · 50 tests |
| 5 | Codebase explorer / developer productivity | 4 | 2 (18%), 3 (20%), 1 (27%) | `src/code_explorer/` | built · 40 tests |

Every suite runs offline against injected fakes. Each package runs from its own directory:
`cd src/<name> && uv run --project ../.. pytest`.

---

## 1. Structured data extraction (Scenario 6)

**Why first:** one synchronous API call per document, no subprocess, no agent loop, fully testable
against fixture documents. The whole of Domain 4 lands here.

Build `src/extraction/` — extracts invoice/receipt facts from unstructured text.

- `tool_use` with a JSON schema as the structured-output mechanism; `strict: true` (4.3)
- `tool_choice` forced to a named tool so extraction always runs; `"any"` when the document type
  is unknown (4.3)
- Schema design: nullable optional fields so absent data is not fabricated, enum + `"other"` +
  detail string, `"unclear"` for ambiguity (4.3)
- Few-shot examples covering varied document shapes and ambiguous cases (4.2)
- Semantic validation the schema cannot catch — `calculated_total` vs `stated_total`,
  `conflict_detected` (4.4)
- Retry-with-error-feedback that resends document + failed extraction + specific errors, and
  classifies *absent information* as non-retryable (4.4)
- Field-level confidence, calibrated threshold, routing to human review (5.5)
- Batch path: one `custom_id` per document, correlate results by id, resubmit only failures (4.5)

**Done when:** `pytest` green from `src/extraction/`, and
`PYTHONPATH=extraction uv run --project ../.. python -m extraction samples/invoice_clean.txt invoice`
prints a validated record. — *Built. 42 tests green; the live run is unverified, see the note
at the foot of this file.*

## 2. Claude Code in CI (Scenario 5)

**Why second:** a thin wrapper over the `claude` CLI plus a workflow file. No new architecture.

Build `src/ci_review/` and a GitHub Actions workflow.

- `claude -p` non-interactive, `--output-format json` + `--json-schema` for parseable findings (3.6)
- Review criteria as explicit categorical rules, not "be conservative" (4.1)
- Few-shot examples separating acceptable patterns from genuine issues to cut false positives (4.2)
- Prior findings passed in context so a re-run reports only new or still-unaddressed issues (3.6)
- Existing test files passed in context so generated tests do not duplicate coverage (3.6)
- A `detected_pattern` field on each finding for dismissal-pattern analysis (4.4)
- An independent review instance — not the session that wrote the code (4.6)
- Per-file passes plus one cross-file integration pass (4.6)

**Done when:** the workflow runs on a PR and posts structured inline comments, and the finding
parser has unit tests that run without network. — *Built, 53 tests green. The workflow ran on
its own PR (#5) and found two real bugs in itself: a `PYTHONPATH` that pointed inside the
package so `python -m` could not import it, and a demand for `ANTHROPIC_API_KEY` when this
repo's secret is `CLAUDE_CODE_OAUTH_TOKEN`. Both fixed. It is now **manual-only** — the repo
already runs `Claude Code Review` on every PR — so it has not yet posted inline comments on a
real diff.*

## 3. Claude Code configuration & workflows (Scenario 2)

**Why third:** all declarative, but many interlocking pieces and the hierarchy has to be right.

Extend `.claude/` (exempt from the `src/` rule — Claude Code fixes these paths).

- CLAUDE.md hierarchy demonstrated: project root, `@import` of `.claude/rules/*`, and a
  directory-level CLAUDE.md (`src/CLAUDE.md` already exists) (3.1)
- Path-scoped rules with `paths:` glob frontmatter so conventions load only when editing matching
  files — e.g. a test convention rule on `**/test_*.py` (3.3)
- Project-scoped slash commands in `.claude/commands/` (3.2)
- A skill in `.claude/skills/` using `context: fork` to keep verbose output out of the main
  session, plus `allowed-tools` and `argument-hint` frontmatter (3.2)
- Written guidance on plan mode vs direct execution, and on the Explore subagent for verbose
  discovery (3.4)
- The iterative-refinement patterns: concrete input/output examples, test-first iteration, the
  interview pattern, batching interacting issues into one message (3.5)

**Done when:** `/memory` shows the expected files loaded, a path-scoped rule demonstrably does not
load outside its glob, and each command and skill runs. — *Built: two path-scoped rules, two
commands, one forked skill, plus `docs/claude-code-workflows.md` for the plan-mode and
iterative-refinement halves. The `paths:` frontmatter key is written as the exam guide documents
it and has not been confirmed against this CLI build; if the key is wrong the rule still loads,
just unconditionally.*

## 4. Customer support resolution agent (Scenario 1)

**Why fourth:** first item needing the Agent SDK, an MCP server, hooks, and a real agent loop.

Build `src/support_agent/` on `claude-agent-sdk` with an in-process MCP server.

- MCP tools `get_customer`, `lookup_order`, `process_refund`, `escalate_to_human` (2.1)
- Tool descriptions carrying input formats, example queries, edge cases and boundaries; no two
  tools overlapping (2.1)
- Structured MCP errors: `isError`, `errorCategory` (transient/validation/business/permission),
  `isRetryable`, human-readable text; access failure distinguished from valid empty result (2.2)
- A `PreToolUse` hook enforcing the prerequisite gate — `process_refund` blocked until
  `get_customer` returned a verified id — because prompt instructions have a non-zero failure
  rate (1.4, 1.5)
- A `PreToolUse` hook blocking refunds over the policy threshold and redirecting to escalation (1.5)
- A `PostToolUse` hook normalising heterogeneous formats (unix vs ISO 8601 timestamps, numeric
  status codes) before the model sees them (1.5)
- Tool-output trimming so 40-field order lookups do not flood context (5.1)
- A persistent "case facts" block (amounts, dates, order numbers, statuses) held outside the
  summarised history (5.1)
- Explicit escalation criteria with few-shot examples: honour an explicit request for a human
  immediately; escalate on policy gaps; ask for identifiers on multiple matches rather than
  guessing (5.2)
- A structured handoff summary — customer id, root cause, refund amount, recommended action — for
  a human who cannot see the transcript (1.4)

**Done when:** the prerequisite gate and the threshold block are proven by tests that assert the
tool call was denied, not that the model chose not to make it. — *Built. 50 tests green, including
those denials; no live conversation has been run.*

## 5. Codebase explorer / developer productivity (Scenario 4)

**Why last:** built-in tools plus MCP plus session lifecycle plus subagents — the widest surface,
and the one that depends on habits formed in items 1–4.

Build `src/code_explorer/` on `claude-agent-sdk`.

- Built-in tools used for what each is for: `Grep` for content, `Glob` for paths, `Read`/`Write`
  for whole files, `Edit` for targeted change with `Read`+`Write` as the non-unique-match
  fallback (2.5)
- Incremental exploration — Grep for entry points, then Read to follow imports — rather than
  reading everything up front (2.5)
- MCP servers wired in: project-scoped `.mcp.json` with `${VAR}` expansion for the shared server,
  user-scoped for experimental ones; tool descriptions detailed enough that the agent prefers the
  MCP tool over `Grep` (2.4)
- MCP resources exposing a catalog so the agent does not have to probe for what exists (2.4)
- Named session resume (`--resume <name>`) and `fork_session` for divergent approaches from one
  shared analysis baseline (1.7)
- The choice between resuming and starting fresh with an injected summary when tool results are
  stale (1.7)
- A scratchpad file persisting key findings across context boundaries, plus a state manifest the
  coordinator reloads on resume for crash recovery (5.4)
- Subagent delegation for verbose exploration, with the main agent keeping only summaries (5.4)
- Adaptive decomposition: map structure, find high-impact areas, then build a plan that changes as
  dependencies surface (1.6)

---

## What has not been verified

Every suite above passes offline. Nothing has been run against the live API: this workspace's
key is rate-limited to 0 requests/minute (`workspace POC_MI`), so a real extraction, a real
support conversation, and a real exploration session all remain unexercised. Same for the CI
workflow, which has not run on a pull request.
