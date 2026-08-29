# Known defects — proposal-research plugin

Found during a full Phase 0–6b run on 2026-08-29 (session `16829a3e-1678-468f-a260-ac82bbbf6b47`,
question: *"AML system architecture for sri lankan banks with enterprise deployments which uses AI agents"*).

Every defect below was observed in that run, not inferred from reading the code. Each entry records
what actually happened, what it cost, and what a fix would look like.

**Status summary: 1 of 5 fixed, uncommitted.**

| # | Defect | Severity | Status |
|---|---|---|---|
| 1 | Validators cannot read PDFs | Critical | **Fixed in source, uncommitted** |
| 2 | `curl` is invisible to the provenance hook | Critical | Not fixed |
| 3 | `web.archive.org` is unreachable to WebFetch | Moderate | Not fixed (harness limit) |
| 4 | `validator-tool-restrictions` check never fires | High | Not fixed |
| 5 | WebFetch's 10 MB ceiling silently drops large PDFs | Moderate | Not fixed (harness limit) |

Defects 1 and 2 compound each other: the workaround for 1 (read PDFs with `curl`) triggers 2
(retrievals become invisible), and the workaround for 2 (call WebFetch first anyway) is defeated by 1
(WebFetch cannot decode the PDF). Together they were the single largest source of lost work in the run.

---

## 1. Validators cannot read PDFs — **fixed in source, uncommitted**

**What happens.** `agents/validator.md` grants only `WebFetch` and `microsoft_docs_fetch`. WebFetch
cannot extract text from a PDF binary, so a validator sent to a PDF-hosted claim returns `NOT_FOUND`
regardless of whether the claim is true. The gate then requires every verdict on a material claim to
be `CONFIRMED`, so the claim is excluded.

**How it manifested.** 93 of 162 claims (57%) at the point of discovery cited PDFs — and PDFs are
where primary law lives. Sub-question coverage would have been:

| Sub-question | PDF-sourced | Citable without the fix |
|---|---:|---:|
| Q1 — FTRA / STR / CTR / EFT thresholds | 16 of 16 | 0 |
| Q4 — Data residency (PDPA, CBSL Directions) | 14 of 15 | 1 |
| Q2 — FIU TBML red flags | 7 of 8 | 1 |
| Q5 — TBML data requirements | 13 of 20 | 7 |
| Q10 / Q11 — AI governance and failure modes | 30 of 40 | 10 |

Nine claims were recorded `NOT_FOUND` before the cause was understood (C020–C026, C123, C124).
Because the ledger is append-only, those claims were permanently disqualified from the pack body;
the seven FIU TBML red flags had to be re-researched under fresh ids (C028–C037) to be recoverable.

**Fix applied.** `agents/validator.md` now grants `Bash`, with a mandatory WebFetch-first step (so
provenance is still logged) and an explicit prohibition on reading anything under `research/`, opening
scratchpad or temp files, using WebSearch, or fetching any URL other than the cited one.

**Caveat on this fix — it weakens a guarantee.** Validator blindness was previously enforced by *tool
restriction*: no Bash meant no possible path to the researcher's quote or the ledger. It is now
enforced by *instruction*. That held for this run — a manual audit of all 531 logged retrievals found
zero WebSearch calls by any validator agent — but it is a weaker property than the plugin originally
had, and it is worth revisiting if a tool-level alternative becomes available.

**Note on propagation.** Agent definitions load at session start, so the change did not take effect in
the session that made it; the run completed using a Bash-capable read-only agent type as a stand-in
validator. The edit was applied to both the repo source and the installed cache under
`~/.claude/plugins/cache/ccaf/proposal-research/0.1.0/`; **only the repo copy is durable** — a plugin
reinstall will overwrite the cache.

---

## 2. `curl` is invisible to the provenance hook — **not fixed**

**What happens.** `hooks/hooks.json` registers `record_fetch.py` on
`PostToolUse` with matcher `WebFetch|WebSearch|mcp__microsoft_docs_mcp__.*`. Any retrieval performed
through `Bash` — `curl`, `wget` — is never logged. Agents reach for `curl` precisely when WebFetch
fails, which is exactly when the page is a PDF (see defect 1), so the two defects reinforce each other.

**How it manifested, twice.**

- *Researchers.* 39 claims cited URLs that appeared nowhere in `fetch-log.jsonl`, because the
  researcher had retrieved them with `curl` + `pdftotext`. These were not fabricated citations — the
  pages were real and had been read — but the gate cannot tell the difference. A targeted re-fetch
  pass recovered 22; 17 were unrecoverable and excluded.
