# Repository layout rules

These govern **where new code is created**. They are not a migration order — see
"Existing code stays put" below.

## 1. New Python files go in `src/`

Any new `.py` file is created under `src/`, never at the repository root.

```text
src/<module>.py              ✅
src/<package>/<module>.py    ✅
<module>.py                  ❌  root is closed to new Python files
```

The repository root already holds a set of single-concept demo scripts. That set is closed.
A new demo, script, or utility goes in `src/` — either as a top-level module or inside a
package, whichever matches its size.

## 2. New agent projects go in `src/` too

An agent project is a self-contained directory with its own package, `pytest.ini`,
`conftest.py`, and `README.md` — the shape of `research-agent/`,
`research_agent_batch/`, and `research_agent_batch_server_tools/`.

New ones are created **inside** `src/`, keeping that whole shape:

```text
src/<agent-name>/
  <agent_package>/       the importable package (underscores)
  tests/
  conftest.py            puts src/<agent-name>/ on sys.path
  pytest.ini
  README.md              opens with the trade this variant makes
```

Run its tests from its own directory (`cd src/<agent-name> && pytest`), exactly as the
existing three do. Nothing here is pip-installed; `conftest.py` is what makes imports work.

## 3. Exceptions — paths fixed by something outside this repo

Do **not** move these into `src/`; a hard-coded path elsewhere resolves to them:

| Path | Fixed by |
|---|---|
| `plugins/**` | `.claude-plugin/marketplace.json` (`"source": "./plugins/proposal-research"`) and each plugin's own `hooks.json`, which reference hook and script paths relative to the plugin root |
| `.claude/**` | Claude Code |
| `.github/workflows/**` | GitHub Actions |
| `conftest.py`, `pytest.ini` | pytest — they sit at the root of the tree they configure |

A new Claude Code **plugin** therefore goes in `plugins/<name>/`, and its Python hooks and
scripts stay inside it. `src/` is for Python projects, not for plugins.

## 4. Existing code stays put

`main.py`, `agent-loop.py`, `coordinator.py`, `cache.py`, `prefil.py`, `batch.py`,
`transcript.py`, `message_handler.py`, `subagent_tracker.py`, and the three
`research*` directories remain where they are. Relocating them would break
`coordinator.py`'s sibling imports, every `conftest.py` path assumption, and the READMEs'
relative cross-links — for no gain.

Move one only when the user asks for that move specifically. Never as a side effect of
another task.
