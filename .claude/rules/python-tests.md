---
description: Test conventions for this repo's pytest suites
paths:
  - "**/tests/**/*.py"
  - "**/test_*.py"
  - "**/conftest.py"
  - "**/pytest.ini"
---

# Test conventions

Path-scoped: this file loads only when a test file, a `conftest.py`, or a `pytest.ini` is in
play. Test conventions apply to files scattered across seven directories, which is exactly the
case a glob rule handles and a directory-level `CLAUDE.md` does not.

## Where tests run from

Nothing is pip-installed. Each package's `conftest.py` puts its own directory on `sys.path`,
so a suite runs **from its own directory** and nowhere else:

```bash
cd research-agent && pytest
cd src/extraction && uv run --project ../.. pytest
pytest plugins/proposal-research/tests/ -v      # from the repo root
```

Running `pytest` at the repo root collects nothing useful and fails on imports.

## Settings every suite inherits

- `asyncio_mode = strict` — an async test without `@pytest.mark.asyncio` is silently skipped,
  so every async test carries the marker.
- `filterwarnings = error::DeprecationWarning` — a new deprecation warning fails the suite.
  Do not add a blanket `ignore`; fix the call or scope the filter to the one warning.

## What a test here is for

Most of these suites exist to defend an invariant, not to reach a coverage number. Prefer:

- **Assert the mechanism, not the outcome the model happened to produce.** A gate test proves
  the call was *denied*; a test that the model chose not to make the call proves nothing.
- **One behaviour per test, named as the behaviour.** `test_absent_information_is_not_retried`
  beats `test_extract_3`.
- **No network.** Inject a fake client. Every suite in this repo runs with no API key set.
- **Fixtures build a valid object and override one field** — the diff between the fixture and
  the case is the thing under test.

## Vendored code

`ledger/`, `gate/verify.py`, `vault/build.py` and `ingest.py` are copies in each of the three
Python pipeline packages, and so are their tests. A fix in one is not a fix in the others. When
changing shared-looking test code, say which of the four you are changing.