- *Validators.* 28 verdicts later failed the `validator-blindness` check for the same reason: the
  validator had read its document via `curl` and skipped the mandatory WebFetch call, so it could not
  be proven to have opened the page it ruled on. This caused the first gate failure. Repair required
  resuming six validator agents and asking each to perform the WebFetch it had been instructed to
  perform. Every verdict held unchanged on re-reading, confirming the independence property was intact
  in substance and only the *proof* was missing.

**Also observed.** Failed WebFetch attempts are correctly *not* logged (PostToolUse does not fire on
tool error), so provenance stays honest — an unreachable page cannot masquerade as a retrieved one.
That behaviour is right and should be preserved by any fix.

**Possible fixes.**

- Extend the `PostToolUse` matcher to include `Bash` and parse URLs out of `curl`/`wget` invocations
  in `record_fetch.py`. Catches the common case; will not catch a URL built in a variable.
- Or invert the failure: have researchers and validators fail *fast* rather than at the gate — e.g. a
  check that warns as soon as a claim is appended whose URL has no logged retrieval, so the researcher
  can re-fetch while still in context, instead of the orchestrator discovering it an hour later.

---

## 3. `web.archive.org` is unreachable to WebFetch — **not fixed (harness limit)**

**What happens.** WebFetch refuses the host outright: `Claude Code is unable to fetch from
web.archive.org`. This is a client-side restriction, distinct from a target site blocking the request.

**How it manifested.** Researchers used Wayback mirrors as a sensible workaround when FATF's and
Finacle's own sites were Cloudflare/Akamai-blocked. But no validator could ever re-fetch those URLs,
so the claims could never be dual-confirmed. 11 claims were permanently excluded on this ground:
C080–C086 and C097, C098 (FATF's TBML *Trends and Developments* and *Risk Indicators* reports) and
C165, C166 (Finacle API Connect). The FATF TBML methodology is core subject matter for a TBML
proposal; losing it materially thinned that section.

**Mitigation available in-plugin.** `agents/researcher.md` should state plainly that a
`web.archive.org` URL can never be validated and must not be recorded as a claim's `url` — if a live
source cannot be reached, report the gap instead. This run had to inject that instruction by hand into
round-2 researcher prompts.

---

## 4. `validator-tool-restrictions` check never fires — **not fixed**

**What happens.** `scripts/verify_pack.py` line 276:

```python
if row.get("agent_type") == "validator" and row.get("tool") == "WebSearch":
```

`record_fetch.py` writes the *namespaced* agent type, so the log contains
`proposal-research:validator`, never bare `validator`. The equality never holds. The check that
enforces "validators must not search" — described in the skill as protecting against a validator
shopping for a friendlier source — is dead code and has presumably never fired.

**How it manifested.** Silently. Nothing failed; the property simply went unverified. It was found by
reading the check, not by it firing. The run compensated with a manual audit across all 531 logged
retrievals, which found zero WebSearch calls by any validator agent — so the property did hold, by
luck and prompt discipline rather than by enforcement.

**Fix.** One line:

```python
if str(row.get("agent_type") or "").endswith("validator") and row.get("tool") == "WebSearch":
```

Worth auditing the other checks for the same bare-vs-namespaced assumption.

---

## 5. WebFetch's 10 MB ceiling silently drops large PDFs — **not fixed (harness limit)**

**What happens.** WebFetch returns `maxContentLength size of 10485760 exceeded` and no content. The
document is real and reachable; it is simply too large. Since the retrieval fails, nothing is logged
(correctly — see defect 2), so the claim has no provenance and no validator can ever confirm it.

**How it manifested.** The OWASP *Top 10 for LLM Applications 2025* PDF exceeded the limit, excluding
6 claims (C208–C213) covering indirect prompt injection and Excessive Agency. For a proposal about AI
agents reading attacker-supplied trade documents, that is directly on-point material. The underlying
Greshake et al. paper (arXiv) was reachable and carried the prompt-injection point, so the section
survived — but by luck of having a second source, not by design.

**Mitigation available in-plugin.** `agents/researcher.md` should warn that very large PDFs will fail
and that an HTML version or an alternative primary source should be preferred where one exists.

---

## Suggested order of work

1. **Defect 4** — one line, restores a dead integrity check. Highest value per unit of effort.
2. **Defect 2** — deepest and most costly; needs a design decision between logging Bash retrievals and
   failing fast at claim-append time.
3. **Defects 3 and 5** — not fixable in code, but both cost claims in this run and both are cheap to
   mitigate with explicit guidance in `agents/researcher.md`.
4. **Defect 1** — already fixed; commit it, and revisit whether tool-enforced blindness can be
   restored rather than left to instruction.
