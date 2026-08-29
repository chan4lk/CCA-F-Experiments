# Proposal Research

Multi-agent web research for product and solution proposals.

## Why

Proposal research fails two ways: it states things that are not true, and it
misses details that were findable. The damaging false claims are rarely
invented — they are *technically true and materially wrong*: preview-only,
region-locked, licence-gated, deprecated last quarter.

This plugin makes the guarantee structural rather than exhortative. Prompts
saying "do not hallucinate" are not the mechanism. These are:

- Researchers cannot write `claims.jsonl` or `verdicts.jsonl` at all: a
  PreToolUse hook denies `Write` and `Edit` on both and redirects to
  `add_claim.py` / `add_verdict.py`, which validate the row — **verbatim quote
  required** — and append it atomically.
- The gate re-checks the quote itself rather than trusting that CLI, because the
  researcher carries `Bash` and an append redirect would not trip the hook. A
  cited claim with no quote, or a quote over 50 words, fails the gate.
- Validators are **blind by tool restriction** — no `Read`, no `WebSearch` — so
  they cannot open the ledger and cannot shop for a friendlier source.
- The synthesizer has **no web tools**, so it cannot introduce a fact absent
  from the ledger.
- A blocking gate proves every cited URL was actually retrieved this session, by
  the validator that ruled on it — and that a material claim was confirmed by two
  *different* validators running two *different* models.
- The gate also requires a citation on every factual paragraph, bullet and table
  row, so a pack cannot pass by asserting a cap, a price or an availability date
  in a markdown shape no check was looking at.

## Usage

    /proposal-research:research "ServiceNow agent via Copilot Studio + MCP vs native AI Agents"
    /proposal-research:draft      # after approving the evidence pack
    /proposal-research:verify     # re-run the gate standalone

Output lands in `research/<slug>/`, including a self-contained Obsidian vault
at `research/<slug>/vault/`.

## Requirements

- Python 3.9+ on PATH as `python3` (stdlib only — no packages to install)
- Optional: `microsoft_docs_mcp` for first-party Microsoft documentation
- Optional: `headroom` MCP for in-agent compression

## Installation

    /plugin marketplace add <path to this repo>
    /plugin install proposal-research@ccaf

Hook configuration hot-reloads, so no restart is needed.

## Verifying the install

    python3 -m pytest plugins/proposal-research/tests/ -v

All tests are stdlib-only and run under the system `python3`.

## How the guarantee works

`research/<slug>/` holds the audit trail for a run:

| File | What it proves |
|---|---|
| `claims.jsonl` | Every claim, with the verbatim quote it rests on |
| `verdicts.jsonl` | Who ruled on each claim and what they found |
| `fetch-log.jsonl` | Every page retrieved, and which agent retrieved it |
| `verify-report.md` | The gate result, with source mix and every warning |
| `vault/06-Sources/Sources.md` | Per-claim anchors plus derived reliability notes |

The gate cross-references the first three. A citation can only survive if the page behind it
was really fetched, by the validator that really ruled on it.
