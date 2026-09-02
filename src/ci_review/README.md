# ci_review — Claude Code in CI

> Backlog item 2 of `docs/backlog/2026-09-02-ccar-f-scenarios.md`.
> CCAR-F Scenario 5. Domains 3 (Claude Code Configuration & Workflows) and 4 (Prompt
> Engineering & Structured Output).

**The trade:** the reviewer is a subprocess, not a library. `claude -p` gives up in-process
control and gains the whole Claude Code harness — file tools, project `CLAUDE.md`, the model's
own exploration of the repo — for the cost of a JSON envelope on stdout. The Python here does
three things the subprocess cannot: decide what a finding is, decide what has already been
said, and turn the rest into a PR review.

## Run

```bash
cd src/ci_review
uv run --project ../.. pytest                    # 50 tests, no CLI, no network

PYTHONPATH=ci_review uv run --project ../.. python -m ci_review review --base origin/main
PYTHONPATH=ci_review uv run --project ../.. python -m ci_review tests src/orders.py tests/test_orders.py
```

`CI_REVIEW_MODEL` (default `claude-haiku-4-5`), `CI_REVIEW_BUDGET_USD` and
`CI_REVIEW_TIMEOUT` override the pinned settings.

In CI: `.github/workflows/claude-review.yml`, on every push to a PR.

## The four decisions

**`-p`, and structured output.** `-p` is what stops the CLI waiting on a tty and hanging the
job — an interactive prompt in CI is a twenty-minute timeout, not an error. `--output-format
json` wraps the run in an envelope carrying cost and session id; `--json-schema` constrains
what lands in its `result`, so findings arrive as objects with a file and a line and go
straight into `gh api` as inline comments. Nothing parses prose. The reviewer runs read-only
(`--allowed-tools Read Grep Glob`) and under `--max-budget-usd`: it reports, it does not edit,
and it cannot run away with the bill.

**Criteria, not confidence.** "Be conservative" and "only report high-confidence findings" ask
the model to filter on a feeling, and it filters inconsistently. `criteria.py` instead names
six reportable categories and six explicitly-not-reportable ones, defines each severity with a
concrete code example, and shows six boundary pairs — the f-string `execute` and the
parameterised one, the `sum/len` and the guarded `sum/len`. Pairs generalise where prose does
not: the model applies the distinction to constructs the list never mentions. Every finding
must also carry a `failure_input`; a finding that cannot name the input it breaks on is a
guess, and the schema makes it impossible to submit one.

**The same session cannot review itself.** Each pass is a fresh process. An instance that just
wrote the code carries the reasoning that produced it and is measurably less likely to question
it, so the reviewer arrives with only the diff. Passes are also split: one per file for local
defects, then one over the full diff for the cross-file ones — a changed signature whose callers
were not updated, a data shape consumed elsewhere. A single prompt spanning twenty files dilutes
attention across all of them and produces findings that contradict each other; the integration
pass is the thing per-file passes structurally cannot do.

**Nothing gets said twice.** Findings already posted on the PR are read back from the API and
fed into the prompt with an instruction not to repeat them. That instruction has a non-zero
failure rate and the cost of it failing is a duplicate comment on someone's PR, so `dedupe.py`
fingerprints on `(file, category, detected_pattern)` — deliberately not line number, so a
finding does not resurrect when the code above it shifts — and filters deterministically.
Test proposals get the same treatment from the other direction: the existing suite goes into
the prompt and every proposal must name the branch it does not reach.

**`detected_pattern` is the feedback loop.** Every finding carries a slug for the construct
that triggered it, rendered into the comment. Grouped by slug against dismissals, that is what
identifies a category producing false positives — the exam's point being that the fix for a
high-false-positive category is to disable it and rewrite it, not to keep asking the same
prompt to be more careful.

## Layout

| File | Holds |
|---|---|
| `criteria.py` | report/skip categories, severity definitions, boundary examples |
| `schema.py` | the findings and test-proposal output schemas |
| `prompts.py` | system prompt, per-file pass, integration pass, test pass |
| `runner.py` | CLI command construction, subprocess, envelope parsing |
| `review.py` | the pass sequence and git plumbing |
| `dedupe.py` | fingerprinting, and pattern frequency for dismissal analysis |
| `comment.py` | findings → a single GitHub review payload |
