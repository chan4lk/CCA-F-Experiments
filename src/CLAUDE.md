# src/

All **new** Python code in this repository lives here — modules, packages, and new agent
projects alike. See `.claude/rules/repository-layout.md` for the full rules, including the
fixed paths (`plugins/`, `.claude/`, `.github/`) that are exempt and the existing root-level
scripts that stay where they are.

A new agent project keeps the shape the existing three use, one level down:

```text
src/<agent-name>/
  <agent_package>/
  tests/
  conftest.py      puts src/<agent-name>/ on sys.path — nothing is pip-installed
  pytest.ini
  README.md
```

Its tests run from its own directory: `cd src/<agent-name> && pytest`.
