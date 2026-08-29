# Changelog

## 0.2.0

Everything here came out of the first real run — a Phase 0–6b research pass on AML system
architecture for Sri Lankan banks, 277 claims, gate PASS. Five defects were found by running
it, not by reading it, and two more surfaced while fixing those.

### Breaking

- **The gate no longer exempts blockquotes.** A pack could assert a tool cap, a price and an
  availability date entirely inside `> ` and return `GATE: PASS`. Quoted prose, quoted bullets
  and quoted table rows are each units now. Packs that passed under 0.1.0 may fail.
- **`raw_hash` is validated.** It must be the hex hash `headroom_compress` returned, or be
  omitted. A run recorded the literal string `"n/a"` nine times because nothing checked it.
- **The validator holds `Bash`.** 57% of that run's claims cited PDFs — primary law lives in
  PDFs — and WebFetch cannot decode one, so validators returned `NOT_FOUND` regardless of
  whether the claim was true.

### Fixed

- **Two integrity checks were dead code.** Claude Code namespaces plugin agents, so the fetch
  log holds `proposal-research:validator` while both checks compared against bare `validator`.
  Neither had ever fired. One affected `--infer-agent-from`, the path the skill tells the
  orchestrator to use, which therefore always refused.
- **Validator blindness is mechanical again.** Granting `Bash` reopened the hole that removing
  `Read` had closed — `cat claims.jsonl` is a read. A `PreToolUse` guard now blocks a
  validator from reaching `research/` or searching. Researchers and the main session are
  unaffected.
- **Claims warn about missing provenance at append time**, while the researcher still has the
  page, instead of the orchestrator discovering it an hour later at the gate. A run lost 17
  claims that way, to pages read with `curl` that the hook cannot see.
- **`researcher.md` warns off sources no validator can re-fetch** — `web.archive.org`, which
  WebFetch refuses outright, and PDFs over its 10 MB ceiling. Those cost that run 28 claims.

### Added

- `add_verdict --batch` records many verdicts in one call.
- `context_guard.py` samples the orchestrator's live context, warns when a single turn adds
  more than 15K tokens, and writes `context-log.jsonl`; the gate reports the curve in
  `verify-report.md`.
- Narration discipline in `SKILL.md`, aimed at what the measurement showed: of ~600K of
  context growth, tool results were only ~104K and the rest was the orchestrator's own prose.

### Retracted

- **The design spec's claim that `raw_hash` provides an audit trail was false.** It said the
  hash lets the human gate retrieve the original page weeks later. Headroom's store is
  session-scoped: 232 claims carried a hash, retrieval afterwards returns "Content not found",
  and `headroom memory stats` reports `Total Memories: 0`.
- **Batching verdicts was not the token lever it was billed as.** The orchestrator called
  `add_verdict` three times in the whole run, not once per verdict as the usage summary
  implied. `--batch` is still right; it is not where the cost was.

### Known limits

`context_guard` measures, it does not enforce — the orchestrator's prose is not a tool call,
so nothing can deny it the way `validator_guard` denies a Bash command. Expected effect on a
same-scope re-run is ~240M tokens against 279M. Scope remains the larger lever: one gap round
instead of two is worth more than every change in this release combined.

## 0.1.0

Initial release. Six subagents communicating through append-only claim ledgers, hook-recorded
fetch provenance, and a blocking gate that proves every material claim traces to a page
retrieved during the run.
