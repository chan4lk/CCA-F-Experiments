---
name: codebase-map
description: Use when orienting in an unfamiliar part of this repo — mapping which of the four proposal-research implementations owns a behaviour, tracing where a vendored file diverged, or finding every caller of a symbol across the six packages. Produces a summary, not a file dump.
context: fork
argument-hint: "<what you are looking for, e.g. 'where the gate rejects an unresolvable citation'>"
allowed-tools: Read, Grep, Glob
---

# Codebase map

Answer: `$ARGUMENTS`

`context: fork` is the whole point of this skill. Mapping this repo means reading a lot of
files, and the reading is worth nothing once the answer is found. Run in a forked context and
the greps, the false leads, and the forty files opened along the way stay out of the main
conversation — what comes back is the summary. Read-only tools only: this skill answers
questions, it does not change anything.

## How to search here

This repo has one design implemented four times. A symbol appearing in four places is normal
and is **not** shared code:

- `plugins/proposal-research/` — the plugin, markdown agents plus hooks
- `research-agent/` — Claude Agent SDK
- `research_agent_batch/` — Batches API, local tools
- `research_agent_batch_server_tools/` — Batches API, server tools

`ledger/`, `gate/verify.py`, `vault/build.py` and `ingest.py` are **vendored copies** with
import paths rewritten. So:

1. Start with `Grep` for the symbol or message across the repo — do not read files first.
2. Count the hits per implementation before reading any of them. Four hits means four copies.
3. Read only the copy the question is about. If the question does not name one, say which four
   it could be and ask, rather than reading all four.
4. Follow imports with `Read` from the hit outwards. Do not read a whole package to build
   context you will not use.

## What to return

Keep it under a page:

- **The answer**, first, in two or three sentences.
- **Where it lives** — `path:line` for each site that matters, clickable.
- **Which implementation(s)** the answer applies to, explicitly, and whether the other copies
  differ.
- **What you did not check**, if a lead was left open.

No file contents unless a specific block is the answer. No narration of the search.
