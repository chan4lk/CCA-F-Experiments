# Claude Code workflows in this repo

> Backlog item 3 of `backlog/2026-09-02-ccar-f-scenarios.md`.
> CCAR-F Scenario 2. Domains 3 (Claude Code Configuration & Workflows) and 5 (Context
> Management & Reliability).

The configuration itself is code — `.claude/` and the CLAUDE.md files. This document covers the
two parts of the scenario that are judgement rather than files: when to plan and when to just
do it, and how to iterate when the first attempt is wrong.

## What is configured, and why there

| Loaded | File | Scope |
|---|---|---|
| Always | `CLAUDE.md` | project-wide facts: the two SDKs, the four implementations, the invariants |
| Always, via `@import` | `.claude/rules/repository-layout.md` | where new code goes — applies to every task |
| When under `src/` | `src/CLAUDE.md` | the shape a new project in `src/` takes |
| When editing a test | `.claude/rules/python-tests.md` | `paths: **/test_*.py`, `**/conftest.py`, … |
| When editing CI | `.claude/rules/github-workflows.md` | `paths: .github/workflows/**` |
| On request | `.claude/commands/*.md` | `/check`, `/new-demo` |
| On request, forked | `.claude/skills/codebase-map/` | verbose exploration, summary returned |

Three placement decisions worth stating.

**Path-scoped rules over a subdirectory CLAUDE.md.** Test files here live in seven different
directories. A `tests/CLAUDE.md` would have to be copied seven times and would drift; a
`paths:` glob applies to files by *type*, wherever they are. The rule for where new code goes
is the opposite case — it applies to every task, so it is `@import`ed into the always-loaded
CLAUDE.md instead.

**Project-scoped, not user-scoped.** `.claude/commands/` and `.claude/rules/` are committed, so
a new contributor gets them on clone. The same content in `~/.claude/` applies to one machine
and one person, and is the usual reason a teammate "isn't getting the instructions" — the
files are there, just not in a place version control can reach. Personal variants belong in
`~/.claude/skills/` under a *different name*, so they do not shadow the shared one.

**A skill, not a CLAUDE.md section.** `codebase-map` is invoked for one kind of task and
produces verbose output. As a CLAUDE.md section it would cost context on every unrelated turn;
as a skill it costs nothing until asked for. `context: fork` then keeps the forty files it
opens out of the main conversation — the answer comes back, the search does not.

## Plan mode versus direct execution

Plan mode is for changes where the *approach* is the risk, not the typing:

- multiple valid approaches with different consequences — a migration that could be done
  in-place or behind an adapter;
- architectural commitments — anything that adds a fifth implementation, or changes something
  vendored into all four;
- multi-file changes where the shape only becomes clear after reading — "add tests to the
  legacy areas of this package";
- anything touching the shared invariants in `CLAUDE.md`, where the cost of discovering the
  design was wrong after the edits is a full revert.

Direct execution is for changes where the scope is already clear:

- a single-file bug fix with a stack trace pointing at the line;
- adding a validation check to one function;
- a rename with a known blast radius;
- anything the `/new-demo` command already scaffolds.

The two combine more often than they compete: plan the investigation, then execute the plan
directly. And for the discovery phase inside either, delegate to the Explore subagent or the
`codebase-map` skill — a multi-phase task that reads its way to context exhaustion in phase one
has nothing left for phase three.

## Iterating when the first attempt is wrong

**Show, do not describe.** Two or three concrete input/output pairs settle a transformation
that a paragraph of prose gets interpreted three different ways. This is why
`src/ci_review/criteria.py` carries paired examples — the f-string `execute` and the
parameterised one — rather than a longer definition of "SQL injection".

**Tests first, then iterate on failures.** Write the suite covering expected behaviour, edge
cases, and the performance bound; then hand over failures one at a time. A failing assertion is
an unambiguous specification in a way that "it doesn't handle empty input right" is not.

**Ask for the interview.** In an unfamiliar domain, ask Claude to ask *you* the questions first
— cache invalidation, failure modes, what happens on partial writes. Surfacing those before
implementation is cheaper than discovering them in review.

**Batch interacting problems, sequence independent ones.** Three issues that interact go in one
message with all three described, or fixing the first invalidates the analysis of the other
two. Three unrelated issues go one at a time, because a single message about all three gets a
shallower fix for each.
