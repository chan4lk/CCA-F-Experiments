# Proposal Research

Multi-agent web research for product and solution proposals.

## Why

Proposal research fails two ways: it states things that are not true, and it
misses details that were findable. The damaging false claims are rarely
invented — they are *technically true and materially wrong*: preview-only,
region-locked, licence-gated, deprecated last quarter.

This plugin makes the guarantee structural rather than exhortative. Prompts
saying "do not hallucinate" are not the mechanism. These are:

- Researchers append claims to `claims.jsonl` with a **verbatim quote**. A row
  without one is rejected by a hook before it lands.
- Validators are **blind by tool restriction** — no `Read`, no `WebSearch` — so
  they cannot open the ledger and cannot shop for a friendlier source.
- The synthesizer has **no web tools**, so it cannot introduce a fact absent
  from the ledger.
- A blocking gate proves every cited URL was actually retrieved this session,
  by the validator that ruled on it.

## Usage

    /proposal-research:research "ServiceNow agent via Copilot Studio + MCP vs native AI Agents"
    /proposal-research:draft      # after approving the evidence pack
    /proposal-research:verify     # re-run the gate standalone

Output lands in `research/<slug>/`, including a self-contained Obsidian vault
at `research/<slug>/vault/`.

## Requirements

- Python 3.12+ on PATH as `python3` (stdlib only — no packages to install)
- Optional: `microsoft_docs_mcp` for first-party Microsoft documentation
- Optional: `headroom` MCP for in-agent compression
