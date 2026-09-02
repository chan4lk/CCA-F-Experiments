---
description: Scaffold a new single-concept demo or agent project under src/, per the layout rules
argument-hint: "<name> — what the demo isolates, e.g. 'streaming' or 'tool-search'"
allowed-tools: Read, Write, Edit, Bash, Glob
---

Scaffold a new piece of code under `src/`. Name/purpose: `$ARGUMENTS`

Before writing anything, read `.claude/rules/repository-layout.md`. The root is closed to new
Python files; this goes in `src/` either way.

Decide which shape fits and say which you chose and why:

- **A single module** (`src/<name>.py`) when it isolates one API feature and fits in one file,
  like the root-level demos it sits alongside.
- **A package** (`src/<name>/<name>/…`) with `tests/`, `conftest.py`, `pytest.ini` and a
  `README.md` when it has more than one concern. Copy the shape of `src/extraction/`.

Then:

1. Write the code. Minimal comments — a comment earns its place by explaining *why*, never by
   restating the line below it.
2. If it is a package, the `README.md` opens with the trade this variant makes, the way the
   existing pipeline READMEs do.
3. Tests run with no network and no API key: inject a fake client.
4. Run `uvx ruff check src/<name>` and the new suite before reporting done.

Do not touch anything outside `src/<name>/` unless I ask.
