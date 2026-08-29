---
name: proposal-research
description: Research a product or solution proposal question across the web and emit a cited evidence pack, a draft proposal, and a self-contained Obsidian vault. Use when the user asks to research a proposal, compare vendor or architecture options for a client, or build a solution proposal that must not contain false capability, pricing, or regulatory claims. Six subagents communicate through append-only claim ledgers; a blocking gate proves every cited page was actually retrieved.
---

# Proposal Research

You orchestrate. You do not search, and you do not write claims yourself.

Set `PR` to `${CLAUDE_PLUGIN_ROOT}`, then derive the slug with the plugin's own slugifier rather than by hand, so the workspace path is the same one the scripts compute:

```bash
SLUG=$(python3 -c "import sys; sys.path.insert(0, '$PR/scripts'); import workspace; print(workspace.slugify(sys.argv[1]))" "<the question>")
WS="research/$SLUG"
```

## Phase 0 — Intake

Use AskUserQuestion to establish, in one call:

1. **Client / prospect** — who the proposal is for
2. **Audience** — technical buyer, procurement, C-level, regulator
3. **Hard constraints** — budget ceiling, timeline, incumbent tech, mandated platform
4. **Context paths** — any local folders to ingest (optional)

Create the workspace, then register the run so the fetch hook knows where to log. Read the
session id from the `CLAUDE_CODE_SESSION_ID` environment variable — hook events fired by tool
calls made inside a dispatched subagent still report the *parent* session's id, so
registering under your own `CLAUDE_CODE_SESSION_ID` is what lets fetches made by researchers
and validators resolve correctly too. If `CLAUDE_CODE_SESSION_ID` is not set on this host, ask
the user for a session identifier rather than inventing one.

```bash
python3 -c "
import os, sys; sys.path.insert(0, '$PR/scripts')
from pathlib import Path
import workspace
session_id = os.environ['CLAUDE_CODE_SESSION_ID']
workspace.ensure_workspace(Path('$WS'))
workspace.set_active_run(Path('.'), session_id, '<slug>')
assert workspace.get_active_run(Path('.'), session_id) == '<slug>', 'active-run registration mismatch: wrong session_id key'
print('active run registered:', session_id, '->', '<slug>')
"
```

**If this registration is wrong, the fetch log stays empty and every claim fails the gate.**
A mismatched `session_id` key means `record_fetch.py`'s `get_active_run` lookup silently
returns nothing for every fetch call, `fetch-log.jsonl` never receives a single row, and
Phase 6 then fails every cited claim's `fetch-provenance` and `validator-blindness` checks —
a silent, total failure of the run that only surfaces an hour later at the gate. Do not settle
for confirming that `research/.active.json` exists; a file that exists under the wrong key
proves nothing. The `assert` above is the real check — confirm it did not raise before
continuing to Phase 0.5.

## Phase 0.5 — Ingest local context

```bash
python3 "$PR/scripts/ingest_context.py" --workspace "$WS" --question "<question>" \
  [--prior <prior run or vault>]... [--context <path>]... \
  [--configured-vault <path>] [--repo .] --limit 25
```

Read `ingest-report.md`. Carried claims skip discovery but are still re-validated.

## Phase 1 — Plan

Dispatch `planner`, **model `sonnet`**. Give it the question, the intake answers, and the
workspace path. It writes `plan.md`. Read it and confirm the sub-questions are genuinely
self-contained before fanning out — a vague sub-question wastes a whole researcher.

## Phase 2 — Research fan-out

Dispatch one `researcher` per sub-question, **model `sonnet`**, in a single message so they
run in parallel. Give each one:

- its sub-question, stated in full, and its tier
- the workspace path
- a **disjoint claim id range** (Q1 -> C001-C019, Q2 -> C020-C039, ...) so parallel
  researchers cannot collide on ids

Also dispatch one researcher per carried claim to re-fetch its URL and re-append it with a
fresh `fetched_at`, using the same id range discipline.

## Phase 3 — Validation fan-out

For every claim in `claims.jsonl`, dispatch a `validator`, **model `haiku`**, in parallel.

Give the validator **only** `{claim_id, claim, url}`. Never the researcher's quote, never
their narrative, never the raw_hash. The validator holds `Bash` (it must, to read PDFs)
but a PreToolUse guard blocks it from reaching `research/` or searching — do not undo
mechanically-enforced blindness by pasting the answer into the prompt.

**Record verdicts in batches, not one at a time.** This is the single largest cost lever in
the skill. The first real run spent roughly 468 orchestrator turns recording 468 verdicts,
and each of those turns re-read a context averaging 362,000 tokens — about 65% of the
entire run's token consumption, for work that is identical either way.

**Take each validator's `agentId` from its dispatch result.** You already have it; that is
what makes batching possible. Write the rows straight to a file — do not echo the JSON back
into your own context first:

```bash
cat > "$WS/verdict-batch.jsonl" <<'JSONL'
{"claim_id":"C012","verdict":"CONFIRMED","validator_model":"haiku","validator_agent_id":"<agentId>","quote":"..."}
{"claim_id":"C013","verdict":"MISLEADING","validator_model":"haiku","validator_agent_id":"<agentId>","quote":"...","caveat":"..."}
JSONL
python3 "$PR/scripts/add_verdict.py" --workspace "$WS" --batch "$WS/verdict-batch.jsonl"
```

