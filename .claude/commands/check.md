---
description: Run every test suite and the linter, from the right directory for each
argument-hint: "[suite name, or blank for all]"
allowed-tools: Bash, Read
---

Run the repo's checks. Each suite runs from its own directory — `conftest.py` is what puts
that directory on `sys.path`, so running from anywhere else fails on imports.

Argument: `$ARGUMENTS` — a suite name to run just that one, or empty to run all.

Suites:

| Name | Command |
|---|---|
| `extraction` | `cd src/extraction && uv run --project ../.. pytest -q` |
| `ci_review` | `cd src/ci_review && uv run --project ../.. pytest -q` |
| `research-agent` | `cd research-agent && pytest -q` |
| `batch` | `cd research_agent_batch && pytest -q` |
| `server-tools` | `cd research_agent_batch_server_tools && pytest -q` |
| `plugin` | `pytest plugins/proposal-research/tests/ -q` (from the repo root) |

Then lint: `uvx ruff check src/`.

Report the pass/fail count per suite in a table. If a suite fails, show the failing test names
and the assertion — not the full traceback. Do not fix anything; this command reports.
