# code_explorer — developer productivity

> Backlog item 5 of `docs/backlog/2026-09-02-ccar-f-scenarios.md`.
> CCAR-F Scenario 4. Domains 2 (Tool Design & MCP Integration), 3 (Claude Code Configuration
> & Workflows) and 1 (Agentic Architecture & Orchestration).

**The trade:** the built-in tools do the work, and everything this package adds exists to
survive the context window. An exploration agent's failure mode is not a wrong answer — it is a
session that has read so much it can no longer reason about any of it, and then starts
answering from typical patterns instead of the classes it found an hour ago. Scratchpad,
manifest, subagent, and the resume decision are four answers to that one problem.

## Run

```bash
cd src/code_explorer
uv run --project ../.. pytest                    # 40 tests, no CLI, no network

PYTHONPATH=code_explorer uv run --project ../.. python -m code_explorer \
  explore "How does the gate reject an unresolvable citation, and do all four copies agree?"
PYTHONPATH=code_explorer uv run --project ../.. python -m code_explorer status
PYTHONPATH=code_explorer uv run --project ../.. python -m code_explorer fork "adapter approach"
```

Needs Node and the `claude` CLI on `PATH`. Copy `mcp.example.json` to `.mcp.json` to wire in
project MCP servers. `EXPLORER_MODEL` and `EXPLORER_SUBAGENT_MODEL` both default to
`claude-haiku-4-5`.

## The five decisions

**Tool selection is taught once.** Grep for content, Glob for paths, Read for a whole file once
Grep has said which one, Edit for a targeted change — and when Edit fails on a non-unique
anchor, Read plus Write rather than a wider anchor and a guess. The rule that matters most is
the order: build understanding *outward* from an entry point, following imports, instead of
reading directories whole. Reading everything first fills the window with code you will not use
and leaves nothing for the reasoning.

**Verbose reading is delegated.** The `explore` subagent gets read-only tools, a cheap model,
and low effort; it reads widely and returns under 300 words with `path:line` references. The
coordinator keeps the high-level picture and never sees the forty files. Because a subagent
starts with no memory of the parent conversation, `subagent_prompt` is self-contained by
construction — question, constraints, and what a useful answer looks like — and it requires
each claim's source location as a *separate field* from the claim, so attribution survives the
handoff instead of dissolving into prose.

**Findings go to disk as they are produced.** `scratchpad.py` appends each established finding
with its location, and saves a manifest — goal, session id, phase, files read, open questions.
Two failures, one mechanism: in a long session the model re-reads the scratchpad instead of
trusting recall, and after a crash the coordinator reloads the manifest instead of
re-exploring. Exported as produced, not reconstructed afterwards.

**Resume, resume-with-notice, or start fresh — decided, not defaulted.** Resuming is cheap and
keeps everything, and is wrong the moment the prior tool results describe a repo that has
changed: the session then reasons over a snapshot, confidently. `session.decide()` resumes when
nothing analysed has moved; resumes *and names the changed files*, scoping the re-reading to
those, when something has; and starts fresh past the staleness window — injecting
`pad.summary()` instead of the stale transcript. That summary leads with conclusions and puts
detail below, because an aggregated input is read most reliably at its beginning. `fork` takes
one analysis baseline into two branches, so comparing two refactors does not pay for the
mapping phase twice or let the first colour the second.

**The plan is expected to change.** `plan.py` is map → rank → work, where the work items are
generated from what the ranking exposed and re-ordered as dependencies surface. A fixed pipeline
is right when the steps are known in advance; "add tests to this legacy package" is the case
where step three depends on what step one found.

## MCP

`mcp.example.json` is project scope: committed, so the team shares the servers, with credentials
referenced as `${GITHUB_TOKEN}` and living only in the environment. Personal and experimental
servers belong in user scope (`~/.claude.json`), so a half-working server is one person's
problem. A server whose variable does not resolve costs its tools rather than the run — quietly,
which is worse than loudly — so `missing_credentials()` names them at startup.

One naming trap, live in the code: the subagent tool was renamed `Task` → `Agent`. `"Agent"` is
what goes in `allowed_tools`, but `is_delegation()` matches **both**, because `system:init` and
permission denials still say `Task`.

## Layout

| File | Holds |
|---|---|
| `prompts.py` | tool-selection discipline, delegation rules, the self-contained subagent prompt |
| `agents.py` | the `explore` subagent definition |
| `scratchpad.py` | findings file, manifest, and the injected summary |
| `session.py` | resume / resume-with-changes / fresh, and forking |
| `plan.py` | adaptive decomposition with dependencies and re-ranking |
| `mcp_config.py` | `.mcp.json` loading, `${VAR}` expansion, missing-credential reporting |
| `explorer.py` | `ClaudeAgentOptions` wiring and the run loop |