A malformed row is reported and skipped; the rest still land. Fix and re-submit only those.

**Why explicit ids rather than inference here.** `--infer-agent-from` resolves identity from
the fetch log, and the log is cumulative: once two validators have opened the same page —
which happens constantly, since several claims cite one document — it cannot tell which one
is speaking, and refuses rather than guessing. Passing the id you already hold sidesteps
that entirely and removes any constraint on when you record. Keep `--infer-agent-from` for
the one-off single-row case where you genuinely do not have the id.

**Escalation:** every `material` claim a haiku validator marked `CONFIRMED` gets a second
validator, **model `sonnet`**. Dispatch the escalation wave in parallel too and record it as
its own batch. A material claim needs two CONFIRMED rulings from **two different validators
running two different models** to enter the pack — the gate checks the ids and the models,
not just the row count, because the same validator ruling twice proves nothing.

## Phase 4 — Gap hunt

Dispatch `gap-hunter`, **model `opus`**. It writes `gaps.md`. If it emits questions and you
have run fewer than **2 rounds**, return to Phase 2 for those questions only. After 2 rounds,
stop: remaining gaps become the pack's "Open Questions" section.

## Phase 5 — Synthesis

Dispatch `synthesizer`, **model `fable`**. It writes `evidence-pack.md` using the fixed H2
section contract. Re-read the contract in the agent file if the build fails.

## Phase 6 — The gate

```bash
python3 "$PR/scripts/verify_pack.py" --workspace "$WS"
```

**A non-zero exit blocks the pipeline.** Do not proceed to Phase 7, and do not present the
pack as trustworthy, until it passes. Typical failures and their real causes:

| Failure | Cause |
|---|---|
| `fetch-provenance` | The claim's URL was never retrieved — usually a fabricated citation, sometimes a missing `.active.json` |
| `validator-blindness` | A verdict was recorded for a page its validator never opened |
| `verdict-admission` | A material claim is missing its sonnet escalation pass, or both its verdicts came from the same validator |
| `uncited-prose` | The synthesizer asserted something with no claim behind it — bullets and table rows count |
| `claim-quote` | A cited ledger row has no verbatim quote, or one longer than 50 words |

## Phase 6b — Build the vault

**Only after the gate passes.** Building first would leave a fully rendered, openable
vault on disk with nothing on it saying the pack behind it failed — and a vault is the
artefact a reader trusts most, because it looks finished.

```bash
python3 "$PR/scripts/build_vault.py" --workspace "$WS"
```

Broken links exit non-zero. Fix the pack, re-run the gate, and rebuild rather than editing
the vault by hand — the vault is generated output.

## HUMAN GATE

Present `evidence-pack.md`, `verify-report.md`, and the vault path. Say plainly what is
verified, what is low confidence, and what is in "Unverified & excluded".

**Stop. Do not draft the proposal until the user approves the pack.** The whole point of two
gates is that the proposal cannot inherit unvetted claims.

## Phase 7 — Draft the proposal

Only after approval. Dispatch `proposal-writer`, **model `fable`**, with the approved pack.
Then re-run both the gate and the builder over the proposal:

```bash
python3 "$PR/scripts/verify_pack.py" --workspace "$WS" --pack proposal.md \
  && python3 "$PR/scripts/build_vault.py" --workspace "$WS" --with-proposal
```

Chained on purpose, for the same reason Phase 6b follows Phase 6: a vault built over a
proposal that failed the gate looks exactly like one that passed.

## Phase 7b — Offer to copy out

Ask whether to copy the vault somewhere the user keeps proposals:

```bash
python3 "$PR/scripts/build_vault.py" --workspace "$WS" --with-proposal --copy-to "<path>"
```

## Rules for you, the orchestrator

- You never search and you never write to `claims.jsonl` or `verdicts.jsonl` by hand. Both
  are hook-protected.
- Dispatch parallel agents in **one message** with multiple tool calls, or they run serially.
- Never paste a researcher's quote into a validator's prompt. That single shortcut destroys
  the only independent check in the system.
- If the gate fails, report the failure honestly. Do not narrate around it, and do not
  present a failed pack as "mostly verified".

## Keeping your own context small

Your context is re-read on every turn you take, so its size multiplies by your turn count.
In the first real run that product was 172 million tokens — 65% of everything the run
processed — while all ninety subagents together came to 90 million. **You are the expensive
one, not the research.** Three habits keep it down:

- **Batch state-changing calls.** Verdicts go in batches (Phase 3). The same applies to any
  repeated one-line command: prefer one call over twenty.
- **Never route file content through yourself.** Hand agents a *path*, not a paste. When you
  need a number out of a ledger, compute it in the shell and read back the number — not the
  rows:

  ```bash
  python3 -c "import json,sys; rows=[json.loads(l) for l in open('$WS/claims.jsonl')]; \
    print(len(rows), 'claims,', sum(1 for r in rows if r['tier']=='material'), 'material')"
  ```

- **Do not echo agent output back to yourself.** A validator's JSON belongs in the batch
  file, written directly by the command that records it. Reading it into your context to
  reformat it costs the whole context again on the next turn, and it is the reformatting
  that tempts you to paste a quote where it does not belong.

Subagent context is cheap by comparison: it is discarded when the agent finishes. Push work
outward. If you find yourself holding something only so you can pass it along, pass the path
instead.
