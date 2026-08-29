# Proposal Research Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that researches a product/solution proposal question across the web and emits a cited evidence pack, a draft proposal, and a self-contained Obsidian vault, where every material claim is mechanically traceable to a page provably retrieved during the run.

**Architecture:** Six subagents (planner, researcher, validator, gap-hunter, synthesizer, proposal-writer) communicate through append-only JSONL ledgers on disk rather than through the orchestrator's context. Two `PostToolUse` hooks enforce the ledger's shape and record every fetch with its originating `agent_id`. A blocking `verify_pack.py` gate proves citation provenance and validator blindness before any proposal is drafted. Deterministic Python scripts handle ingestion and vault generation; models write prose only.

**Tech Stack:** Python 3.12 standard library only. pytest for tests. Claude Code plugin format (`.claude-plugin/plugin.json`, `agents/`, `skills/`, `commands/`, `hooks/`). Headroom MCP for in-agent compression. `microsoft_docs_mcp` for first-party Microsoft documentation.

**Spec:** `docs/superpowers/specs/2026-08-29-proposal-research-plugin-design.md`

## Global Constraints

- **Stdlib only.** Plugin scripts and hooks MUST NOT import third-party packages. Hooks execute via bare `python3` (system Python 3.12.6), outside this repo's `.venv`. No `yaml`, no `pydantic`, no `requests`.
- **Test runner:** `python3 -m pytest` — the system interpreter, which has pytest 9.0.3. `.venv/bin/python` has no pytest; do not use it.
- **Test location:** `plugins/proposal-research/tests/`.
- **Plugin root:** `plugins/proposal-research/`. All paths below are relative to the repo root `/Users/chandima/repos/CCAF`.
- **Claim ID format:** `C` followed by at least 3 digits, zero-padded — `C012`. Regex: `C\d{3,}`.
- **Verdicts (exact strings):** `CONFIRMED`, `CONTRADICTED`, `NOT_FOUND`, `MISLEADING`, `INTERNAL_UNVERIFIED`.
- **Tiers (exact strings):** `material`, `context`.
- **Source types (exact strings):** `vendor_doc`, `regulator`, `analyst`, `blog`, `forum`, `internal`.
- **Staleness threshold:** 90 days for carried-forward claims.
- **Ingestion budget:** 25 notes default.
- **Gap loop:** maximum 2 rounds.
- **Model per role, passed at dispatch time** (never agent-file frontmatter): planner `sonnet`, researcher `sonnet`, validator `haiku` (escalation pass `sonnet`), gap-hunter `opus`, synthesizer `fable`, proposal-writer `fable`.
- **Reference vault** for all Obsidian output shape: `/Users/chandima/Downloads/Claude Architect Exam`.
- **Timestamps:** ISO 8601 UTC with `Z` suffix, second precision — `2026-08-29T09:41:00Z`.

---

### Task 1: Plugin scaffold and shared workspace module

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `plugins/proposal-research/.claude-plugin/plugin.json`
- Create: `plugins/proposal-research/README.md`
- Create: `plugins/proposal-research/scripts/workspace.py`
- Create: `plugins/proposal-research/tests/test_workspace.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces:
  - `workspace.slugify(text: str) -> str`
  - `workspace.workspace_root(cwd: Path, slug: str) -> Path`
  - `workspace.ensure_workspace(root: Path) -> Path`
  - `workspace.append_jsonl(path: Path, row: dict) -> None`
  - `workspace.read_jsonl(path: Path) -> list[dict]`
  - `workspace.utc_now() -> str` (ISO 8601 `Z`)
  - `workspace.CLAIM_ID_RE`, `workspace.VERDICTS`, `workspace.TIERS`, `workspace.SOURCE_TYPES`

- [ ] **Step 1: Write the failing test**

Create `plugins/proposal-research/tests/test_workspace.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import workspace  # noqa: E402


def test_slugify_lowercases_and_hyphenates():
    assert workspace.slugify("ServiceNow Agent vs Copilot Studio!") == "servicenow-agent-vs-copilot-studio"


def test_slugify_collapses_runs_and_trims():
    assert workspace.slugify("  AML   solutions -- for  banks  ") == "aml-solutions-for-banks"


def test_slugify_truncates_to_60_chars():
    assert len(workspace.slugify("word " * 40)) <= 60


def test_workspace_root_is_research_slug_under_cwd(tmp_path):
    root = workspace.workspace_root(tmp_path, "my-slug")
    assert root == tmp_path / "research" / "my-slug"


def test_ensure_workspace_creates_directory(tmp_path):
    root = workspace.ensure_workspace(tmp_path / "research" / "s")
    assert root.is_dir()


def test_append_and_read_jsonl_roundtrip(tmp_path):
    p = tmp_path / "claims.jsonl"
    workspace.append_jsonl(p, {"id": "C001", "claim": "a"})
    workspace.append_jsonl(p, {"id": "C002", "claim": "b"})
    rows = workspace.read_jsonl(p)
    assert [r["id"] for r in rows] == ["C001", "C002"]


def test_append_jsonl_creates_parent_directories(tmp_path):
    p = tmp_path / "deep" / "nested" / "claims.jsonl"
    workspace.append_jsonl(p, {"id": "C001"})
    assert p.is_file()


def test_read_jsonl_skips_blank_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "C001"}\n\n{"id": "C002"}\n')
    assert len(workspace.read_jsonl(p)) == 2


def test_read_jsonl_missing_file_returns_empty(tmp_path):
    assert workspace.read_jsonl(tmp_path / "nope.jsonl") == []


def test_read_jsonl_raises_on_malformed_line(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "C001"}\nNOT JSON\n')
    try:
        workspace.read_jsonl(p)
    except ValueError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_utc_now_is_iso_z():
    v = workspace.utc_now()
    assert v.endswith("Z") and "T" in v and len(v) == 20


def test_constants_match_spec():
    assert workspace.VERDICTS == {
        "CONFIRMED", "CONTRADICTED", "NOT_FOUND", "MISLEADING", "INTERNAL_UNVERIFIED",
    }
    assert workspace.TIERS == {"material", "context"}
    assert workspace.SOURCE_TYPES == {
        "vendor_doc", "regulator", "analyst", "blog", "forum", "internal",
    }


def test_claim_id_regex_matches_padded_ids():
    assert workspace.CLAIM_ID_RE.fullmatch("C012")
    assert workspace.CLAIM_ID_RE.fullmatch("C1234")
    assert not workspace.CLAIM_ID_RE.fullmatch("C12")
    assert not workspace.CLAIM_ID_RE.fullmatch("X012")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_workspace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'workspace'`

- [ ] **Step 3: Write minimal implementation**

Create `plugins/proposal-research/scripts/workspace.py`:

```python
"""Shared workspace helpers for the proposal-research plugin.

Stdlib only: hooks run under bare `python3`, outside any project venv.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

CLAIM_ID_RE = re.compile(r"C\d{3,}")

VERDICTS = {
    "CONFIRMED",
    "CONTRADICTED",
    "NOT_FOUND",
    "MISLEADING",
    "INTERNAL_UNVERIFIED",
}
TIERS = {"material", "context"}
SOURCE_TYPES = {
    "vendor_doc",
    "regulator",
    "analyst",
    "blog",
    "forum",
    "internal",
}

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, hyphen-separated, <=60 chars, no leading/trailing hyphen."""
    s = _SLUG_STRIP.sub("-", text.lower()).strip("-")
    if len(s) <= 60:
        return s
    return s[:60].rstrip("-")


def workspace_root(cwd: Path, slug: str) -> Path:
    return Path(cwd) / "research" / slug


def ensure_workspace(root: Path) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: malformed JSON at line {lineno}: {exc}") from exc
    return rows


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chandima/repos/CCAF && python3 -m pytest plugins/proposal-research/tests/test_workspace.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Create the plugin manifest and marketplace entry**

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "ccaf",
  "owner": {
    "name": "Chandima Ranaweera",
    "url": "https://github.com/chan4lk"
  },
  "description": "Claude Code plugins from the CCAF experiments repo.",
  "plugins": [
    {
      "name": "proposal-research",
      "source": "./plugins/proposal-research",
      "version": "0.1.0",
      "description": "Multi-agent web research for product proposals. Emits a cited evidence pack, a draft proposal, and a self-contained Obsidian vault, with every material claim provably traced to a retrieved page.",
      "author": { "name": "Chandima Ranaweera" },
      "license": "MIT"
    }
  ]
}
```

Create `plugins/proposal-research/.claude-plugin/plugin.json`:

```json
{
  "name": "proposal-research",
  "displayName": "Proposal Research",
  "version": "0.1.0",
  "description": "Multi-agent web research for product and solution proposals. Six subagents communicate through append-only claim ledgers; two PostToolUse hooks record every fetch with its originating agent_id; a blocking gate proves citation provenance and validator blindness before a proposal is drafted. Emits a self-contained Obsidian vault per run.",
  "author": { "name": "Chandima Ranaweera" },
  "license": "MIT",
  "keywords": [
    "research", "proposal", "citations", "provenance",
    "obsidian", "multi-agent", "anti-hallucination"
  ]
}
```

- [ ] **Step 6: Write the README**

Create `plugins/proposal-research/README.md`:

```markdown
# Proposal Research

Multi-agent web research for product and solution proposals.

## Why

Proposal research fails two ways: it states things that are not true, and it
misses details that were findable. The damaging false claims are rarely
invented — they are *technically true and materially wrong*: preview-only,
region-locked, licence-gated, deprecated last quarter.

This plugin makes the guarantee structural rather than exhortative. Prompts
saying "do not hallucinate" are not the mechanism. These are:

- Researchers append claims to `claims.jsonl` with a **verbatim quote**. A row
  without one is rejected by a hook before it lands.
- Validators are **blind by tool restriction** — no `Read`, no `WebSearch` — so
  they cannot open the ledger and cannot shop for a friendlier source.
- The synthesizer has **no web tools**, so it cannot introduce a fact absent
  from the ledger.
- A blocking gate proves every cited URL was actually retrieved this session,
  by the validator that ruled on it.

## Usage

    /proposal-research:research "ServiceNow agent via Copilot Studio + MCP vs native AI Agents"
    /proposal-research:draft      # after approving the evidence pack
    /proposal-research:verify     # re-run the gate standalone

Output lands in `research/<slug>/`, including a self-contained Obsidian vault
at `research/<slug>/vault/`.

## Requirements

- Python 3.12+ on PATH as `python3` (stdlib only — no packages to install)
- Optional: `microsoft_docs_mcp` for first-party Microsoft documentation
- Optional: `headroom` MCP for in-agent compression
```

- [ ] **Step 7: Verify the manifests are valid JSON**

Run:
```bash
cd /Users/chandima/repos/CCAF
python3 -c "import json;[json.load(open(p)) for p in ['.claude-plugin/marketplace.json','plugins/proposal-research/.claude-plugin/plugin.json']];print('manifests OK')"
```
Expected: `manifests OK`

- [ ] **Step 8: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add .claude-plugin plugins/proposal-research
git commit -m "feat(proposal-research): plugin scaffold and shared workspace module"
```

---
### Task 2: Ledger append CLIs (`add_claim.py`, `add_verdict.py`)

> **Deviation from spec, deliberate.** The spec has researchers writing `claims.jsonl`
> directly with a `PostToolUse` lint. Two problems: N parallel researchers using the `Write`
> tool on one file clobber each other, and `PostToolUse` fires *after* the row has landed, so
> "rejected before it lands" is unachievable on that event. Both are fixed by routing appends
> through a CLI that validates and performs a single atomic `O_APPEND` write of one line
> (atomic under POSIX for writes below `PIPE_BUF`). The hook in Task 3 then *denies* direct
> writes to the ledger and points the agent here. Same guarantee, concurrency-safe, and the
> validation is deterministic rather than hook-timing-dependent.

**Files:**
- Create: `plugins/proposal-research/scripts/add_claim.py`
- Create: `plugins/proposal-research/scripts/add_verdict.py`
- Create: `plugins/proposal-research/tests/test_add_claim.py`
- Create: `plugins/proposal-research/tests/test_add_verdict.py`

**Interfaces:**
- Consumes: `workspace.append_jsonl`, `workspace.read_jsonl`, `workspace.utc_now`, `workspace.CLAIM_ID_RE`, `workspace.TIERS`, `workspace.SOURCE_TYPES`, `workspace.VERDICTS` (Task 1)
- Produces:
  - `add_claim.validate_claim(row: dict, existing_ids: set[str]) -> list[str]` (returns error strings; empty means valid)
  - `add_claim.main(argv: list[str]) -> int` — CLI `add_claim.py --workspace DIR --json '{...}'`
  - `add_verdict.validate_verdict(row: dict) -> list[str]`
  - `add_verdict.main(argv: list[str]) -> int` — CLI `add_verdict.py --workspace DIR --json '{...}'`

- [ ] **Step 1: Write the failing test for claims**

Create `plugins/proposal-research/tests/test_add_claim.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import add_claim  # noqa: E402

VALID = {
    "id": "C001",
    "sub_q": "Q1",
    "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": "https://learn.microsoft.com/example",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc",
}


def test_valid_claim_has_no_errors():
    assert add_claim.validate_claim(dict(VALID), set()) == []


def test_missing_quote_is_rejected():
    row = dict(VALID)
    del row["quote"]
    errors = add_claim.validate_claim(row, set())
    assert any("quote" in e for e in errors)


def test_empty_quote_is_rejected():
    row = dict(VALID, quote="   ")
    assert any("quote" in e for e in add_claim.validate_claim(row, set()))


def test_quote_over_fifty_words_is_rejected():
    row = dict(VALID, quote=" ".join(["word"] * 51))
    assert any("50 words" in e for e in add_claim.validate_claim(row, set()))


def test_quote_of_exactly_fifty_words_is_accepted():
    row = dict(VALID, quote=" ".join(["word"] * 50))
    assert add_claim.validate_claim(row, set()) == []


def test_bad_claim_id_is_rejected():
    assert any("id" in e for e in add_claim.validate_claim(dict(VALID, id="C1"), set()))


def test_duplicate_id_is_rejected():
    errors = add_claim.validate_claim(dict(VALID), {"C001"})
    assert any("duplicate" in e.lower() for e in errors)


def test_bad_tier_is_rejected():
    assert any("tier" in e for e in add_claim.validate_claim(dict(VALID, tier="high"), set()))


def test_non_http_url_is_rejected():
    assert any("url" in e for e in add_claim.validate_claim(dict(VALID, url="file:///etc/passwd"), set()))


def test_internal_source_type_is_rejected_from_public_ledger():
    errors = add_claim.validate_claim(dict(VALID, source_type="internal"), set())
    assert any("internal" in e.lower() for e in errors)


def test_unknown_source_type_is_rejected():
    assert any("source_type" in e for e in add_claim.validate_claim(dict(VALID, source_type="tweet"), set()))


def test_main_appends_and_fills_fetched_at(tmp_path):
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["fetched_at"].endswith("Z")


def test_main_rejects_invalid_and_writes_nothing(tmp_path, capsys):
    bad = dict(VALID)
    del bad["quote"]
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(bad)])
    assert rc == 1
    assert not (tmp_path / "claims.jsonl").exists()
    assert "quote" in capsys.readouterr().err


def test_main_rejects_duplicate_id_on_second_append(tmp_path):
    add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 1
    rows = [l for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1


def test_concurrent_appends_do_not_interleave(tmp_path):
    import concurrent.futures

    payloads = [json.dumps(dict(VALID, id=f"C{i:03d}")) for i in range(1, 41)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda p: add_claim.main(["--workspace", str(tmp_path), "--json", p]),
            payloads,
        ))
    lines = [l for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    for line in lines:
        json.loads(line)  # every line must be independently parseable
    assert len(lines) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_add_claim.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'add_claim'`

- [ ] **Step 3: Write minimal implementation**

Create `plugins/proposal-research/scripts/add_claim.py`:

```python
#!/usr/bin/env python3
"""Validate and atomically append one claim row to claims.jsonl.

Researchers MUST use this rather than writing the ledger directly: parallel
researchers sharing one file would otherwise clobber each other, and validation
here is deterministic rather than dependent on hook timing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import (  # noqa: E402
    CLAIM_ID_RE,
    SOURCE_TYPES,
    TIERS,
    read_jsonl,
    utc_now,
)

REQUIRED = ("id", "sub_q", "tier", "claim", "url", "quote", "source_type")
MAX_QUOTE_WORDS = 50


def validate_claim(row: dict, existing_ids: set[str]) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED:
        if key not in row:
            errors.append(f"missing required field: {key}")
        elif isinstance(row[key], str) and not row[key].strip():
            errors.append(f"empty required field: {key}")

    claim_id = row.get("id", "")
    if claim_id and not CLAIM_ID_RE.fullmatch(str(claim_id)):
        errors.append("id must match C\\d{3,} (zero-padded, e.g. C012)")
    if claim_id in existing_ids:
        errors.append(f"duplicate id: {claim_id}")

    tier = row.get("tier")
    if tier is not None and tier not in TIERS:
        errors.append(f"tier must be one of {sorted(TIERS)}, got {tier!r}")

    source_type = row.get("source_type")
    if source_type == "internal":
        errors.append(
            "source_type 'internal' is not admissible to claims.jsonl; "
            "internal material belongs in internal-claims.jsonl"
        )
    elif source_type is not None and source_type not in SOURCE_TYPES:
        errors.append(f"source_type must be one of {sorted(SOURCE_TYPES)}, got {source_type!r}")

    url = row.get("url") or ""
    if url and not str(url).startswith(("http://", "https://")):
        errors.append("url must be an http(s) URL")

    quote = row.get("quote") or ""
    if quote.strip() and len(quote.split()) > MAX_QUOTE_WORDS:
        errors.append(f"quote exceeds {MAX_QUOTE_WORDS} words; shorten it to the supporting sentence")

    return errors


def _atomic_append(path: Path, line: str) -> None:
    """Single O_APPEND write of one line — atomic under POSIX below PIPE_BUF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a validated claim to claims.jsonl")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--json", required=True, help="claim row as a JSON object")
    args = parser.parse_args(argv)

    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as exc:
        print(f"REJECTED: --json is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(row, dict):
        print("REJECTED: --json must be a JSON object", file=sys.stderr)
        return 1

    ledger = Path(args.workspace) / "claims.jsonl"
    existing_ids = {r.get("id") for r in read_jsonl(ledger)}

    errors = validate_claim(row, existing_ids)
    if errors:
        print("REJECTED: claim not appended. Fix and retry:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    row.setdefault("fetched_at", utc_now())
    _atomic_append(ledger, json.dumps(row, ensure_ascii=False) + "\n")
    print(f"OK: appended {row['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chandima/repos/CCAF && python3 -m pytest plugins/proposal-research/tests/test_add_claim.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Write the failing test for verdicts**

Create `plugins/proposal-research/tests/test_add_verdict.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import add_verdict  # noqa: E402

VALID = {
    "claim_id": "C001",
    "verdict": "CONFIRMED",
    "validator_agent_id": "a0b0ba8988783040d",
    "validator_model": "haiku",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
}


def test_valid_verdict_has_no_errors():
    assert add_verdict.validate_verdict(dict(VALID)) == []


def test_unknown_verdict_is_rejected():
    errors = add_verdict.validate_verdict(dict(VALID, verdict="PROBABLY"))
    assert any("verdict" in e for e in errors)


def test_confirmed_without_own_quote_is_rejected():
    row = dict(VALID)
    del row["quote"]
    errors = add_verdict.validate_verdict(row)
    assert any("quote" in e for e in errors)


def test_misleading_requires_caveat():
    row = dict(VALID, verdict="MISLEADING", quote="Public preview.")
    errors = add_verdict.validate_verdict(row)
    assert any("caveat" in e for e in errors)


def test_misleading_with_caveat_is_accepted():
    row = dict(VALID, verdict="MISLEADING", quote="Public preview.", caveat="Preview only, not GA.")
    assert add_verdict.validate_verdict(row) == []


def test_not_found_needs_no_quote():
    row = {k: v for k, v in VALID.items() if k != "quote"}
    row["verdict"] = "NOT_FOUND"
    assert add_verdict.validate_verdict(row) == []


def test_missing_validator_agent_id_is_rejected():
    row = dict(VALID)
    del row["validator_agent_id"]
    assert any("validator_agent_id" in e for e in add_verdict.validate_verdict(row))


def test_bad_claim_id_is_rejected():
    assert any("claim_id" in e for e in add_verdict.validate_verdict(dict(VALID, claim_id="nope")))


def test_main_appends_and_fills_ruled_at(tmp_path):
    rc = add_verdict.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["ruled_at"].endswith("Z")


def test_main_rejects_invalid_and_writes_nothing(tmp_path, capsys):
    rc = add_verdict.main(["--workspace", str(tmp_path), "--json", json.dumps(dict(VALID, verdict="MAYBE"))])
    assert rc == 1
    assert not (tmp_path / "verdicts.jsonl").exists()
    assert "verdict" in capsys.readouterr().err
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /Users/chandima/repos/CCAF && python3 -m pytest plugins/proposal-research/tests/test_add_verdict.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'add_verdict'`

- [ ] **Step 7: Write minimal implementation**

Create `plugins/proposal-research/scripts/add_verdict.py`:

```python
#!/usr/bin/env python3
"""Validate and atomically append one verdict row to verdicts.jsonl.

A CONFIRMED verdict must carry the validator's OWN supporting quote. That is
what distinguishes verification from echoing the researcher: the validator
never saw the researcher's quote, so supplying one proves it found its own.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import CLAIM_ID_RE, VERDICTS, utc_now  # noqa: E402

REQUIRED = ("claim_id", "verdict", "validator_agent_id", "validator_model")


def validate_verdict(row: dict) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED:
        if key not in row:
            errors.append(f"missing required field: {key}")
        elif isinstance(row[key], str) and not row[key].strip():
            errors.append(f"empty required field: {key}")

    claim_id = row.get("claim_id", "")
    if claim_id and not CLAIM_ID_RE.fullmatch(str(claim_id)):
        errors.append("claim_id must match C\\d{3,}")

    verdict = row.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        errors.append(f"verdict must be one of {sorted(VERDICTS)}, got {verdict!r}")

    if verdict in ("CONFIRMED", "MISLEADING") and not (row.get("quote") or "").strip():
        errors.append(
            f"{verdict} requires the validator's own supporting quote from the page"
        )

    if verdict == "MISLEADING" and not (row.get("caveat") or "").strip():
        errors.append("MISLEADING requires a caveat explaining why the claim misleads")

    return errors


def _atomic_append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a validated verdict to verdicts.jsonl")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--json", required=True, help="verdict row as a JSON object")
    args = parser.parse_args(argv)

    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as exc:
        print(f"REJECTED: --json is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(row, dict):
        print("REJECTED: --json must be a JSON object", file=sys.stderr)
        return 1

    errors = validate_verdict(row)
    if errors:
        print("REJECTED: verdict not appended. Fix and retry:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    row.setdefault("ruled_at", utc_now())
    _atomic_append(Path(args.workspace) / "verdicts.jsonl", json.dumps(row, ensure_ascii=False) + "\n")
    print(f"OK: recorded {row['verdict']} for {row['claim_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run both test files to verify they pass**

Run: `cd /Users/chandima/repos/CCAF && python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 9: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research/scripts plugins/proposal-research/tests
git commit -m "feat(proposal-research): validated atomic ledger append CLIs"
```

---
### Task 3: Hooks — fetch provenance recording and ledger write protection

**Files:**
- Modify: `plugins/proposal-research/scripts/workspace.py` (append active-run pointer helpers)
- Create: `plugins/proposal-research/hooks/record_fetch.py`
- Create: `plugins/proposal-research/hooks/ledger_lint.py`
- Create: `plugins/proposal-research/hooks/hooks.json`
- Create: `plugins/proposal-research/tests/test_hooks.py`

**Interfaces:**
- Consumes: `workspace.append_jsonl`, `workspace.utc_now` (Task 1); `add_claim.py` / `add_verdict.py` CLI paths (Task 2)
- Produces:
  - `workspace.active_runs_path(cwd: Path) -> Path`
  - `workspace.set_active_run(cwd: Path, session_id: str, slug: str) -> None`
  - `workspace.get_active_run(cwd: Path, session_id: str) -> str | None`
  - `fetch-log.jsonl` rows: `{"ts","tool","url","query","agent_id","agent_type"}`
  - `hooks.json` registering `PostToolUse` (record_fetch) and `PreToolUse` (ledger_lint)

- [ ] **Step 1: Write the failing test**

Create `plugins/proposal-research/tests/test_hooks.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import workspace  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
RECORD_FETCH = PLUGIN / "hooks" / "record_fetch.py"
LEDGER_LINT = PLUGIN / "hooks" / "ledger_lint.py"
SESSION = "sess-abc-123"


def run_hook(script: Path, payload: dict):
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def fetch_log(tmp_path):
    return workspace.read_jsonl(tmp_path / "research" / "run-a" / "fetch-log.jsonl")


# --- active run pointer -------------------------------------------------

def test_set_and_get_active_run(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    assert workspace.get_active_run(tmp_path, SESSION) == "run-a"


def test_get_active_run_unknown_session_returns_none(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    assert workspace.get_active_run(tmp_path, "other") is None


def test_set_active_run_supports_concurrent_sessions(tmp_path):
    workspace.set_active_run(tmp_path, "s1", "run-a")
    workspace.set_active_run(tmp_path, "s2", "run-b")
    assert workspace.get_active_run(tmp_path, "s1") == "run-a"
    assert workspace.get_active_run(tmp_path, "s2") == "run-b"


# --- record_fetch -------------------------------------------------------

def test_webfetch_is_recorded_with_agent_id(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    result = run_hook(RECORD_FETCH, {
        "session_id": SESSION,
        "cwd": str(tmp_path),
        "tool_name": "WebFetch",
        "tool_input": {"url": "https://learn.microsoft.com/x"},
        "agent_id": "val-001",
        "agent_type": "validator",
    })
    assert result.returncode == 0
    rows = fetch_log(tmp_path)
    assert rows[0]["url"] == "https://learn.microsoft.com/x"
    assert rows[0]["agent_id"] == "val-001"
    assert rows[0]["agent_type"] == "validator"
    assert rows[0]["ts"].endswith("Z")


def test_websearch_records_query_and_null_url(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "WebSearch",
        "tool_input": {"query": "copilot studio mcp tool limit"},
        "agent_id": "res-002", "agent_type": "researcher",
    })
    rows = fetch_log(tmp_path)
    assert rows[0]["query"] == "copilot studio mcp tool limit"
    assert rows[0]["url"] is None


def test_ms_docs_fetch_is_recorded(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
        "tool_input": {"url": "https://learn.microsoft.com/y"},
        "agent_id": "res-003", "agent_type": "researcher",
    })
    assert fetch_log(tmp_path)[0]["url"] == "https://learn.microsoft.com/y"


def test_main_session_call_records_null_agent_id(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "WebFetch", "tool_input": {"url": "https://example.com"},
    })
    assert fetch_log(tmp_path)[0]["agent_id"] is None


def test_no_active_run_records_nothing_and_exits_zero(tmp_path):
    result = run_hook(RECORD_FETCH, {
        "session_id": "unknown", "cwd": str(tmp_path),
        "tool_name": "WebFetch", "tool_input": {"url": "https://example.com"},
    })
    assert result.returncode == 0
    assert not (tmp_path / "research" / "run-a" / "fetch-log.jsonl").exists()


def test_malformed_payload_exits_zero_without_crashing(tmp_path):
    result = subprocess.run(
        [sys.executable, str(RECORD_FETCH)],
        input="not json at all", capture_output=True, text=True,
    )
    assert result.returncode == 0


# --- ledger_lint --------------------------------------------------------

def test_direct_write_to_claims_ledger_is_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "claims.jsonl"),
                       "content": "{}"},
    })
    assert result.returncode == 2
    assert "add_claim.py" in result.stderr


def test_direct_edit_to_verdicts_ledger_is_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "verdicts.jsonl"),
                       "old_string": "a", "new_string": "b"},
    })
    assert result.returncode == 2
    assert "add_verdict.py" in result.stderr


def test_write_to_other_files_is_allowed(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "plan.md"),
                       "content": "# Plan"},
    })
    assert result.returncode == 0


def test_internal_claims_ledger_is_not_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "internal-claims.jsonl"),
                       "content": "{}"},
    })
    assert result.returncode == 0


def test_ledger_lint_malformed_payload_exits_zero(tmp_path):
    result = subprocess.run(
        [sys.executable, str(LEDGER_LINT)],
        input="{{{", capture_output=True, text=True,
    )
    assert result.returncode == 0


# --- hooks.json ---------------------------------------------------------

def test_hooks_json_registers_both_hooks():
    cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    post = cfg["hooks"]["PostToolUse"]
    pre = cfg["hooks"]["PreToolUse"]
    assert "WebFetch" in post[0]["matcher"]
    assert "microsoft_docs_mcp" in post[0]["matcher"]
    assert "record_fetch.py" in post[0]["hooks"][0]["command"]
    assert "CLAUDE_PLUGIN_ROOT" in post[0]["hooks"][0]["command"]
    assert pre[0]["matcher"] == "Write|Edit"
    assert "ledger_lint.py" in pre[0]["hooks"][0]["command"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_hooks.py -v`
Expected: FAIL — `AttributeError: module 'workspace' has no attribute 'set_active_run'`

- [ ] **Step 3: Append the active-run helpers to workspace.py**

Append to `plugins/proposal-research/scripts/workspace.py`:

```python
def active_runs_path(cwd: Path) -> Path:
    """Maps session_id -> slug, so hooks can find the run they belong to."""
    return Path(cwd) / "research" / ".active.json"


def _load_active(cwd: Path) -> dict:
    path = active_runs_path(cwd)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def set_active_run(cwd: Path, session_id: str, slug: str) -> None:
    path = active_runs_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_active(cwd)
    data[session_id] = slug
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_active_run(cwd: Path, session_id: str) -> str | None:
    return _load_active(cwd).get(session_id)
```

- [ ] **Step 4: Write record_fetch.py**

Create `plugins/proposal-research/hooks/record_fetch.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: record every web retrieval with its originating agent_id.

This is the provenance spine. A URL cited in the evidence pack but absent from
fetch-log.jsonl is the exact signature of a hallucinated citation, and the
agent_id lets the gate prove the validator that ruled on a claim fetched that
claim's URL itself.

Never blocks. Any failure exits 0 silently — a logging hook that crashes would
take the whole run down with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def main() -> int:
    try:
        from workspace import append_jsonl, get_active_run, utc_now

        payload = json.load(sys.stdin)
        cwd = payload.get("cwd") or "."
        session_id = payload.get("session_id") or ""

        slug = get_active_run(Path(cwd), session_id)
        if not slug:
            return 0  # no active research run; nothing to record

        tool_input = payload.get("tool_input") or {}
        append_jsonl(
            Path(cwd) / "research" / slug / "fetch-log.jsonl",
            {
                "ts": utc_now(),
                "tool": payload.get("tool_name"),
                "url": tool_input.get("url"),
                "query": tool_input.get("query"),
                "agent_id": payload.get("agent_id"),
                "agent_type": payload.get("agent_type"),
            },
        )
    except Exception:  # noqa: BLE001 — never break the run
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Write ledger_lint.py**

Create `plugins/proposal-research/hooks/ledger_lint.py`:

```python
#!/usr/bin/env python3
"""PreToolUse hook: deny direct writes to the append-only ledgers.

claims.jsonl and verdicts.jsonl are written by parallel agents. Direct Write or
Edit would clobber concurrent appends and bypass validation, so both are denied
here and the agent is redirected to the CLI that appends atomically.

Exit 2 blocks the tool call and returns stderr to the model as feedback.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

GUARDED = {
    "claims.jsonl": "add_claim.py",
    "verdicts.jsonl": "add_verdict.py",
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0

    file_path = ((payload.get("tool_input") or {}).get("file_path")) or ""
    cli = GUARDED.get(Path(file_path).name)
    if not cli:
        return 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "${CLAUDE_PLUGIN_ROOT}")
    workspace = Path(file_path).parent
    print(
        f"BLOCKED: {Path(file_path).name} is append-only and written concurrently by "
        f"parallel agents. Direct Write/Edit would clobber other agents' rows and skip "
        f"validation.\n\n"
        f"Use the CLI instead:\n"
        f"  python3 {plugin_root}/scripts/{cli} \\\n"
        f"    --workspace {workspace} \\\n"
        f"    --json '{{...one row...}}'\n\n"
        f"It validates the row, rejects it with reasons if malformed, and appends "
        f"atomically.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Write hooks.json**

Create `plugins/proposal-research/hooks/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "WebFetch|WebSearch|mcp__microsoft_docs_mcp__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/record_fetch.py\"",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/ledger_lint.py\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/chandima/repos/CCAF && python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 8: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): fetch provenance hook and ledger write protection"
```

---
### Task 4: The gate, part 1 — citation resolution and verdict admission

**Files:**
- Create: `plugins/proposal-research/scripts/verify_pack.py`
- Create: `plugins/proposal-research/tests/test_verify_pack.py`
- Create: `plugins/proposal-research/tests/fixtures/__init__.py`
- Create: `plugins/proposal-research/tests/fixtures/build.py`

**Interfaces:**
- Consumes: `workspace.read_jsonl`, `workspace.CLAIM_ID_RE` (Task 1)
- Produces:
  - `verify_pack.Finding(check: str, severity: str, message: str)` — NamedTuple
  - `verify_pack.FAIL`, `verify_pack.WARN` — severity constants
  - `verify_pack.APPENDIX_HEADING` — `"## Unverified & excluded"`
  - `verify_pack.Context` — dataclass `(workspace, pack_text, body, appendix, claims, verdicts, fetches)`
  - `verify_pack.load_context(workspace: Path, pack_name: str = "evidence-pack.md") -> Context`
  - `verify_pack.extract_citations(text: str) -> list[str]`
  - `verify_pack.split_pack(text: str) -> tuple[str, str]`
  - `verify_pack.check_citations_resolve(ctx) -> list[Finding]`
  - `verify_pack.check_verdict_admission(ctx) -> list[Finding]`
  - `fixtures.build.make_workspace(tmp_path, claims=..., verdicts=..., fetches=..., pack=...) -> Path`

- [ ] **Step 1: Write the fixture builder**

Create `plugins/proposal-research/tests/fixtures/__init__.py` (empty file).

Create `plugins/proposal-research/tests/fixtures/build.py`:

```python
"""Synthetic workspace builder for gate tests.

Defaults describe a workspace that PASSES every check, so each test mutates
exactly one thing and asserts exactly one failure.
"""
from __future__ import annotations

import json
from pathlib import Path

URL_A = "https://learn.microsoft.com/a"
URL_B = "https://learn.microsoft.com/b"

CLAIM_MATERIAL = {
    "id": "C001", "sub_q": "Q1", "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": URL_A,
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc", "fetched_at": "2026-08-29T09:41:00Z",
}
CLAIM_CONTEXT = {
    "id": "C002", "sub_q": "Q2", "tier": "context",
    "claim": "ServiceNow positions AI Agent Studio for platform-native agents",
    "url": URL_B,
    "quote": "AI Agent Studio lets teams build agents natively on the Now Platform.",
    "source_type": "vendor_doc", "fetched_at": "2026-08-29T09:42:00Z",
}

VERDICTS_OK = [
    {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
     "validator_model": "haiku", "quote": "A maximum of 10 tools per MCP server connection is supported.",
     "ruled_at": "2026-08-29T09:50:00Z"},
    {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-s1",
     "validator_model": "sonnet", "quote": "A maximum of 10 tools per MCP server connection is supported.",
     "ruled_at": "2026-08-29T09:51:00Z"},
    {"claim_id": "C002", "verdict": "CONFIRMED", "validator_agent_id": "val-h2",
     "validator_model": "haiku", "quote": "AI Agent Studio lets teams build agents natively.",
     "ruled_at": "2026-08-29T09:52:00Z"},
]

FETCHES_OK = [
    {"ts": "2026-08-29T09:41:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "res-1", "agent_type": "researcher"},
    {"ts": "2026-08-29T09:42:00Z", "tool": "WebFetch", "url": URL_B, "query": None,
     "agent_id": "res-1", "agent_type": "researcher"},
    {"ts": "2026-08-29T09:50:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "val-h1", "agent_type": "validator"},
    {"ts": "2026-08-29T09:51:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "val-s1", "agent_type": "validator"},
    {"ts": "2026-08-29T09:52:00Z", "tool": "WebFetch", "url": URL_B, "query": None,
     "agent_id": "val-h2", "agent_type": "validator"},
]

PACK_OK = """# Evidence Pack

## Capability limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

ServiceNow positions AI Agent Studio for platform-native agents [C002].

## Unverified & excluded

Nothing was excluded in this run.
"""


def make_workspace(tmp_path, claims=None, verdicts=None, fetches=None, pack=None,
                   pack_name="evidence-pack.md") -> Path:
    ws = Path(tmp_path) / "research" / "run-a"
    ws.mkdir(parents=True, exist_ok=True)

    rows = [CLAIM_MATERIAL, CLAIM_CONTEXT] if claims is None else claims
    _write_jsonl(ws / "claims.jsonl", rows)
    _write_jsonl(ws / "verdicts.jsonl", VERDICTS_OK if verdicts is None else verdicts)
    _write_jsonl(ws / "fetch-log.jsonl", FETCHES_OK if fetches is None else fetches)
    (ws / pack_name).write_text(PACK_OK if pack is None else pack, encoding="utf-8")
    return ws


def _write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
```

- [ ] **Step 2: Write the failing test**

Create `plugins/proposal-research/tests/test_verify_pack.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_pack  # noqa: E402
from fixtures import build  # noqa: E402


def fails(findings):
    return [f for f in findings if f.severity == verify_pack.FAIL]


# --- parsing ------------------------------------------------------------

def test_extract_citations_finds_ids_in_order():
    assert verify_pack.extract_citations("a [C002] b [C001] c") == ["C002", "C001"]


def test_extract_citations_ignores_malformed_ids():
    assert verify_pack.extract_citations("[C1] [X001] [C012]") == ["C012"]


def test_split_pack_separates_appendix():
    body, appendix = verify_pack.split_pack(build.PACK_OK)
    assert "[C001]" in body
    assert "Nothing was excluded" in appendix
    assert "[C001]" not in appendix


def test_split_pack_with_no_appendix_returns_empty_appendix():
    body, appendix = verify_pack.split_pack("# Pack\n\nA claim [C001].\n")
    assert appendix == ""


# --- check 1: citations resolve ----------------------------------------

def test_clean_workspace_passes_check_one(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_citations_resolve(ctx)) == []


def test_orphan_citation_fails(tmp_path):
    pack = build.PACK_OK.replace("[C002]", "[C999]")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    findings = fails(verify_pack.check_citations_resolve(ctx))
    assert len(findings) == 1
    assert "C999" in findings[0].message


# --- check 2: verdict admission ----------------------------------------

def test_clean_workspace_passes_check_two(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []


def test_cited_claim_with_no_verdict_fails(tmp_path):
    verdicts = [v for v in build.VERDICTS_OK if v["claim_id"] != "C002"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C002" in f.message and "no verdict" in f.message for f in findings)


def test_material_claim_with_single_verdict_fails_escalation_rule(tmp_path):
    verdicts = [v for v in build.VERDICTS_OK if v["validator_model"] != "sonnet"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("escalation" in f.message for f in findings)


def test_material_claim_not_confirmed_by_all_validators_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1]["verdict"] = "MISLEADING"
    verdicts[1]["caveat"] = "Preview only."
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C001" in f.message for f in findings)


def test_contradicted_claim_in_body_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2]["verdict"] = "CONTRADICTED"
    verdicts[2].pop("quote", None)
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("CONTRADICTED" in f.message for f in findings)


def test_context_claim_not_found_warns_but_does_not_fail(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2]["verdict"] = "NOT_FOUND"
    verdicts[2].pop("quote", None)
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = verify_pack.check_verdict_admission(ctx)
    assert fails(findings) == []
    assert any(f.severity == verify_pack.WARN and "C002" in f.message for f in findings)


def test_misleading_claim_without_its_caveat_in_pack_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("caveat" in f.message for f in findings)


def test_misleading_claim_with_caveat_present_passes(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    pack = build.PACK_OK.replace(
        "[C002].", "[C002]. Public preview only, not GA.")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts, pack=pack))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []


def test_claims_cited_only_in_appendix_are_not_admission_checked(tmp_path):
    pack = """# Evidence Pack

Body with no citations.

## Unverified & excluded

- Could not stand up: [C001]
"""
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=[], pack=pack))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_verify_pack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'verify_pack'`

- [ ] **Step 4: Write minimal implementation**

Create `plugins/proposal-research/scripts/verify_pack.py`:

```python
#!/usr/bin/env python3
"""The gate. Proves an evidence pack's claims are backed by retrieved pages.

Six checks, added across three tasks. Non-zero exit blocks the pipeline.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import read_jsonl  # noqa: E402

FAIL = "FAIL"
WARN = "WARN"

APPENDIX_HEADING = "## Unverified & excluded"
CITATION_RE = re.compile(r"\[(C\d{3,})\]")


class Finding(NamedTuple):
    check: str
    severity: str
    message: str


@dataclass
class Context:
    workspace: Path
    pack_text: str
    body: str
    appendix: str
    claims: dict[str, dict]
    verdicts: dict[str, list[dict]]
    fetches: list[dict] = field(default_factory=list)

    @property
    def body_citations(self) -> list[str]:
        return extract_citations(self.body)

    @property
    def all_citations(self) -> list[str]:
        return extract_citations(self.pack_text)


def extract_citations(text: str) -> list[str]:
    return CITATION_RE.findall(text or "")


def split_pack(text: str) -> tuple[str, str]:
    """Return (body, appendix). Appendix is everything from the heading on."""
    idx = (text or "").find(APPENDIX_HEADING)
    if idx == -1:
        return text or "", ""
    return text[:idx], text[idx:]


def load_context(workspace: Path, pack_name: str = "evidence-pack.md") -> Context:
    workspace = Path(workspace)
    pack_text = (workspace / pack_name).read_text(encoding="utf-8")
    body, appendix = split_pack(pack_text)

    claims = {r["id"]: r for r in read_jsonl(workspace / "claims.jsonl") if "id" in r}

    verdicts: dict[str, list[dict]] = {}
    for row in read_jsonl(workspace / "verdicts.jsonl"):
        verdicts.setdefault(row.get("claim_id"), []).append(row)

    return Context(
        workspace=workspace,
        pack_text=pack_text,
        body=body,
        appendix=appendix,
        claims=claims,
        verdicts=verdicts,
        fetches=read_jsonl(workspace / "fetch-log.jsonl"),
    )


def check_citations_resolve(ctx: Context) -> list[Finding]:
    """Check 1: every [Cxxx] anywhere in the pack resolves to a ledger row."""
    findings = []
    for claim_id in dict.fromkeys(ctx.all_citations):
        if claim_id not in ctx.claims:
            findings.append(Finding(
                "citations-resolve", FAIL,
                f"{claim_id} is cited in the pack but has no row in claims.jsonl",
            ))
    return findings


def check_verdict_admission(ctx: Context) -> list[Finding]:
    """Check 2: body claims carry verdicts that admit them.

    material -> at least two verdicts (haiku plus sonnet escalation), all CONFIRMED
    context  -> CONTRADICTED is fatal; NOT_FOUND is allowed but warned
    MISLEADING -> admitted only if the validator's caveat text appears in the pack
    """
    findings = []
    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue  # already reported by check 1

        rulings = ctx.verdicts.get(claim_id, [])
        if not rulings:
            findings.append(Finding(
                "verdict-admission", FAIL,
                f"{claim_id} is cited in the pack body but has no verdict",
            ))
            continue

        verdicts = [r.get("verdict") for r in rulings]
        tier = claim.get("tier")

        if "CONTRADICTED" in verdicts:
            findings.append(Finding(
                "verdict-admission", FAIL,
                f"{claim_id} was ruled CONTRADICTED and must not appear in the pack body",
            ))
            continue

        for ruling in rulings:
            if ruling.get("verdict") != "MISLEADING":
                continue
            caveat = (ruling.get("caveat") or "").strip()
            if caveat and caveat not in ctx.pack_text:
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} was ruled MISLEADING but its caveat is absent from the "
                    f"pack: {caveat!r}",
                ))

        if tier == "material":
            if len(rulings) < 2:
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} is material but carries {len(rulings)} verdict(s); the "
                    f"sonnet escalation pass is missing",
                ))
            elif any(v != "CONFIRMED" for v in verdicts):
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} is material and must be CONFIRMED by every validator; "
                    f"got {verdicts}",
                ))
        elif "NOT_FOUND" in verdicts:
            findings.append(Finding(
                "verdict-admission", WARN,
                f"{claim_id} is context-tier and NOT_FOUND; admitted as low confidence",
            ))

    return findings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_verify_pack.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 6: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): gate checks for citation resolution and verdict admission"
```

---
### Task 5: The gate, part 2 — provenance and validator blindness

This is the anti-hallucination heart of the plugin. Check 3 proves a cited page was actually
retrieved this session. Check 4 proves the validator that ruled on a claim retrieved that
claim's URL *itself*, which is what makes blind validation a property of the log rather than a
promise in a prompt.

**Files:**
- Modify: `plugins/proposal-research/scripts/verify_pack.py` (append three checks)
- Modify: `plugins/proposal-research/tests/test_verify_pack.py` (append tests)

**Interfaces:**
- Consumes: `verify_pack.Context`, `verify_pack.Finding`, `FAIL`, `WARN` (Task 4); `fixtures.build.make_workspace` (Task 4)
- Produces:
  - `verify_pack.normalize_url(url: str) -> str`
  - `verify_pack.check_fetch_provenance(ctx) -> list[Finding]`
  - `verify_pack.check_validator_blindness(ctx) -> list[Finding]`
  - `verify_pack.check_validator_tool_restrictions(ctx) -> list[Finding]`

- [ ] **Step 1: Write the failing test**

Append to `plugins/proposal-research/tests/test_verify_pack.py`:

```python
# --- url normalization --------------------------------------------------

def test_normalize_url_strips_fragment_and_trailing_slash():
    assert verify_pack.normalize_url("https://a.com/x/#frag") == "https://a.com/x"
    assert verify_pack.normalize_url("https://a.com/x") == "https://a.com/x"


def test_normalize_url_handles_none():
    assert verify_pack.normalize_url(None) == ""


# --- check 3: fetch provenance -----------------------------------------

def test_clean_workspace_passes_provenance(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_fetch_provenance(ctx)) == []


def test_cited_url_never_fetched_fails(tmp_path):
    fetches = [f for f in build.FETCHES_OK if f["url"] != build.URL_B]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_fetch_provenance(ctx))
    assert any("C002" in f.message and "never retrieved" in f.message for f in findings)


def test_provenance_matches_despite_trailing_slash(tmp_path):
    fetches = [dict(f) for f in build.FETCHES_OK]
    for f in fetches:
        if f["url"]:
            f["url"] = f["url"] + "/"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert fails(verify_pack.check_fetch_provenance(ctx)) == []


def test_empty_fetch_log_fails_every_cited_claim(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=[]))
    assert len(fails(verify_pack.check_fetch_provenance(ctx))) == 2


# --- check 4: validator blindness --------------------------------------

def test_clean_workspace_passes_blindness(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_validator_blindness(ctx)) == []


def test_validator_that_never_fetched_the_url_fails(tmp_path):
    fetches = [f for f in build.FETCHES_OK if f["agent_id"] != "val-s1"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_validator_blindness(ctx))
    assert any("val-s1" in f.message and "C001" in f.message for f in findings)


def test_validator_that_fetched_a_different_url_fails(tmp_path):
    fetches = [dict(f) for f in build.FETCHES_OK]
    for f in fetches:
        if f["agent_id"] == "val-s1":
            f["url"] = "https://unrelated.example/other"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert any("val-s1" in f.message for f in fails(verify_pack.check_validator_blindness(ctx)))


def test_verdict_with_no_validator_agent_id_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1].pop("validator_agent_id")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_validator_blindness(ctx))
    assert any("no validator_agent_id" in f.message for f in findings)


def test_blindness_only_applies_to_body_claims(tmp_path):
    pack = "# Pack\n\nNo citations here.\n\n## Unverified & excluded\n\n- [C001]\n"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=[], pack=pack))
    assert fails(verify_pack.check_validator_blindness(ctx)) == []


# --- validator tool restrictions ---------------------------------------

def test_validator_using_websearch_fails(tmp_path):
    fetches = list(build.FETCHES_OK) + [
        {"ts": "2026-08-29T09:53:00Z", "tool": "WebSearch", "url": None,
         "query": "friendlier source", "agent_id": "val-s1", "agent_type": "validator"},
    ]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_validator_tool_restrictions(ctx))
    assert any("val-s1" in f.message and "WebSearch" in f.message for f in findings)


def test_researcher_using_websearch_is_fine(tmp_path):
    fetches = list(build.FETCHES_OK) + [
        {"ts": "2026-08-29T09:53:00Z", "tool": "WebSearch", "url": None,
         "query": "mcp tool limit", "agent_id": "res-1", "agent_type": "researcher"},
    ]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert fails(verify_pack.check_validator_tool_restrictions(ctx)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_verify_pack.py -v`
Expected: FAIL — `AttributeError: module 'verify_pack' has no attribute 'normalize_url'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/proposal-research/scripts/verify_pack.py`:

```python
def normalize_url(url: str | None) -> str:
    """Compare URLs ignoring fragment and trailing slash."""
    if not url:
        return ""
    return url.split("#", 1)[0].rstrip("/")


def _fetched_urls_by_agent(ctx: Context) -> dict[str, set[str]]:
    by_agent: dict[str, set[str]] = {}
    for row in ctx.fetches:
        url = normalize_url(row.get("url"))
        if not url:
            continue
        by_agent.setdefault(row.get("agent_id"), set()).add(url)
    return by_agent


def check_fetch_provenance(ctx: Context) -> list[Finding]:
    """Check 3: every cited claim's URL was actually retrieved this session.

    A URL in the pack that never appears in fetch-log.jsonl is the signature of
    a hallucinated citation.
    """
    findings = []
    all_fetched = {
        normalize_url(r.get("url")) for r in ctx.fetches if normalize_url(r.get("url"))
    }
    for claim_id in dict.fromkeys(ctx.all_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        url = normalize_url(claim.get("url"))
        if url and url not in all_fetched:
            findings.append(Finding(
                "fetch-provenance", FAIL,
                f"{claim_id} cites {claim.get('url')} but that page was never retrieved "
                f"during this run",
            ))
    return findings


def check_validator_blindness(ctx: Context) -> list[Finding]:
    """Check 4: each validator that ruled on a body claim fetched that URL itself.

    This is what makes blindness provable. A validator ruling on a page it never
    opened is either echoing the researcher or inventing a verdict.
    """
    findings = []
    by_agent = _fetched_urls_by_agent(ctx)

    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        url = normalize_url(claim.get("url"))
        if not url:
            continue

        for ruling in ctx.verdicts.get(claim_id, []):
            agent_id = ruling.get("validator_agent_id")
            if not agent_id:
                findings.append(Finding(
                    "validator-blindness", FAIL,
                    f"a verdict on {claim_id} carries no validator_agent_id, so its "
                    f"independence cannot be proven",
                ))
                continue
            if url not in by_agent.get(agent_id, set()):
                findings.append(Finding(
                    "validator-blindness", FAIL,
                    f"validator {agent_id} ruled {ruling.get('verdict')} on {claim_id} "
                    f"but never retrieved {claim.get('url')} itself",
                ))
    return findings


def check_validator_tool_restrictions(ctx: Context) -> list[Finding]:
    """Validators must not search. Searching means shopping for a friendlier source."""
    findings = []
    for row in ctx.fetches:
        if row.get("agent_type") == "validator" and row.get("tool") == "WebSearch":
            findings.append(Finding(
                "validator-tool-restrictions", FAIL,
                f"validator {row.get('agent_id')} called WebSearch "
                f"(query={row.get('query')!r}); validators must only fetch the cited URL",
            ))
    return findings
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_verify_pack.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): prove fetch provenance and validator blindness"
```

---
### Task 6: The gate, part 3 — uncited prose, source mix, report, CLI

**Files:**
- Modify: `plugins/proposal-research/scripts/verify_pack.py` (append checks, runner, renderer, CLI)
- Modify: `plugins/proposal-research/tests/test_verify_pack.py` (append tests)

**Interfaces:**
- Consumes: everything from Tasks 4 and 5
- Produces:
  - `verify_pack.NO_CITATION_MARKER` — `"<!-- no-citation:"`
  - `verify_pack.check_uncited_prose(ctx) -> list[Finding]`
  - `verify_pack.check_source_mix(ctx) -> list[Finding]`
  - `verify_pack.collect_stats(ctx) -> dict`
  - `verify_pack.ALL_CHECKS` — ordered list of check callables
  - `verify_pack.run_checks(ctx) -> list[Finding]`
  - `verify_pack.render_report(findings: list[Finding], stats: dict, passed: bool) -> str`
  - `verify_pack.main(argv) -> int` — CLI `verify_pack.py --workspace DIR [--pack NAME]`, exit 0 pass / 1 fail

- [ ] **Step 1: Write the failing test**

Append to `plugins/proposal-research/tests/test_verify_pack.py`:

```python
# --- check 5: uncited prose --------------------------------------------

def test_clean_workspace_passes_uncited_prose(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_long_uncited_body_paragraph_fails(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "Copilot Studio is clearly the stronger option for this client given the "
        "existing Microsoft investment and the team's familiarity with Power Platform.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert len(fails(verify_pack.check_uncited_prose(ctx))) == 1


def test_short_transition_paragraph_is_ignored(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded", "In summary:\n\n## Unverified & excluded")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_headings_tables_and_code_are_ignored(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "### A heading that is quite long indeed and has many words in it here\n\n"
        "| column one | column two | column three | column four | column five |\n"
        "|---|---|---|---|---|\n\n"
        "```\nsome code block with plenty of words inside it for length\n```\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_explicit_no_citation_marker_exempts_a_paragraph(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "<!-- no-citation: framing, not a factual claim -->\n"
        "This section compares the two candidate architectures against the client's "
        "stated priorities rather than asserting any new external fact.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_appendix_prose_is_never_flagged(tmp_path):
    pack = build.PACK_OK + (
        "\nThese claims could not be stood up against any first-party source "
        "and are recorded here so the reader can see what was excluded.\n")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


# --- check 6: source mix ------------------------------------------------

def test_vendor_doc_material_claims_pass_source_mix(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_source_mix(ctx)) == []


def test_material_claim_sourced_from_blog_warns(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, source_type="blog"), build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = verify_pack.check_source_mix(ctx)
    assert fails(findings) == []
    assert any(f.severity == verify_pack.WARN and "C001" in f.message for f in findings)


def test_collect_stats_counts_sources_and_verdicts(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    stats = verify_pack.collect_stats(ctx)
    assert stats["claims_total"] == 2
    assert stats["claims_cited"] == 2
    assert stats["source_mix"]["vendor_doc"] == 2
    assert stats["verdict_counts"]["CONFIRMED"] == 3
    assert stats["fetches_total"] == 5


# --- runner, renderer, CLI ---------------------------------------------

def test_run_checks_on_clean_workspace_has_no_failures(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.run_checks(ctx)) == []


def test_render_report_marks_pass(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    report = verify_pack.render_report([], verify_pack.collect_stats(ctx), True)
    assert "GATE: PASS" in report
    assert "Source mix" in report


def test_render_report_lists_failures(tmp_path):
    findings = [verify_pack.Finding("fetch-provenance", verify_pack.FAIL, "C001 was never retrieved")]
    report = verify_pack.render_report(findings, {"claims_total": 1, "claims_cited": 1,
                                                  "source_mix": {}, "verdict_counts": {},
                                                  "fetches_total": 0}, False)
    assert "GATE: FAIL" in report
    assert "C001 was never retrieved" in report


def test_main_passes_on_clean_workspace_and_writes_report(tmp_path):
    ws = build.make_workspace(tmp_path)
    assert verify_pack.main(["--workspace", str(ws)]) == 0
    assert "GATE: PASS" in (ws / "verify-report.md").read_text()


def test_main_fails_on_orphan_citation(tmp_path):
    ws = build.make_workspace(tmp_path, pack=build.PACK_OK.replace("[C002]", "[C999]"))
    assert verify_pack.main(["--workspace", str(ws)]) == 1
    assert "GATE: FAIL" in (ws / "verify-report.md").read_text()


def test_main_accepts_alternate_pack_name(tmp_path):
    ws = build.make_workspace(tmp_path, pack_name="proposal.md")
    assert verify_pack.main(["--workspace", str(ws), "--pack", "proposal.md"]) == 0
    assert (ws / "verify-report-proposal.md").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_verify_pack.py -v`
Expected: FAIL — `AttributeError: module 'verify_pack' has no attribute 'check_uncited_prose'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/proposal-research/scripts/verify_pack.py`:

```python
NO_CITATION_MARKER = "<!-- no-citation:"
MIN_FACTUAL_WORDS = 12


def _body_paragraphs(body: str) -> list[str]:
    """Prose paragraphs only: no headings, tables, list items, or code blocks."""
    paragraphs = []
    in_code = False
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("```"):
            in_code = not block.endswith("```") or block.count("```") % 2 == 1
            continue
        if in_code:
            if "```" in block:
                in_code = False
            continue
        first = block.splitlines()[0].lstrip()
        if first.startswith(("#", "|", ">", "-", "*", "+")):
            continue
        paragraphs.append(block)
    return paragraphs


def check_uncited_prose(ctx: Context) -> list[Finding]:
    """Check 5: no factual body paragraph lacks a citation.

    A paragraph may opt out with an explicit `<!-- no-citation: reason -->`
    marker, which keeps the exemption visible and auditable rather than silent.
    """
    findings = []
    for para in _body_paragraphs(ctx.body):
        if NO_CITATION_MARKER in para:
            continue
        if len(para.split()) < MIN_FACTUAL_WORDS:
            continue
        if CITATION_RE.search(para):
            continue
        preview = " ".join(para.split())[:90]
        findings.append(Finding(
            "uncited-prose", FAIL,
            f"factual paragraph carries no citation: \"{preview}...\"",
        ))
    return findings


def check_source_mix(ctx: Context) -> list[Finding]:
    """Check 6: surface material claims resting on weak source types."""
    findings = []
    weak = {"blog", "forum"}
    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        if claim.get("tier") == "material" and claim.get("source_type") in weak:
            findings.append(Finding(
                "source-mix", WARN,
                f"{claim_id} is material but rests on a {claim.get('source_type')} source; "
                f"prefer a first-party page for claims that move the proposal",
            ))
    return findings


def collect_stats(ctx: Context) -> dict:
    source_mix: dict[str, int] = {}
    for claim in ctx.claims.values():
        key = claim.get("source_type", "unknown")
        source_mix[key] = source_mix.get(key, 0) + 1

    verdict_counts: dict[str, int] = {}
    for rulings in ctx.verdicts.values():
        for ruling in rulings:
            key = ruling.get("verdict", "unknown")
            verdict_counts[key] = verdict_counts.get(key, 0) + 1

    return {
        "claims_total": len(ctx.claims),
        "claims_cited": len(set(ctx.all_citations)),
        "source_mix": source_mix,
        "verdict_counts": verdict_counts,
        "fetches_total": len(ctx.fetches),
    }


ALL_CHECKS = [
    check_citations_resolve,
    check_verdict_admission,
    check_fetch_provenance,
    check_validator_blindness,
    check_validator_tool_restrictions,
    check_uncited_prose,
    check_source_mix,
]


def run_checks(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(ctx))
    return findings


def render_report(findings: list[Finding], stats: dict, passed: bool) -> str:
    lines = [
        "# Verify Report",
        "",
        f"**GATE: {'PASS' if passed else 'FAIL'}**",
        "",
        "## Totals",
        "",
        f"- Claims in ledger: {stats.get('claims_total', 0)}",
        f"- Claims cited in pack: {stats.get('claims_cited', 0)}",
        f"- Fetches recorded: {stats.get('fetches_total', 0)}",
        "",
        "## Verdicts",
        "",
    ]
    verdict_counts = stats.get("verdict_counts") or {}
    lines.extend(f"- {k}: {v}" for k, v in sorted(verdict_counts.items())) or lines.append("- none")
    lines += ["", "## Source mix", ""]
    source_mix = stats.get("source_mix") or {}
    if source_mix:
        total = sum(source_mix.values()) or 1
        lines.append("| Source type | Claims | Share |")
        lines.append("|---|---|---|")
        for key, count in sorted(source_mix.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {key} | {count} | {round(100 * count / total)}% |")
    else:
        lines.append("- none")

    failures = [f for f in findings if f.severity == FAIL]
    warnings = [f for f in findings if f.severity == WARN]

    lines += ["", "## Failures", ""]
    lines.extend(f"- **[{f.check}]** {f.message}" for f in failures) or lines.append("- none")
    lines += ["", "## Warnings", ""]
    lines.extend(f"- [{f.check}] {f.message}" for f in warnings) or lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify an evidence pack against its ledgers")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--pack", default="evidence-pack.md", help="pack filename to verify")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    ctx = load_context(workspace, args.pack)
    findings = run_checks(ctx)
    stats = collect_stats(ctx)
    passed = not any(f.severity == FAIL for f in findings)

    stem = "verify-report.md" if args.pack == "evidence-pack.md" else \
        f"verify-report-{Path(args.pack).stem}.md"
    (workspace / stem).write_text(render_report(findings, stats, passed), encoding="utf-8")

    for finding in findings:
        stream = sys.stderr if finding.severity == FAIL else sys.stdout
        print(f"{finding.severity} [{finding.check}] {finding.message}", file=stream)

    print(f"GATE: {'PASS' if passed else 'FAIL'} — report at {workspace / stem}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): complete the gate with prose, source mix, report and CLI"
```

---
### Task 7: Ingestion lane 1 — carry-forward from prior runs

> **Deviation from spec, deliberate.** The spec re-fetches only carried claims older than 90
> days. But a carried claim cited in a new pack would then fail checks 3 and 4 — nothing in
> *this* session fetched its URL, and no validator in this session ruled on it. Rather than
> carve an exception into the gate (which would put a hole in exactly the guarantee the plugin
> exists to provide), **every carried claim is re-validated in the new run**. The saving is
> preserved because the expensive phase is *discovery*, not re-fetching a URL you already know:
> carried claims skip search and the researcher phase entirely. Staleness keeps a narrower job —
> flagging claims whose page has had time to drift, so the gap-hunter looks at them.

**Files:**
- Create: `plugins/proposal-research/scripts/ingest_context.py`
- Create: `plugins/proposal-research/tests/test_ingest_lane1.py`

**Interfaces:**
- Consumes: `workspace.read_jsonl`, `workspace.append_jsonl`, `workspace.utc_now` (Task 1)
- Produces:
  - `ingest_context.STALE_DAYS = 90`
  - `ingest_context.LEDGER_EXPORT = "06-Sources/ledger-export.jsonl"`
  - `ingest_context.load_prior_ledger(path: Path) -> list[dict]` — accepts a workspace dir or a vault dir
  - `ingest_context.is_stale(fetched_at: str, now: datetime, days: int = STALE_DAYS) -> bool`
  - `ingest_context.carry_forward(prior: list[dict], now: datetime) -> list[dict]`
  - `carried-claims.jsonl` rows: prior claim fields plus `origin: {slug, claim_id, fetched_at}`, `stale: bool`, `needs_revalidation: true`

- [ ] **Step 1: Write the failing test**

Create `plugins/proposal-research/tests/test_ingest_lane1.py`:

```python
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ingest_context  # noqa: E402

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
OLD = (NOW - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")

CLAIM = {
    "id": "C001", "sub_q": "Q1", "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": "https://learn.microsoft.com/a",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc", "fetched_at": FRESH,
}
CONFIRMED = [{"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v1",
              "validator_model": "haiku", "quote": "A maximum of 10 tools."},
             {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v2",
              "validator_model": "sonnet", "quote": "A maximum of 10 tools."}]


def write_workspace(tmp_path, claims, verdicts):
    ws = tmp_path / "research" / "prior-run"
    ws.mkdir(parents=True)
    (ws / "claims.jsonl").write_text("".join(json.dumps(c) + "\n" for c in claims))
    (ws / "verdicts.jsonl").write_text("".join(json.dumps(v) + "\n" for v in verdicts))
    return ws


def write_vault(tmp_path, rows):
    vault = tmp_path / "some-vault"
    (vault / "06-Sources").mkdir(parents=True)
    (vault / "06-Sources" / "ledger-export.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return vault


# --- staleness ----------------------------------------------------------

def test_fresh_claim_is_not_stale():
    assert ingest_context.is_stale(FRESH, NOW) is False


def test_old_claim_is_stale():
    assert ingest_context.is_stale(OLD, NOW) is True


def test_exactly_ninety_days_is_not_stale():
    ts = (NOW - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ingest_context.is_stale(ts, NOW) is False


def test_unparseable_timestamp_is_treated_as_stale():
    assert ingest_context.is_stale("not-a-date", NOW) is True


def test_missing_timestamp_is_treated_as_stale():
    assert ingest_context.is_stale(None, NOW) is True


# --- loading ------------------------------------------------------------

def test_load_prior_ledger_from_workspace(tmp_path):
    ws = write_workspace(tmp_path, [CLAIM], CONFIRMED)
    rows = ingest_context.load_prior_ledger(ws)
    assert rows[0]["id"] == "C001"
    assert len(rows[0]["verdicts"]) == 2


def test_load_prior_ledger_from_vault_export(tmp_path):
    vault = write_vault(tmp_path, [dict(CLAIM, verdicts=CONFIRMED)])
    rows = ingest_context.load_prior_ledger(vault)
    assert rows[0]["id"] == "C001"
    assert len(rows[0]["verdicts"]) == 2


def test_load_prior_ledger_missing_path_returns_empty(tmp_path):
    assert ingest_context.load_prior_ledger(tmp_path / "nope") == []


# --- carry forward ------------------------------------------------------

def test_confirmed_claim_is_carried(tmp_path):
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED, _slug="prior-run")], NOW)
    assert len(rows) == 1
    assert rows[0]["url"] == CLAIM["url"]
    assert rows[0]["origin"]["claim_id"] == "C001"
    assert rows[0]["origin"]["slug"] == "prior-run"


def test_every_carried_claim_needs_revalidation(tmp_path):
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED)], NOW)
    assert rows[0]["needs_revalidation"] is True


def test_fresh_carried_claim_is_not_flagged_stale():
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED)], NOW)
    assert rows[0]["stale"] is False


def test_old_carried_claim_is_flagged_stale():
    rows = ingest_context.carry_forward(
        [dict(CLAIM, fetched_at=OLD, verdicts=CONFIRMED)], NOW)
    assert rows[0]["stale"] is True


def test_contradicted_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0]), dict(CONFIRMED[1], verdict="CONTRADICTED")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_not_found_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0], verdict="NOT_FOUND")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_misleading_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0], verdict="MISLEADING", caveat="preview")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_claim_with_no_verdicts_is_not_carried():
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=[])], NOW) == []


def test_internal_claim_is_never_carried_as_public():
    row = dict(CLAIM, source_type="internal", url=None, verdicts=CONFIRMED)
    assert ingest_context.carry_forward([row], NOW) == []


def test_carried_ids_are_reassigned_sequentially():
    rows = ingest_context.carry_forward([
        dict(CLAIM, id="C007", verdicts=CONFIRMED),
        dict(CLAIM, id="C009", url="https://learn.microsoft.com/b", verdicts=CONFIRMED),
    ], NOW)
    assert [r["id"] for r in rows] == ["C001", "C002"]


def test_duplicate_urls_are_carried_once():
    rows = ingest_context.carry_forward([
        dict(CLAIM, id="C007", verdicts=CONFIRMED),
        dict(CLAIM, id="C009", verdicts=CONFIRMED),
    ], NOW)
    assert len(rows) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_ingest_lane1.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest_context'`

- [ ] **Step 3: Write minimal implementation**

Create `plugins/proposal-research/scripts/ingest_context.py`:

```python
#!/usr/bin/env python3
"""Phase 0.5 — assemble local context before the planner runs.

Lane 1 (prior runs) is public and carried forward. Lanes 2-4 (Task 8) are
internal: they steer the research without ever becoming evidence.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import read_jsonl  # noqa: E402

STALE_DAYS = 90
LEDGER_EXPORT = "06-Sources/ledger-export.jsonl"


def is_stale(fetched_at: str | None, now: datetime, days: int = STALE_DAYS) -> bool:
    """Unknown or unparseable timestamps count as stale — fail toward re-checking."""
    if not fetched_at:
        return True
    try:
        seen = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (now - seen).days > days


def load_prior_ledger(path: Path) -> list[dict]:
    """Accept either a run workspace (claims + verdicts) or a generated vault (export).

    Returns claim rows each carrying a `verdicts` list and a `_slug` provenance tag.
    """
    path = Path(path)

    export = path / LEDGER_EXPORT
    if export.is_file():
        rows = read_jsonl(export)
        for row in rows:
            row.setdefault("verdicts", [])
            row.setdefault("_slug", path.name)
        return rows

    claims_path = path / "claims.jsonl"
    if not claims_path.is_file():
        return []

    verdicts_by_claim: dict[str, list[dict]] = {}
    for verdict in read_jsonl(path / "verdicts.jsonl"):
        verdicts_by_claim.setdefault(verdict.get("claim_id"), []).append(verdict)

    rows = read_jsonl(claims_path)
    for row in rows:
        row["verdicts"] = verdicts_by_claim.get(row.get("id"), [])
        row.setdefault("_slug", path.name)
    return rows


def carry_forward(prior: list[dict], now: datetime) -> list[dict]:
    """Keep only claims every validator confirmed. Re-id and mark for re-validation."""
    carried: list[dict] = []
    seen_urls: set[str] = set()

    for row in prior:
        if row.get("source_type") == "internal" or not row.get("url"):
            continue

        verdicts = row.get("verdicts") or []
        if not verdicts:
            continue
        if any(v.get("verdict") != "CONFIRMED" for v in verdicts):
            continue

        url_key = row["url"].split("#", 1)[0].rstrip("/")
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)

        carried.append({
            "id": f"C{len(carried) + 1:03d}",
            "sub_q": row.get("sub_q"),
            "tier": row.get("tier"),
            "claim": row.get("claim"),
            "url": row.get("url"),
            "quote": row.get("quote"),
            "source_type": row.get("source_type"),
            "origin": {
                "slug": row.get("_slug"),
                "claim_id": row.get("id"),
                "fetched_at": row.get("fetched_at"),
            },
            "stale": is_stale(row.get("fetched_at"), now),
            "needs_revalidation": True,
        })

    return carried
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_ingest_lane1.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): carry verified claims forward from prior runs"
```

---
### Task 8: Ingestion lanes 2-4 — internal firewall, ranking, budget, CLI

**Files:**
- Modify: `plugins/proposal-research/scripts/ingest_context.py` (append lanes 2-4 and the CLI)
- Create: `plugins/proposal-research/tests/test_ingest_lanes234.py`

**Interfaces:**
- Consumes: `ingest_context.carry_forward`, `load_prior_ledger` (Task 7); `workspace.append_jsonl`, `workspace.utc_now` (Task 1)
- Produces:
  - `ingest_context.DEFAULT_LIMIT = 25`
  - `ingest_context.parse_frontmatter(text: str) -> tuple[dict, str]`
  - `ingest_context.discover_notes(paths: list[Path]) -> list[Path]`
  - `ingest_context.score_note(path: Path, meta: dict, question: str) -> int`
  - `ingest_context.rank_notes(notes: list[Path], question: str, limit: int) -> list[Path]`
  - `ingest_context.to_internal_claims(notes: list[Path], lane: int) -> list[dict]`
  - `ingest_context.main(argv) -> int` — CLI writing `carried-claims.jsonl`, `internal-claims.jsonl`, `ingest-report.md`

- [ ] **Step 1: Write the failing test**

Create `plugins/proposal-research/tests/test_ingest_lanes234.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ingest_context  # noqa: E402

QUESTION = "ServiceNow agent via Copilot Studio MCP versus native AI Agent Studio"


def note(dir_path: Path, name: str, body: str = "Some body text.", frontmatter: str = "") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text((frontmatter + "\n" if frontmatter else "") + body, encoding="utf-8")
    return path


# --- frontmatter --------------------------------------------------------

def test_parse_frontmatter_reads_scalars_and_lists():
    text = "---\ntitle: My Note\ntags: [alpha, beta]\n---\n\nBody here.\n"
    meta, body = ingest_context.parse_frontmatter(text)
    assert meta["title"] == "My Note"
    assert meta["tags"] == ["alpha", "beta"]
    assert body.strip() == "Body here."


def test_parse_frontmatter_absent_returns_empty_meta():
    meta, body = ingest_context.parse_frontmatter("Just body.\n")
    assert meta == {}
    assert body.strip() == "Just body."


def test_parse_frontmatter_strips_quotes():
    meta, _ = ingest_context.parse_frontmatter('---\ntitle: "Quoted"\n---\nx\n')
    assert meta["title"] == "Quoted"


# --- discovery and ranking ---------------------------------------------

def test_discover_notes_finds_markdown_recursively(tmp_path):
    note(tmp_path / "a", "one.md")
    note(tmp_path / "a" / "b", "two.md")
    note(tmp_path / "a", "ignored.txt")
    found = ingest_context.discover_notes([tmp_path])
    assert {p.name for p in found} == {"one.md", "two.md"}


def test_discover_notes_skips_obsidian_config(tmp_path):
    note(tmp_path / ".obsidian", "workspace.md")
    note(tmp_path, "real.md")
    assert {p.name for p in ingest_context.discover_notes([tmp_path])} == {"real.md"}


def test_discover_notes_missing_path_is_skipped(tmp_path):
    assert ingest_context.discover_notes([tmp_path / "nope"]) == []


def test_score_note_rewards_question_terms_in_title(tmp_path):
    p = note(tmp_path, "copilot-studio-mcp.md")
    high = ingest_context.score_note(p, {"title": "Copilot Studio MCP limits"}, QUESTION)
    low = ingest_context.score_note(p, {"title": "Cafeteria menu"}, QUESTION)
    assert high > low


def test_rank_notes_respects_limit(tmp_path):
    for i in range(10):
        note(tmp_path, f"servicenow-{i}.md")
    assert len(ingest_context.rank_notes(ingest_context.discover_notes([tmp_path]), QUESTION, 3)) == 3


def test_rank_notes_is_deterministic(tmp_path):
    for i in range(6):
        note(tmp_path, f"copilot-{i}.md")
    notes = ingest_context.discover_notes([tmp_path])
    assert ingest_context.rank_notes(notes, QUESTION, 4) == ingest_context.rank_notes(notes, QUESTION, 4)


# --- the firewall -------------------------------------------------------

def test_internal_claims_are_never_material(tmp_path):
    p = note(tmp_path, "n.md", "Copilot Studio supports 200 tools per server.")
    rows = ingest_context.to_internal_claims([p], lane=2)
    assert rows[0]["tier"] == "context"


def test_internal_claims_have_internal_source_type_and_null_url(tmp_path):
    p = note(tmp_path, "n.md")
    row = ingest_context.to_internal_claims([p], lane=2)[0]
    assert row["source_type"] == "internal"
    assert row["url"] is None


def test_internal_claims_carry_the_unverified_verdict(tmp_path):
    p = note(tmp_path, "n.md")
    assert ingest_context.to_internal_claims([p], lane=2)[0]["verdict"] == "INTERNAL_UNVERIFIED"


def test_internal_claims_record_their_lane_and_path(tmp_path):
    p = note(tmp_path, "n.md")
    row = ingest_context.to_internal_claims([p], lane=3)[0]
    assert row["lane"] == 3
    assert row["source_path"] == str(p)


def test_internal_claim_ids_are_prefixed_to_avoid_ledger_collision(tmp_path):
    p = note(tmp_path, "n.md")
    assert ingest_context.to_internal_claims([p], lane=2)[0]["id"].startswith("I")


# --- CLI ----------------------------------------------------------------

def test_main_writes_internal_claims_and_report(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    ctx_dir = tmp_path / "notes"
    note(ctx_dir, "copilot-studio.md", "Prior notes on Copilot Studio.")

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(ctx_dir), "--limit", "5",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert rows and rows[0]["source_type"] == "internal"
    assert "Ingestion Report" in (ws / "ingest-report.md").read_text()


def test_main_writes_carried_claims_from_prior_run(tmp_path):
    prior = tmp_path / "research" / "prior"
    prior.mkdir(parents=True)
    (prior / "claims.jsonl").write_text(json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material", "claim": "x",
        "url": "https://learn.microsoft.com/a", "quote": "q",
        "source_type": "vendor_doc", "fetched_at": "2026-08-20T00:00:00Z",
    }) + "\n")
    (prior / "verdicts.jsonl").write_text("".join(json.dumps(v) + "\n" for v in [
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v1",
         "validator_model": "haiku", "quote": "q"},
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v2",
         "validator_model": "sonnet", "quote": "q"},
    ]))

    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION, "--prior", str(prior),
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "carried-claims.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["needs_revalidation"] is True


def test_main_enforces_the_note_budget(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    ctx_dir = tmp_path / "notes"
    for i in range(40):
        note(ctx_dir, f"servicenow-note-{i}.md")

    ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(ctx_dir), "--limit", "25",
    ])
    rows = [l for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 25


def test_main_with_no_sources_writes_empty_ledgers(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    assert ingest_context.main(["--workspace", str(ws), "--question", QUESTION]) == 0
    assert (ws / "ingest-report.md").is_file()


def test_earlier_lane_wins_on_duplicate_note(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    shared = tmp_path / "shared"
    note(shared, "copilot.md")

    ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(shared), "--configured-vault", str(shared),
    ])
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["lane"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_ingest_lanes234.py -v`
Expected: FAIL — `AttributeError: module 'ingest_context' has no attribute 'parse_frontmatter'`

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/proposal-research/scripts/ingest_context.py`:

```python
import argparse
import json
import re

from workspace import utc_now  # noqa: E402

DEFAULT_LIMIT = 25
SKIP_DIRS = {".obsidian", ".git", "node_modules", ".venv", "__pycache__"}
_WORD_RE = re.compile(r"[a-z0-9]+")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML front matter: `key: value` and `key: [a, b]`. Stdlib only."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}, text

    meta: dict = {}
    for line in parts[0].lstrip("-").splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key, raw = key.strip(), raw.strip()
        if not key:
            continue
        if raw.startswith("[") and raw.endswith("]"):
            meta[key] = [v.strip().strip("\"'") for v in raw[1:-1].split(",") if v.strip()]
        else:
            meta[key] = raw.strip("\"'")
    return meta, parts[1].lstrip("-\n")


def discover_notes(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for base in paths:
        base = Path(base)
        if not base.exists():
            continue
        if base.is_file() and base.suffix == ".md":
            found.append(base)
            continue
        for path in sorted(base.rglob("*.md")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            found.append(path)
    return found


def score_note(path: Path, meta: dict, question: str) -> int:
    """Term overlap between the question and the note's identifying text."""
    q_terms = set(_WORD_RE.findall(question.lower()))
    haystack = " ".join([
        path.stem.replace("-", " ").replace("_", " "),
        str(meta.get("title", "")),
        " ".join(meta.get("tags", []) if isinstance(meta.get("tags"), list) else []),
    ]).lower()
    return len(q_terms & set(_WORD_RE.findall(haystack)))


def rank_notes(notes: list[Path], question: str, limit: int) -> list[Path]:
    scored = []
    for path in notes:
        try:
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            meta = {}
        scored.append((-score_note(path, meta, question), str(path), path))
    scored.sort()
    return [path for _, _, path in scored[:limit]]


def to_internal_claims(notes: list[Path], lane: int) -> list[dict]:
    """Internal material can steer research but can never become evidence.

    tier is forced to 'context' and source_type to 'internal', so the gate's
    material-claim rules can never admit one.
    """
    rows = []
    for index, path in enumerate(notes, start=1):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        rows.append({
            "id": f"I{index:03d}",
            "tier": "context",
            "source_type": "internal",
            "url": None,
            "verdict": "INTERNAL_UNVERIFIED",
            "lane": lane,
            "source_path": str(path),
            "title": meta.get("title") or path.stem,
            "excerpt": " ".join(body.split())[:600],
            "ingested_at": utc_now(),
        })
    return rows


def _render_report(carried: list[dict], internal: list[dict], limit: int) -> str:
    stale = sum(1 for row in carried if row.get("stale"))
    by_lane: dict[int, int] = {}
    for row in internal:
        by_lane[row["lane"]] = by_lane.get(row["lane"], 0) + 1

    lines = [
        "# Ingestion Report",
        "",
        "## Lane 1 — carried forward (public, re-validated this run)",
        "",
        f"- Claims carried: {len(carried)}",
        f"- Flagged stale (>{STALE_DAYS} days): {stale}",
        "",
        "Every carried claim is re-validated in this run, so it passes the same gate as",
        "a freshly researched claim. The saving is skipping discovery, not verification.",
        "",
        "## Lanes 2-4 — internal (steer only, never evidence)",
        "",
        f"- Notes ingested: {len(internal)} (budget {limit})",
    ]
    for lane in sorted(by_lane):
        lines.append(f"- Lane {lane}: {by_lane[lane]} notes")
    lines += [
        "",
        "Internal claims are `tier: context`, `source_type: internal`, verdict",
        "`INTERNAL_UNVERIFIED`. They seed sub-questions for the planner. They cannot",
        "ground a capability, price, limit, or regulation. A claim may be promoted only",
        "if a researcher independently finds a public source for it.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble local context for a research run")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--prior", action="append", default=[], help="prior run workspace or vault (lane 1)")
    parser.add_argument("--context", action="append", default=[], help="per-run path (lane 2)")
    parser.add_argument("--configured-vault", default=None, help="standing proposals vault (lane 3)")
    parser.add_argument("--repo", default=None, help="working repo whose docs/ and README are read (lane 4)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)

    ws = Path(args.workspace)
    ws.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)

    # Lane 1 — public carry-forward
    prior_rows: list[dict] = []
    for path in args.prior:
        prior_rows.extend(load_prior_ledger(Path(path)))
    carried = carry_forward(prior_rows, now)

    # Lanes 2-4 — internal, earlier lanes win on duplicates
    lane_paths: list[tuple[int, list[Path]]] = [(2, [Path(p) for p in args.context])]
    if args.configured_vault:
        lane_paths.append((3, [Path(args.configured_vault)]))
    if args.repo:
        repo = Path(args.repo)
        lane_paths.append((4, [repo / "docs", repo / "README.md"]))

    internal: list[dict] = []
    claimed: set[str] = set()
    remaining = args.limit
    for lane, paths in lane_paths:
        if remaining <= 0:
            break
        notes = [n for n in discover_notes(paths) if str(n.resolve()) not in claimed]
        chosen = rank_notes(notes, args.question, remaining)
        claimed.update(str(n.resolve()) for n in chosen)
        rows = to_internal_claims(chosen, lane)
        for offset, row in enumerate(rows, start=len(internal) + 1):
            row["id"] = f"I{offset:03d}"
        internal.extend(rows)
        remaining -= len(rows)

    _write_rows(ws / "carried-claims.jsonl", carried)
    _write_rows(ws / "internal-claims.jsonl", internal)
    (ws / "ingest-report.md").write_text(
        _render_report(carried, internal, args.limit), encoding="utf-8")

    print(f"OK: {len(carried)} carried, {len(internal)} internal notes ingested")
    return 0


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): internal ingestion lanes with a firewall and note budget"
```

---
### Task 9: Vault builder, part 1 — template, pack contract, MOC and findings

The synthesizer's pack must follow a fixed H2 section contract so the builder can file it
deterministically. The contract is enforced here (missing sections are a build error) and
stated in the synthesizer's agent prompt in Task 12.

**Pack section contract:**

| Pack section (H2) | Becomes |
|---|---|
| `## Summary` | `00-MOC/Proposal Brief.md` body |
| `## Recommendation` | `00-MOC/Decision Cheatsheet.md` |
| `## Findings` | `01-Findings/<h3>.md`, one note per H3 |
| `## Options` | `02-Options/<h3>.md`, one note per H3 |
| `## Constraints` | `03-Constraints/<h3>.md`, one note per H3 |
| `## Open Questions` | `04-Risks-and-Gaps/Open Questions.md` |
| `## Unverified & excluded` | `04-Risks-and-Gaps/Unverified Claims.md` |

**Files:**
- Create: `plugins/proposal-research/templates/vault/.obsidian/app.json`
- Create: `plugins/proposal-research/templates/vault/.obsidian/appearance.json`
- Create: `plugins/proposal-research/templates/vault/.obsidian/core-plugins.json`
- Create: `plugins/proposal-research/templates/vault/.obsidian/graph.json`
- Create: `plugins/proposal-research/scripts/build_vault.py`
- Create: `plugins/proposal-research/tests/test_build_vault.py`

**Interfaces:**
- Consumes: `workspace.read_jsonl` (Task 1); `fixtures.build.make_workspace` (Task 4)
- Produces:
  - `build_vault.VAULT_DIRS` — ordered folder names
  - `build_vault.SECTION_MAP` — H2 heading -> destination
  - `build_vault.parse_sections(text: str) -> dict[str, str]`
  - `build_vault.split_subsections(text: str) -> list[tuple[str, str]]`
  - `build_vault.note_filename(title: str) -> str`
  - `build_vault.render_note(title: str, tags: list[str], body: str, meta: dict | None = None) -> str`
  - `build_vault.copy_obsidian_config(vault: Path) -> None`
  - `build_vault.build(workspace: Path, include_proposal: bool = False) -> Path`

- [ ] **Step 1: Write the .obsidian template files**

Create `plugins/proposal-research/templates/vault/.obsidian/app.json`:

```json
{}
```

Create `plugins/proposal-research/templates/vault/.obsidian/appearance.json`:

```json
{}
```

Create `plugins/proposal-research/templates/vault/.obsidian/core-plugins.json`:

```json
{
  "file-explorer": true,
  "global-search": true,
  "switcher": true,
  "graph": true,
  "backlink": true,
  "outgoing-link": true,
  "tag-pane": true,
  "properties": true,
  "page-preview": true,
  "outline": true,
  "word-count": true,
  "command-palette": true,
  "bookmarks": true,
  "note-composer": true,
  "templates": true,
  "canvas": false,
  "daily-notes": false,
  "footnotes": false,
  "slides": false,
  "audio-recorder": false,
  "workspaces": false,
  "random-note": false,
  "zk-prefixer": false,
  "markdown-importer": false
}
```

Create `plugins/proposal-research/templates/vault/.obsidian/graph.json`:

```json
{
  "collapse-filter": true,
  "search": "",
  "showTags": false,
  "showAttachments": false,
  "hideUnresolved": false,
  "showOrphans": true,
  "collapse-color-groups": true,
  "colorGroups": [],
  "collapse-display": true,
  "showArrow": false,
  "textFadeMultiplier": 0,
  "nodeSizeMultiplier": 1,
  "lineSizeMultiplier": 1,
  "collapse-forces": true,
  "centerStrength": 0.5187132489703125,
  "repelStrength": 10,
  "linkStrength": 1,
  "linkDistance": 250,
  "scale": 1,
  "close": false
}
```

- [ ] **Step 2: Write the failing test**

Create `plugins/proposal-research/tests/test_build_vault.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_vault  # noqa: E402
from fixtures import build as fx  # noqa: E402

FULL_PACK = """# Evidence Pack: ServiceNow Agent Platform

## Summary

Two candidate architectures were assessed against the client's Microsoft estate [C001].

## Recommendation

Copilot Studio with an MCP server is the stronger fit given the tool cap [C001].

## Findings

### MCP tool limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

### Native agent positioning

ServiceNow positions AI Agent Studio for platform-native agents [C002].

## Options

### Copilot Studio with MCP

Strong Microsoft alignment [C001].

### ServiceNow native AI Agent Studio

Platform-native but a separate licence [C002].

## Constraints

### Licensing

Tool caps constrain the design [C001].

## Open Questions

- Regional GA status for the MCP connector

## Unverified & excluded

Nothing was excluded in this run.
"""


def make_ws(tmp_path, pack=FULL_PACK):
    return fx.make_workspace(tmp_path, pack=pack)


# --- parsing ------------------------------------------------------------

def test_parse_sections_finds_every_h2():
    sections = build_vault.parse_sections(FULL_PACK)
    assert set(sections) >= {
        "Summary", "Recommendation", "Findings", "Options",
        "Constraints", "Open Questions", "Unverified & excluded",
    }


def test_parse_sections_captures_body_text():
    assert "[C001]" in build_vault.parse_sections(FULL_PACK)["Summary"]


def test_split_subsections_splits_on_h3():
    findings = build_vault.parse_sections(FULL_PACK)["Findings"]
    subs = build_vault.split_subsections(findings)
    assert [t for t, _ in subs] == ["MCP tool limits", "Native agent positioning"]


def test_split_subsections_with_no_h3_returns_empty():
    assert build_vault.split_subsections("Just prose, no headings.\n") == []


def test_note_filename_is_filesystem_safe():
    assert build_vault.note_filename("MCP tool limits") == "MCP tool limits.md"
    assert "/" not in build_vault.note_filename("A/B: limits?")


def test_render_note_emits_frontmatter_and_title():
    out = build_vault.render_note("My Note", ["finding", "proposal-research"], "Body [C001].")
    assert out.startswith("---\n")
    assert "tags: [finding, proposal-research]" in out
    assert "# My Note" in out
    assert "Body [C001]." in out


# --- build --------------------------------------------------------------

def test_build_creates_the_folder_skeleton(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    for name in build_vault.VAULT_DIRS:
        assert (vault / name).is_dir(), name


def test_build_copies_obsidian_config(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / ".obsidian" / "core-plugins.json").is_file()
    assert (vault / ".obsidian" / "graph.json").is_file()


def test_build_writes_proposal_brief_with_wikilinks(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    brief = (vault / "00-MOC" / "Proposal Brief.md").read_text()
    assert "[[MCP tool limits]]" in brief
    assert "[[Sources]]" in brief


def test_build_writes_decision_cheatsheet(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "00-MOC" / "Decision Cheatsheet.md").read_text()
    assert "Copilot Studio with an MCP server" in text


def test_build_writes_one_note_per_finding(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    names = sorted(p.name for p in (vault / "01-Findings").glob("*.md"))
    assert names == ["MCP tool limits.md", "Native agent positioning.md"]


def test_finding_notes_carry_their_citations(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "[C001]" in (vault / "01-Findings" / "MCP tool limits.md").read_text()


def test_build_is_idempotent(tmp_path):
    ws = make_ws(tmp_path)
    build_vault.build(ws)
    vault = build_vault.build(ws)
    assert len(list((vault / "01-Findings").glob("*.md"))) == 2


def test_build_rejects_a_pack_missing_required_sections(tmp_path):
    ws = make_ws(tmp_path, pack="# Evidence Pack\n\n## Summary\n\nOnly a summary.\n")
    try:
        build_vault.build(ws)
    except ValueError as exc:
        assert "Findings" in str(exc)
    else:
        raise AssertionError("expected ValueError for incomplete pack")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_build_vault.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_vault'`

- [ ] **Step 4: Write minimal implementation**

Create `plugins/proposal-research/scripts/build_vault.py`:

```python
#!/usr/bin/env python3
"""Phase 5b/7b — file the evidence pack into a self-contained Obsidian vault.

Deterministic on purpose. Fable writes the prose; this script does the filing,
wikilinking and anchor generation. A model that files its own citations can
misfile them, and that would put a hole in the provenance guarantee at the very
last step.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import read_jsonl  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "vault"

VAULT_DIRS = [
    "00-MOC",
    "01-Findings",
    "02-Options",
    "03-Constraints",
    "04-Risks-and-Gaps",
    "05-Proposal",
    "06-Sources",
]

REQUIRED_SECTIONS = ["Summary", "Recommendation", "Findings", "Options", "Constraints"]

SECTION_MAP = {
    "Findings": ("01-Findings", "finding"),
    "Options": ("02-Options", "option"),
    "Constraints": ("03-Constraints", "constraint"),
}

_UNSAFE = re.compile(r"[/\\:*?\"<>|]")


def parse_sections(text: str) -> dict[str, str]:
    """Split markdown on H2 headings into {heading: body}."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def split_subsections(text: str) -> list[tuple[str, str]]:
    """Split a section body on H3 headings into [(title, body)]."""
    subs: list[tuple[str, str]] = []
    current: str | None = None
    buffer: list[str] = []
    for line in (text or "").splitlines():
        if line.startswith("### "):
            if current is not None:
                subs.append((current, "\n".join(buffer).strip()))
            current = line[4:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        subs.append((current, "\n".join(buffer).strip()))
    return subs


def note_filename(title: str) -> str:
    return f"{_UNSAFE.sub('-', title).strip()}.md"


def render_note(title: str, tags: list[str], body: str, meta: dict | None = None) -> str:
    lines = ["---", f"tags: [{', '.join(tags)}]"]
    for key, value in (meta or {}).items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", f"# {title}", "", body.strip(), ""]
    return "\n".join(lines)


def copy_obsidian_config(vault: Path) -> None:
    source = TEMPLATE_ROOT / ".obsidian"
    target = vault / ".obsidian"
    target.mkdir(parents=True, exist_ok=True)
    for item in source.glob("*.json"):
        shutil.copy2(item, target / item.name)


def _clear_generated(vault: Path) -> None:
    """Idempotency: drop previously generated notes before rewriting."""
    for name in VAULT_DIRS:
        folder = vault / name
        if folder.is_dir():
            for note in folder.glob("*.md"):
                note.unlink()


def build(workspace: Path, include_proposal: bool = False) -> Path:
    workspace = Path(workspace)
    pack_text = (workspace / "evidence-pack.md").read_text(encoding="utf-8")
    sections = parse_sections(pack_text)

    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        raise ValueError(
            f"evidence-pack.md is missing required section(s): {', '.join(missing)}. "
            f"The synthesizer must emit the fixed H2 contract."
        )

    vault = workspace / "vault"
    for name in VAULT_DIRS:
        (vault / name).mkdir(parents=True, exist_ok=True)
    copy_obsidian_config(vault)
    _clear_generated(vault)

    claims = {r["id"]: r for r in read_jsonl(workspace / "claims.jsonl") if "id" in r}

    # Sectioned notes
    linked_titles: dict[str, list[str]] = {}
    for heading, (folder, tag) in SECTION_MAP.items():
        titles = []
        for title, body in split_subsections(sections.get(heading, "")):
            (vault / folder / note_filename(title)).write_text(
                render_note(title, [tag, "proposal-research"], body),
                encoding="utf-8",
            )
            titles.append(title)
        linked_titles[heading] = titles

    # 00-MOC
    (vault / "00-MOC" / "Decision Cheatsheet.md").write_text(
        render_note("Decision Cheatsheet", ["moc", "recommendation", "proposal-research"],
                    sections["Recommendation"]),
        encoding="utf-8",
    )
    (vault / "00-MOC" / "Proposal Brief.md").write_text(
        _render_brief(sections, linked_titles, claims, include_proposal),
        encoding="utf-8",
    )

    # 04-Risks-and-Gaps
    (vault / "04-Risks-and-Gaps" / "Open Questions.md").write_text(
        render_note("Open Questions", ["gap", "proposal-research"],
                    sections.get("Open Questions", "_None recorded._")),
        encoding="utf-8",
    )
    (vault / "04-Risks-and-Gaps" / "Unverified Claims.md").write_text(
        render_note("Unverified Claims", ["unverified", "proposal-research"],
                    sections.get("Unverified & excluded", "_Nothing was excluded._")),
        encoding="utf-8",
    )

    return vault


def _render_brief(sections: dict, linked_titles: dict, claims: dict,
                  include_proposal: bool) -> str:
    lines = [sections["Summary"], "", "## Contents", ""]
    lines.append("- [[Decision Cheatsheet]]")
    for heading, (_folder, _tag) in SECTION_MAP.items():
        for title in linked_titles.get(heading, []):
            lines.append(f"- [[{title}]]")
    lines += [
        "- [[Open Questions]]",
        "- [[Unverified Claims]]",
        "- [[Sources]]",
        "- [[Research Log]]",
    ]
    if include_proposal:
        lines.append("- [[Draft Proposal]]")
    lines += ["", "## Quick facts", "", "| Item | Value |", "|---|---|",
              f"| Claims in ledger | {len(claims)} |"]
    return render_note("Proposal Brief", ["moc", "proposal-research"], "\n".join(lines))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_build_vault.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 6: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): vault skeleton, pack section contract, MOC and findings"
```

---
### Task 10: Vault builder, part 2 — Sources, reliability notes, log, ledger export

`06-Sources/ledger-export.jsonl` is what makes a copied-out vault self-sufficient as a lane-1
ingestion source for future runs. Its round trip through `ingest_context.load_prior_ledger` is
tested here.

**Files:**
- Modify: `plugins/proposal-research/scripts/build_vault.py` (append renderers; call them from `build`)
- Modify: `plugins/proposal-research/tests/test_build_vault.py` (append tests)

**Interfaces:**
- Consumes: `build_vault.render_note`, `build` (Task 9); `ingest_context.load_prior_ledger` (Task 7)
- Produces:
  - `build_vault.SOURCE_GROUPS` — ordered `[(source_type, human label)]`
  - `build_vault.render_sources(claims: dict, verdicts: dict) -> str`
  - `build_vault.render_reliability_notes(claims: dict, verdicts: dict) -> str`
  - `build_vault.render_research_log(claims: dict, verdicts: dict, fetches: list, gaps: str) -> str`
  - `build_vault.write_ledger_export(vault: Path, claims: dict, verdicts: dict) -> Path`

- [ ] **Step 1: Write the failing test**

Append to `plugins/proposal-research/tests/test_build_vault.py`:

```python
import json  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ingest_context  # noqa: E402


# --- Sources.md ---------------------------------------------------------

def test_sources_note_is_written(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / "06-Sources" / "Sources.md").is_file()


def test_sources_groups_by_source_type(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert "## Vendor documentation" in text


def test_sources_has_an_anchor_per_claim(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert "### C001" in text
    assert "### C002" in text


def test_sources_shows_url_and_quote(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert fx.URL_A in text
    assert "A maximum of 10 tools" in text


# --- reliability notes --------------------------------------------------

def test_reliability_section_is_present_even_when_clean(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "Notes on source reliability" in (vault / "06-Sources" / "Sources.md").read_text()


def test_contradicted_claim_appears_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[2].update(verdict="CONTRADICTED")
    verdicts[2].pop("quote", None)
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    assert "C002" in text.split("Notes on source reliability")[1]


def test_misleading_caveat_appears_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    assert "Public preview only, not GA." in text


def test_disagreeing_validators_appear_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[1].update(verdict="MISLEADING", caveat="Preview in some regions.")
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    section = text.split("Notes on source reliability")[1]
    assert "C001" in section and "disagree" in section.lower()


# --- Research Log -------------------------------------------------------

def test_research_log_reports_verdict_counts(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Research Log.md").read_text()
    assert "CONFIRMED" in text and "3" in text


def test_research_log_reports_fetch_total(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "Fetches recorded" in (vault / "06-Sources" / "Research Log.md").read_text()


# --- ledger export ------------------------------------------------------

def test_ledger_export_is_written(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / "06-Sources" / "ledger-export.jsonl").is_file()


def test_ledger_export_merges_verdicts_into_claim_rows(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    rows = [json.loads(l) for l in
            (vault / "06-Sources" / "ledger-export.jsonl").read_text().splitlines() if l.strip()]
    by_id = {r["id"]: r for r in rows}
    assert len(by_id["C001"]["verdicts"]) == 2


def test_exported_vault_round_trips_as_a_lane_one_source(tmp_path):
    """A copied-out vault must be ingestable by a future run."""
    vault = build_vault.build(make_ws(tmp_path))
    rows = ingest_context.load_prior_ledger(vault)
    assert {r["id"] for r in rows} == {"C001", "C002"}
    from datetime import datetime, timezone
    carried = ingest_context.carry_forward(rows, datetime.now(timezone.utc))
    assert [c["origin"]["claim_id"] for c in carried] == ["C001", "C002"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_build_vault.py -v`
Expected: FAIL — `AssertionError` on `06-Sources/Sources.md` not existing

- [ ] **Step 3: Write minimal implementation**

Append to `plugins/proposal-research/scripts/build_vault.py`:

```python
import json  # noqa: E402

SOURCE_GROUPS = [
    ("vendor_doc", "Vendor documentation"),
    ("regulator", "Regulator and official guidance"),
    ("analyst", "Analyst and research firms"),
    ("blog", "Blogs and articles"),
    ("forum", "Forums and community"),
    ("internal", "Internal notes (unverified)"),
]


def render_sources(claims: dict, verdicts: dict) -> str:
    lines: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for claim in claims.values():
        grouped.setdefault(claim.get("source_type", "unknown"), []).append(claim)

    for source_type, label in SOURCE_GROUPS:
        rows = sorted(grouped.get(source_type, []), key=lambda c: c["id"])
        if not rows:
            continue
        lines += [f"## {label}", ""]
        for claim in rows:
            rulings = verdicts.get(claim["id"], [])
            verdict_summary = ", ".join(r.get("verdict", "?") for r in rulings) or "no verdict"
            lines += [
                f"### {claim['id']}",
                "",
                f"**Claim.** {claim.get('claim', '')}",
                "",
                f"**Source.** {claim.get('url') or '_internal note, no URL_'}",
                "",
                f"> {claim.get('quote', '')}",
                "",
                f"*Verdict:* {verdict_summary} · *Retrieved:* {claim.get('fetched_at', 'unknown')}",
                "",
            ]

    lines += render_reliability_notes(claims, verdicts).splitlines()
    return "\n".join(lines)


def render_reliability_notes(claims: dict, verdicts: dict) -> str:
    """Derived from the verdicts, not noticed by hand.

    The pipeline had to record each disagreement in order to rule on a claim, so
    the conflicts fall out for free.
    """
    lines = ["## Notes on source reliability", ""]
    entries: list[str] = []

    for claim_id, rulings in sorted(verdicts.items()):
        claim = claims.get(claim_id)
        if claim is None:
            continue
        seen = {r.get("verdict") for r in rulings}
        url = claim.get("url") or "internal note"

        if "CONTRADICTED" in seen:
            entries.append(
                f"- **{claim_id} — contradicted.** The cited page does not support this "
                f"claim: {url}. Excluded from the pack body."
            )
        for ruling in rulings:
            if ruling.get("verdict") == "MISLEADING" and ruling.get("caveat"):
                entries.append(
                    f"- **{claim_id} — misleading without its caveat.** {ruling['caveat']} "
                    f"Source: {url}"
                )
        if len(seen) > 1:
            entries.append(
                f"- **{claim_id} — validators disagree.** Rulings were "
                f"{', '.join(sorted(v for v in seen if v))}. Treat with care and re-check "
                f"before quoting to a client."
            )

    if entries:
        lines += entries
    else:
        lines.append("- No contradictions, caveats, or validator disagreements were recorded.")
    lines.append("")
    return "\n".join(lines)


def render_research_log(claims: dict, verdicts: dict, fetches: list, gaps: str) -> str:
    verdict_counts: dict[str, int] = {}
    for rulings in verdicts.values():
        for ruling in rulings:
            key = ruling.get("verdict", "unknown")
            verdict_counts[key] = verdict_counts.get(key, 0) + 1

    agents = {f.get("agent_id") for f in fetches if f.get("agent_id")}

    lines = [
        "## Totals",
        "",
        f"- Claims in ledger: {len(claims)}",
        f"- Fetches recorded: {len(fetches)}",
        f"- Distinct agents that fetched: {len(agents)}",
        "",
        "## Verdicts",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(verdict_counts.items())] or ["- none"]
    lines += ["", "## Gap rounds", "", gaps.strip() or "_No gap rounds recorded._", ""]
    return "\n".join(lines)


def write_ledger_export(vault: Path, claims: dict, verdicts: dict) -> Path:
    """Self-sufficient export so a copied-out vault can seed a future run."""
    path = vault / "06-Sources" / "ledger-export.jsonl"
    path.write_text(
        "".join(
            json.dumps({**claim, "verdicts": verdicts.get(claim_id, [])}, ensure_ascii=False) + "\n"
            for claim_id, claim in sorted(claims.items())
        ),
        encoding="utf-8",
    )
    return path
```

- [ ] **Step 4: Wire the renderers into `build`**

In `plugins/proposal-research/scripts/build_vault.py`, inside `build()`, replace the line:

```python
    return vault
```

with:

```python
    # 06-Sources
    verdicts: dict[str, list[dict]] = {}
    for row in read_jsonl(workspace / "verdicts.jsonl"):
        verdicts.setdefault(row.get("claim_id"), []).append(row)
    fetches = read_jsonl(workspace / "fetch-log.jsonl")
    gaps_path = workspace / "gaps.md"
    gaps = gaps_path.read_text(encoding="utf-8") if gaps_path.is_file() else ""

    (vault / "06-Sources" / "Sources.md").write_text(
        render_note("Sources", ["sources", "proposal-research"],
                    render_sources(claims, verdicts)),
        encoding="utf-8",
    )
    (vault / "06-Sources" / "Research Log.md").write_text(
        render_note("Research Log", ["log", "proposal-research"],
                    render_research_log(claims, verdicts, fetches, gaps)),
        encoding="utf-8",
    )
    write_ledger_export(vault, claims, verdicts)

    return vault
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_build_vault.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 6: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): derived source reliability notes, research log, ledger export"
```

---
### Task 11: Vault builder, part 3 — citation links, link integrity, proposal, CLI

**Files:**
- Modify: `plugins/proposal-research/scripts/build_vault.py` (append linkify, link check, proposal, CLI)
- Modify: `plugins/proposal-research/tests/test_build_vault.py` (append tests)

**Interfaces:**
- Consumes: everything from Tasks 9 and 10
- Produces:
  - `build_vault.linkify_citations(body: str, depth: int = 1) -> str`
  - `build_vault.check_links(vault: Path) -> list[str]`
  - `build_vault.main(argv) -> int` — CLI `build_vault.py --workspace DIR [--with-proposal] [--copy-to DIR]`

- [ ] **Step 1: Write the failing test**

Append to `plugins/proposal-research/tests/test_build_vault.py`:

```python
# --- citation links -----------------------------------------------------

def test_linkify_turns_citations_into_relative_links():
    out = build_vault.linkify_citations("A claim [C001].", depth=1)
    assert out == "A claim [C001](../06-Sources/Sources.md#C001)."


def test_linkify_preserves_the_bracketed_id_for_the_gate():
    assert "[C001]" in build_vault.linkify_citations("x [C001]", depth=1)


def test_linkify_handles_multiple_citations():
    out = build_vault.linkify_citations("[C001] and [C002]", depth=1)
    assert out.count("06-Sources/Sources.md#") == 2


def test_linkify_at_depth_zero_uses_local_path():
    assert "(06-Sources/Sources.md#C001)" in build_vault.linkify_citations("[C001]", depth=0)


def test_linkify_does_not_double_link(tmp_path):
    once = build_vault.linkify_citations("[C001]", depth=1)
    assert build_vault.linkify_citations(once, depth=1) == once


def test_finding_notes_have_linked_citations(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "01-Findings" / "MCP tool limits.md").read_text()
    assert "../06-Sources/Sources.md#C001" in text


# --- link integrity -----------------------------------------------------

def test_clean_vault_has_no_broken_links(tmp_path):
    assert build_vault.check_links(build_vault.build(make_ws(tmp_path))) == []


def test_broken_wikilink_is_reported(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    (vault / "01-Findings" / "MCP tool limits.md").write_text("# X\n\nSee [[Nonexistent Note]].\n")
    problems = build_vault.check_links(vault)
    assert any("Nonexistent Note" in p for p in problems)


def test_citation_without_a_sources_anchor_is_reported(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    (vault / "01-Findings" / "MCP tool limits.md").write_text("# X\n\nOrphan [C999].\n")
    assert any("C999" in p for p in build_vault.check_links(vault))


# --- proposal phase -----------------------------------------------------

def test_proposal_note_is_absent_by_default(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert not (vault / "05-Proposal" / "Draft Proposal.md").exists()


def test_proposal_note_is_written_when_requested(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "proposal.md").write_text("# Proposal\n\nWe recommend Copilot Studio [C001].\n")
    vault = build_vault.build(ws, include_proposal=True)
    text = (vault / "05-Proposal" / "Draft Proposal.md").read_text()
    assert "We recommend Copilot Studio" in text
    assert "../06-Sources/Sources.md#C001" in text


def test_brief_links_the_proposal_when_present(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "proposal.md").write_text("# Proposal\n\nText [C001].\n")
    vault = build_vault.build(ws, include_proposal=True)
    assert "[[Draft Proposal]]" in (vault / "00-MOC" / "Proposal Brief.md").read_text()


def test_include_proposal_without_the_file_raises(tmp_path):
    try:
        build_vault.build(make_ws(tmp_path), include_proposal=True)
    except FileNotFoundError as exc:
        assert "proposal.md" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


# --- CLI ----------------------------------------------------------------

def test_main_builds_and_reports_success(tmp_path, capsys):
    ws = make_ws(tmp_path)
    assert build_vault.main(["--workspace", str(ws)]) == 0
    assert "vault" in capsys.readouterr().out


def test_main_fails_on_broken_links(tmp_path):
    ws = make_ws(tmp_path)
    build_vault.build(ws)
    (ws / "vault" / "01-Findings" / "MCP tool limits.md").write_text("# X\n\n[[Ghost]]\n")
    # rebuild would overwrite, so verify check_links directly drives the exit code
    assert build_vault.main(["--workspace", str(ws), "--check-only"]) == 1


def test_main_copies_the_vault_when_asked(tmp_path):
    ws = make_ws(tmp_path)
    dest = tmp_path / "exported"
    assert build_vault.main(["--workspace", str(ws), "--copy-to", str(dest)]) == 0
    assert (dest / "00-MOC" / "Proposal Brief.md").is_file()
    assert (dest / ".obsidian" / "core-plugins.json").is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_build_vault.py -v`
Expected: FAIL — `AttributeError: module 'build_vault' has no attribute 'linkify_citations'`

- [ ] **Step 3: Write linkify and the link checker**

Append to `plugins/proposal-research/scripts/build_vault.py`:

```python
CITATION_RE = re.compile(r"\[(C\d{3,})\](?!\()")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
ANCHOR_RE = re.compile(r"^### (C\d{3,})$", re.MULTILINE)


def linkify_citations(body: str, depth: int = 1) -> str:
    """Turn [C001] into a relative link to its Sources.md anchor.

    The bracketed id is preserved as the link text so the gate's citation regex
    still matches vault notes.
    """
    prefix = "../" * depth
    return CITATION_RE.sub(
        lambda m: f"[{m.group(1)}]({prefix}06-Sources/Sources.md#{m.group(1)})",
        body or "",
    )


def check_links(vault: Path) -> list[str]:
    """Unresolved wikilinks and citations with no anchor in Sources.md."""
    vault = Path(vault)
    notes = [p for p in vault.rglob("*.md") if ".obsidian" not in p.parts]
    titles = {p.stem for p in notes}

    sources = vault / "06-Sources" / "Sources.md"
    anchors = set(ANCHOR_RE.findall(sources.read_text(encoding="utf-8"))) if sources.is_file() else set()

    problems: list[str] = []
    for note in sorted(notes):
        text = note.read_text(encoding="utf-8")
        rel = note.relative_to(vault)
        for target in WIKILINK_RE.findall(text):
            if target.strip() not in titles:
                problems.append(f"{rel}: unresolved wikilink [[{target.strip()}]]")
        for claim_id in re.findall(r"\[(C\d{3,})\]", text):
            if claim_id not in anchors:
                problems.append(f"{rel}: citation [{claim_id}] has no anchor in Sources.md")
    return problems
```

- [ ] **Step 4: Apply linkify to every generated note and add the proposal**

In `build()`, wrap each note body in `linkify_citations`. Specifically:

Replace the sectioned-notes loop body:

```python
            (vault / folder / note_filename(title)).write_text(
                render_note(title, [tag, "proposal-research"], body),
                encoding="utf-8",
            )
```

with:

```python
            (vault / folder / note_filename(title)).write_text(
                render_note(title, [tag, "proposal-research"], linkify_citations(body)),
                encoding="utf-8",
            )
```

Replace the Decision Cheatsheet write with:

```python
    (vault / "00-MOC" / "Decision Cheatsheet.md").write_text(
        render_note("Decision Cheatsheet", ["moc", "recommendation", "proposal-research"],
                    linkify_citations(sections["Recommendation"])),
        encoding="utf-8",
    )
```

Replace the two `04-Risks-and-Gaps` writes with:

```python
    (vault / "04-Risks-and-Gaps" / "Open Questions.md").write_text(
        render_note("Open Questions", ["gap", "proposal-research"],
                    linkify_citations(sections.get("Open Questions", "_None recorded._"))),
        encoding="utf-8",
    )
    (vault / "04-Risks-and-Gaps" / "Unverified Claims.md").write_text(
        render_note("Unverified Claims", ["unverified", "proposal-research"],
                    linkify_citations(sections.get("Unverified & excluded", "_Nothing was excluded._"))),
        encoding="utf-8",
    )
```

And immediately before `return vault`, add the proposal:

```python
    if include_proposal:
        proposal_path = workspace / "proposal.md"
        if not proposal_path.is_file():
            raise FileNotFoundError(
                f"include_proposal was requested but {proposal_path} does not exist; "
                f"run the proposal-writer phase first"
            )
        (vault / "05-Proposal" / "Draft Proposal.md").write_text(
            render_note("Draft Proposal", ["proposal", "proposal-research"],
                        linkify_citations(proposal_path.read_text(encoding="utf-8"))),
            encoding="utf-8",
        )
```

Also linkify the summary inside `_render_brief` — the brief lives in `00-MOC`, one level down, so depth 1 is correct. Change its first line from:

```python
    lines = [sections["Summary"], "", "## Contents", ""]
```

to:

```python
    lines = [linkify_citations(sections["Summary"]), "", "## Contents", ""]
```

- [ ] **Step 5: Add the CLI**

Append to `plugins/proposal-research/scripts/build_vault.py`:

```python
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build the Obsidian vault for a research run")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--with-proposal", action="store_true",
                        help="include 05-Proposal/Draft Proposal.md (phase 7b)")
    parser.add_argument("--check-only", action="store_true",
                        help="verify links in an already-built vault without rebuilding")
    parser.add_argument("--copy-to", default=None, help="also copy the finished vault here")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)

    if args.check_only:
        problems = check_links(workspace / "vault")
    else:
        vault = build(workspace, include_proposal=args.with_proposal)
        problems = check_links(vault)

    if problems:
        for problem in problems:
            print(f"BROKEN LINK: {problem}", file=sys.stderr)
        print(f"VAULT: FAIL — {len(problems)} broken link(s)", file=sys.stderr)
        return 1

    vault = workspace / "vault"
    if args.copy_to:
        destination = Path(args.copy_to)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(vault, destination)
        print(f"Copied vault to {destination}")

    print(f"VAULT: OK — {vault}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the whole suite to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 7: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): citation links, link integrity gate, proposal note, vault CLI"
```

---
### Task 12: Agent definitions, validator identity resolution, tool-restriction lint

> **Design note on validator identity.** The validator needs no `Bash`, because granting it
> Bash would reopen the blindness hole that removing `Read` closed — `cat claims.jsonl` is a
> read. So the validator returns a structured verdict as its final message and the orchestrator
> records it. The `validator_agent_id` is then **resolved from the fetch log** rather than
> self-reported: it is the validator-type agent that actually fetched that claim's URL. That is
> strictly stronger than trusting an agent's word about its own identity, and it means gate
> check 4 passes exactly when the validator genuinely did the work.

**Files:**
- Create: `plugins/proposal-research/agents/planner.md`
- Create: `plugins/proposal-research/agents/researcher.md`
- Create: `plugins/proposal-research/agents/validator.md`
- Create: `plugins/proposal-research/agents/gap-hunter.md`
- Create: `plugins/proposal-research/agents/synthesizer.md`
- Create: `plugins/proposal-research/agents/proposal-writer.md`
- Modify: `plugins/proposal-research/scripts/add_verdict.py` (append resolver + CLI flag)
- Create: `plugins/proposal-research/tests/test_agents.py`
- Modify: `plugins/proposal-research/tests/test_add_verdict.py` (append resolver tests)

**Interfaces:**
- Consumes: `workspace.read_jsonl` (Task 1); `add_verdict.main` (Task 2)
- Produces:
  - `add_verdict.resolve_validator_agent_id(workspace: Path, url: str) -> str | None`
  - `--infer-agent-from <url>` flag on `add_verdict.py`
  - Six agent definition files with enforced tool sets

- [ ] **Step 1: Write the failing tool-restriction lint test**

Create `plugins/proposal-research/tests/test_agents.py`:

```python
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "agents"

EXPECTED_TOOLS = {
    "planner": {"Read", "Write"},
    "researcher": {"WebSearch", "WebFetch", "Bash",
                   "mcp__microsoft_docs_mcp__microsoft_docs_search",
                   "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
                   "mcp__headroom__headroom_compress"},
    "validator": {"WebFetch", "mcp__microsoft_docs_mcp__microsoft_docs_fetch"},
    "gap-hunter": {"Read", "WebSearch", "Write"},
    "synthesizer": {"Read", "Write"},
    "proposal-writer": {"Read", "Write"},
}


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name} has no frontmatter"
    block = text.split("\n---", 1)[0].lstrip("-\n")
    meta = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def tools_of(name: str) -> set[str]:
    raw = parse_frontmatter(AGENTS / f"{name}.md").get("tools", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def test_every_agent_file_exists():
    for name in EXPECTED_TOOLS:
        assert (AGENTS / f"{name}.md").is_file(), name


def test_every_agent_declares_name_and_description():
    for name in EXPECTED_TOOLS:
        meta = parse_frontmatter(AGENTS / f"{name}.md")
        assert meta.get("name") == name
        assert meta.get("description")


def test_tool_sets_match_the_design():
    for name, expected in EXPECTED_TOOLS.items():
        assert tools_of(name) == expected, name


def test_validator_cannot_read_the_ledger():
    """Blindness is enforced by tool restriction, not by instruction."""
    tools = tools_of("validator")
    assert "Read" not in tools
    assert "Bash" not in tools
    assert "Grep" not in tools


def test_validator_cannot_search():
    assert "WebSearch" not in tools_of("validator")


def test_synthesizer_has_no_web_tools():
    tools = tools_of("synthesizer")
    assert not any(t.startswith("Web") or "docs_fetch" in t or "docs_search" in t for t in tools)


def test_proposal_writer_has_no_web_tools():
    tools = tools_of("proposal-writer")
    assert not any(t.startswith("Web") for t in tools)


def test_planner_cannot_search():
    assert "WebSearch" not in tools_of("planner")


def test_no_agent_declares_a_model_in_frontmatter():
    """Models are passed at dispatch time; fable is not verified in frontmatter."""
    for name in EXPECTED_TOOLS:
        assert "model" not in parse_frontmatter(AGENTS / f"{name}.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_agents.py -v`
Expected: FAIL — `AssertionError: planner` (no agent files yet)

- [ ] **Step 3: Write the six agent files**

Create `plugins/proposal-research/agents/planner.md`:

```markdown
---
name: planner
description: Decomposes a proposal research question into independent, self-contained sub-questions, each tagged material or context. Cannot search.
tools: Read, Write
---

You decompose a proposal research question into sub-questions that other agents
will research independently. You cannot search. You produce a plan, nothing else.

## Inputs

- The proposal question, client, audience, and constraints from the orchestrator
- `ingest-report.md`, `internal-claims.jsonl`, `carried-claims.jsonl` in the workspace

## Method

1. Read `internal-claims.jsonl`. These are the user's own notes: unverified, and never
   evidence. Use them for one purpose only — they tell you what matters in this domain that
   a cold decomposition would miss. Turn each relevant one into a sub-question that sends a
   researcher to find a **public** source for it.
2. Read `carried-claims.jsonl`. These are already-verified claims from prior runs being
   re-validated this run. Do NOT write sub-questions that would rediscover them.
3. Decompose the question into 6-12 sub-questions. Each must be answerable on its own by
   someone who has not read the others — no pronouns referring to other sub-questions, no
   shared setup.
4. Tag each sub-question:
   - `material` — the answer changes the proposal: capabilities, limits, prices, licence
     tiers, regulations, GA/preview status, supported versions, integration constraints
   - `context` — background that frames the proposal but does not decide anything
5. For each sub-question, name what a *good* answer looks like, so a researcher knows when
   to stop.

## Output

Write `plan.md` to the workspace:

```markdown
# Research Plan

## Q1 — <question stated in full>
- tier: material
- good answer: <what would settle this>
- seeded by: I003 (internal note) | none

## Q2 — ...
```

## Rules

- Never assert a fact. You are decomposing, not answering.
- A sub-question that cannot be answered by reading one or two public pages is too big —
  split it.
```

Create `plugins/proposal-research/agents/researcher.md`:

```markdown
---
name: researcher
description: Researches one self-contained sub-question and appends verbatim-quoted claims to the ledger. Never paraphrases.
tools: WebSearch, WebFetch, Bash, mcp__microsoft_docs_mcp__microsoft_docs_search, mcp__microsoft_docs_mcp__microsoft_docs_fetch, mcp__headroom__headroom_compress
---

You research exactly ONE sub-question and record what you find as claims backed by
verbatim quotes.

## Method

1. Search for candidate sources. Prefer first-party pages: vendor documentation, regulator
   sites, official pricing pages. For anything Microsoft, use
   `mcp__microsoft_docs_mcp__microsoft_docs_search` first — first-party docs beat blog posts
   and kill a whole class of invented capabilities.
2. Fetch each promising page. Immediately pass large page bodies through
   `mcp__headroom__headroom_compress` and keep the compressed text plus its hash; discard the
   raw body. You will fetch 6-10 pages and you must stay coherent to the end.
3. For each fact you want to record, find the **exact sentence on the page that states it**.

## Recording a claim

Append via the CLI. Never write `claims.jsonl` with Write or Edit — parallel researchers
share that file and direct writes are blocked.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/add_claim.py" \
  --workspace <workspace> \
  --json '{"id":"C012","sub_q":"Q3","tier":"material","claim":"...","url":"https://...","quote":"<verbatim>","source_type":"vendor_doc","raw_hash":"<headroom hash>"}'
```

The CLI rejects malformed rows with reasons. Fix and retry.

## Rules

- **The quote must be copied verbatim from the page.** Not summarised, not tidied, not
  reflowed. Paraphrase is where fabrication hides, and a paraphrased quote is a fabricated
  quote even when the meaning survives.
- Quote at most 50 words — the sentence that carries the fact.
- Never record a claim for a page you did not fetch in this turn.
- If you cannot find a source for something, say so in your final message. Do not infer,
  do not reason from what you already know about the product, do not fill the gap.
- `source_type` must reflect what the page actually is: `vendor_doc`, `regulator`,
  `analyst`, `blog`, `forum`. A vendor's own blog is `blog`, not `vendor_doc`.
- Claim ids must be unique across the whole run. Use the id range the orchestrator gave you.

## Final message

Report: sub-question, claim ids recorded, and anything you could not source.
```

Create `plugins/proposal-research/agents/validator.md`:

```markdown
---
name: validator
description: Independently verifies one claim against its cited URL. Blind by construction — sees only the claim and the URL, cannot read the ledger, cannot search.
tools: WebFetch, mcp__microsoft_docs_mcp__microsoft_docs_fetch
---

You verify ONE claim against ONE URL. You have not seen the researcher's notes, their
quote, or their reasoning, and you cannot go looking for them — you have no Read tool, no
Bash, and no search. That is deliberate. Your independence is the point.

## You are given

- `claim_id`
- `claim` — a single factual statement
- `url` — the page it was drawn from

Nothing else. If you feel you need more context, the answer is no.

## Method

1. Fetch the URL. Fetch **that** URL — you cannot search for a better one.
2. Read the page and decide whether it supports the claim as stated.
3. Find your own supporting or contradicting sentence. Do not guess at what the researcher
   quoted; quote what you actually see.

## Verdicts

- `CONFIRMED` — the page states this. Supply **your own** verbatim quote.
- `CONTRADICTED` — the page states something incompatible with the claim. Supply the quote.
- `NOT_FOUND` — the page does not support the claim: it is silent on it, the link is dead,
  or the content has changed. No quote needed.
- `MISLEADING` — the page technically supports the claim, but stating it plainly in a
  proposal would mislead. Supply your quote **and** a caveat.

`MISLEADING` is the verdict that earns its keep. Watch for:

- preview / beta / "coming soon" features presented as available
- capabilities gated behind a licence tier the claim does not mention
- region-limited or cloud-limited availability (GCC, sovereign clouds, single regions)
- deprecated or superseded features
- limits stated as defaults that are actually hard caps, or vice versa
- version-specific behaviour presented as general

## Output

Return ONLY this JSON as your final message, nothing before or after:

```json
{"claim_id":"C012","verdict":"CONFIRMED","quote":"<your own verbatim quote>","caveat":null}
```

For `MISLEADING`, `caveat` is required and must say what a reader would wrongly conclude.

## Rules

- Never confirm from your own knowledge of the product. Your knowledge is not evidence;
  the page is. If the page does not say it, it is `NOT_FOUND`, however sure you are.
- A claim that is *almost* right is not `CONFIRMED`. Numbers, limits, and version numbers
  must match exactly.
```

Create `plugins/proposal-research/agents/gap-hunter.md`:

```markdown
---
name: gap-hunter
description: Reads the confirmed claim set and names what a domain expert would expect to see and does not. Emits new sub-questions.
tools: Read, WebSearch, Write
---

You are the reviewer who has seen a hundred proposals in this domain. Your job is to name
what is missing — not to research it.

## Method

1. Read `plan.md`, `claims.jsonl`, `verdicts.jsonl`, and `evidence-pack.md` if it exists.
2. Ask, concretely: if a sceptical architect or a procurement lead read this pack, what
   would they immediately ask that it does not answer?
3. Use WebSearch **only** to check whether a suspected gap is real — whether material on
   the topic exists at all. Do not research the answer; that is the researcher's job.

## Where gaps usually hide

- Licensing and per-seat cost of every named component
- GA vs preview status, and regional availability
- Rate limits, quotas, message caps, and what happens when they are hit
- Authentication and identity model between the components
- Data residency, retention, and what leaves the tenant
- Migration and exit cost from the recommended option
- The obvious competing option that was never assessed
- Whatever the client's own regulator requires that nobody mentioned

## Output

Write `gaps.md`:

```markdown
# Gap Round <N>

## G1 — <the missing question, stated in full>
- why it matters: <what decision it changes>
- tier: material
- evidence a gap exists: <search result, or "no coverage found in pack">
```

## Rules

- Only name gaps that would change the proposal. A pack cannot cover everything and
  padding the list wastes a research round.
- If the pack is genuinely complete, say so and emit no questions. That is a valid result.
- You get at most 2 rounds. On the final round, anything still open becomes the pack's
  "Open Questions" section rather than more searching.
```

Create `plugins/proposal-research/agents/synthesizer.md`:

```markdown
---
name: synthesizer
description: Writes the evidence pack from confirmed claims only. Has no web tools and cannot introduce a fact absent from the ledger.
tools: Read, Write
---

You write the evidence pack. You have no web tools, by design: you physically cannot
introduce a fact that is not already in the ledger.

## Inputs

`plan.md`, `claims.jsonl`, `verdicts.jsonl`, `gaps.md`, `ingest-report.md`.

## Admission rules

- A claim tagged `material` may be stated only if **every** validator ruled it `CONFIRMED`.
- A claim tagged `context` may be stated if not contradicted; mark it low confidence if any
  validator ruled `NOT_FOUND`.
- A claim ruled `MISLEADING` may be stated **only if you carry its caveat into the pack**,
  in full, next to the claim. The gate checks the caveat text is present.
- A claim ruled `CONTRADICTED` must never appear in the body. It goes in the appendix.
- Internal claims (`source_type: internal`) are never evidence. They may appear only in the
  appendix, marked as unverified internal knowledge.

## Required structure

The vault builder parses these exact H2 headings. Emit all of them.

```markdown
# Evidence Pack: <subject>

## Summary
## Recommendation
## Findings
### <one H3 per finding>
## Options
### <one H3 per candidate option>
## Constraints
### <one H3 per constraint>
## Open Questions
## Unverified & excluded
```

## Citation rules

- Every factual sentence ends with its claim id in brackets: `... 10 tools per server [C012].`
- A paragraph that states no external fact — framing, comparison of things already cited —
  may carry `<!-- no-citation: reason -->` on the line above. Use this sparingly; the gate
  reports every one.
- Never cite a claim id that is not in `claims.jsonl`.

## Rules

- Do not smooth over disagreement. If two sources conflict, say so and say which is
  first-party.
- The "Unverified & excluded" section is not a failure to hide. It is the section that
  makes the rest trustworthy — list what could not be stood up and why.
- Write for a technical buyer who will be spending money on this. No marketing register.
```

Create `plugins/proposal-research/agents/proposal-writer.md`:

```markdown
---
name: proposal-writer
description: Drafts the client-facing proposal from the human-approved evidence pack only. No web tools, no ledger access beyond the pack.
tools: Read, Write
---

You draft the proposal. You read the **approved** evidence pack and nothing else of
substance — no web, no fresh research. Every fact you state was already verified and
already reviewed by a human.

## Inputs

`evidence-pack.md` (approved), `verify-report.md`, and the client/audience/constraints
brief from the orchestrator.

## Structure

```markdown
# <Client> — <Solution> Proposal

## The problem we are solving
## Recommended approach
## Why this over the alternatives
## Architecture
## Constraints, risks, and how we handle them
## What we need from you
## Effort and phasing
## Open questions
```

## Citation rules

- Every factual claim carries its id: `Copilot Studio caps MCP tools at 10 per server [C012].`
- You may only cite ids that already appear in the approved pack. The gate re-runs over
  your draft with the same checks.
- Where the pack marked a claim low confidence or attached a caveat, that caveat must
  survive into the proposal. Do not quietly upgrade a hedged claim into a firm one — that
  is the single most expensive failure mode in a proposal.

## Rules

- No new facts. If the proposal needs something the pack does not have, put it in
  "Open questions" and say what would settle it.
- Effort and phasing are estimates, not findings. Label them as such.
- Write plainly. A buyer reading this should be able to tell what is verified, what is
  estimated, and what is still open.
```

- [ ] **Step 4: Run the agent lint to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_agents.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 5: Write the failing test for validator identity resolution**

Append to `plugins/proposal-research/tests/test_add_verdict.py`:

```python
def write_fetch_log(tmp_path, rows):
    (tmp_path / "fetch-log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_resolve_validator_agent_id_finds_the_fetching_validator(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "res-1", "agent_type": "researcher"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-9", "agent_type": "validator"},
    ])
    assert add_verdict.resolve_validator_agent_id(tmp_path, "https://a.com/x") == "val-9"


def test_resolve_ignores_trailing_slash_and_fragment(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x/", "agent_id": "val-9", "agent_type": "validator"},
    ])
    assert add_verdict.resolve_validator_agent_id(tmp_path, "https://a.com/x#top") == "val-9"


def test_resolve_returns_none_when_no_validator_fetched_it(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "res-1", "agent_type": "researcher"},
    ])
    assert add_verdict.resolve_validator_agent_id(tmp_path, "https://a.com/x") is None


def test_resolve_returns_the_latest_when_several_validators_fetched(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-1", "agent_type": "validator"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-2", "agent_type": "validator"},
    ])
    assert add_verdict.resolve_validator_agent_id(tmp_path, "https://a.com/x") == "val-2"


def test_main_infers_agent_id_from_the_fetch_log(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-7", "agent_type": "validator"},
    ])
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--infer-agent-from", "https://a.com/x",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["validator_agent_id"] == "val-7"


def test_main_fails_when_inference_finds_nothing(tmp_path, capsys):
    write_fetch_log(tmp_path, [])
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--infer-agent-from", "https://a.com/x",
    ])
    assert rc == 1
    assert "no validator" in capsys.readouterr().err.lower()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_add_verdict.py -v`
Expected: FAIL — `AttributeError: module 'add_verdict' has no attribute 'resolve_validator_agent_id'`

- [ ] **Step 7: Implement the resolver**

Append to `plugins/proposal-research/scripts/add_verdict.py`, above `main`:

```python
from workspace import read_jsonl  # noqa: E402


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    return url.split("#", 1)[0].rstrip("/")


def resolve_validator_agent_id(workspace: Path, url: str) -> str | None:
    """Identify the validator from fetch evidence rather than self-report.

    Stronger than trusting an agent's claim about its own identity: the id is
    derived from the same log the gate checks, so a verdict can only carry an
    id that genuinely fetched the page.
    """
    target = _normalize_url(url)
    found = None
    for row in read_jsonl(Path(workspace) / "fetch-log.jsonl"):
        if row.get("agent_type") != "validator":
            continue
        if _normalize_url(row.get("url")) != target:
            continue
        if row.get("agent_id"):
            found = row["agent_id"]
    return found
```

Then in `main`, add the new argument **before** `parser.parse_args(argv)` is called — alongside the existing `--workspace` and `--json` arguments:

```python
    parser.add_argument("--infer-agent-from", default=None,
                        help="resolve validator_agent_id from the fetch log for this URL")
```

and add the inference **after** the JSON row is parsed but **before** `validate_verdict` runs, so the resolved id is present when validation checks for it:

```python
    if args.infer_agent_from:
        agent_id = resolve_validator_agent_id(Path(args.workspace), args.infer_agent_from)
        if not agent_id:
            print(
                f"REJECTED: no validator fetched {args.infer_agent_from} in this run, so the "
                f"verdict's independence cannot be proven",
                file=sys.stderr,
            )
            return 1
        row["validator_agent_id"] = agent_id
```

- [ ] **Step 8: Run the whole suite to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — every test in the file passes

- [ ] **Step 9: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): six agent definitions with enforced tool restrictions"
```

---
### Task 13: Orchestrator skill and commands

**Files:**
- Create: `plugins/proposal-research/skills/proposal-research/SKILL.md`
- Create: `plugins/proposal-research/commands/research.md`
- Create: `plugins/proposal-research/commands/draft.md`
- Create: `plugins/proposal-research/commands/verify.md`
- Create: `plugins/proposal-research/tests/test_skill_contract.py`

**Interfaces:**
- Consumes: every script and agent from Tasks 1-12
- Produces: `/proposal-research:research`, `/proposal-research:draft`, `/proposal-research:verify`

- [ ] **Step 1: Write the failing contract test**

Create `plugins/proposal-research/tests/test_skill_contract.py`:

```python
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SKILL = PLUGIN / "skills" / "proposal-research" / "SKILL.md"
COMMANDS = PLUGIN / "commands"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} has no frontmatter"
    meta = {}
    for line in text.split("\n---", 1)[0].lstrip("-\n").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def test_skill_file_exists_with_name_and_description():
    meta = frontmatter(SKILL)
    assert meta["name"] == "proposal-research"
    assert len(meta["description"]) > 40


def test_skill_documents_every_phase():
    text = SKILL.read_text()
    for phase in ["Phase 0", "Phase 0.5", "Phase 1", "Phase 2", "Phase 3",
                  "Phase 4", "Phase 5", "Phase 5b", "Phase 6", "Phase 7"]:
        assert phase in text, phase


def test_skill_pins_the_model_for_every_role():
    text = SKILL.read_text()
    for role, model in [("planner", "sonnet"), ("researcher", "sonnet"),
                        ("validator", "haiku"), ("gap-hunter", "opus"),
                        ("synthesizer", "fable"), ("proposal-writer", "fable")]:
        pattern = rf"{role}.*{model}"
        assert re.search(pattern, text, re.IGNORECASE | re.DOTALL), f"{role} -> {model}"


def test_skill_states_the_human_gate_is_blocking():
    text = SKILL.read_text().lower()
    assert "human gate" in text
    assert "do not proceed" in text or "must not proceed" in text


def test_skill_caps_the_gap_loop_at_two_rounds():
    assert "2 rounds" in SKILL.read_text() or "two rounds" in SKILL.read_text()


def test_all_three_commands_exist():
    for name in ["research", "draft", "verify"]:
        assert (COMMANDS / f"{name}.md").is_file(), name


def test_commands_have_descriptions():
    for name in ["research", "draft", "verify"]:
        assert frontmatter(COMMANDS / f"{name}.md").get("description")


def test_research_command_invokes_the_skill():
    assert "proposal-research" in (COMMANDS / "research.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest plugins/proposal-research/tests/test_skill_contract.py -v`
Expected: FAIL — `FileNotFoundError` on SKILL.md

- [ ] **Step 3: Write SKILL.md**

Create `plugins/proposal-research/skills/proposal-research/SKILL.md`:

```markdown
---
name: proposal-research
description: Research a product or solution proposal question across the web and emit a cited evidence pack, a draft proposal, and a self-contained Obsidian vault. Use when the user asks to research a proposal, compare vendor or architecture options for a client, or build a solution proposal that must not contain false capability, pricing, or regulatory claims. Six subagents communicate through append-only claim ledgers; a blocking gate proves every cited page was actually retrieved.
---

# Proposal Research

You orchestrate. You do not search, and you do not write claims yourself.

Set `WS` to `research/<slug>/` where `<slug>` is a slugified form of the question.
Set `PR` to `${CLAUDE_PLUGIN_ROOT}`.

## Phase 0 — Intake

Use AskUserQuestion to establish, in one call:

1. **Client / prospect** — who the proposal is for
2. **Audience** — technical buyer, procurement, C-level, regulator
3. **Hard constraints** — budget ceiling, timeline, incumbent tech, mandated platform
4. **Context paths** — any local folders to ingest (optional)

Create the workspace, then register the run so the fetch hook knows where to log:

```bash
python3 -c "
import sys; sys.path.insert(0, '$PR/scripts')
from pathlib import Path
import workspace
workspace.ensure_workspace(Path('$WS'))
workspace.set_active_run(Path('.'), '<session_id>', '<slug>')
"
```

Take `<session_id>` from your own session. Without this the fetch log stays empty and the
gate will fail every claim — so confirm `research/.active.json` exists before continuing.

## Phase 0.5 — Ingest local context

```bash
python3 "$PR/scripts/ingest_context.py" --workspace "$WS" --question "<question>" \
  [--prior <prior run or vault>]... [--context <path>]... \
  [--configured-vault <path>] [--repo .] --limit 25
```

Read `ingest-report.md`. Carried claims skip discovery but are still re-validated.

## Phase 1 — Plan

Dispatch `planner`, **model `sonnet`**. Give it the question, the intake answers, and the
workspace path. It writes `plan.md`. Read it and confirm the sub-questions are genuinely
self-contained before fanning out — a vague sub-question wastes a whole researcher.

## Phase 2 — Research fan-out

Dispatch one `researcher` per sub-question **in a single message so they run in parallel**,
each **model `sonnet`**. Give each one:

- its sub-question, stated in full, and its tier
- the workspace path
- a **disjoint claim id range** (Q1 -> C001-C019, Q2 -> C020-C039, ...) so parallel
  researchers cannot collide on ids

Also dispatch one researcher per carried claim to re-fetch its URL and re-append it with a
fresh `fetched_at`, using the same id range discipline.

## Phase 3 — Validation fan-out

For every claim in `claims.jsonl`, dispatch a `validator`, **model `haiku`**, in parallel.

Give the validator **only** `{claim_id, claim, url}`. Never the researcher's quote, never
their narrative, never the raw_hash. The validator has no Read, no Bash and no WebSearch, so
it cannot obtain them itself — do not undo that by pasting them into the prompt.

The validator returns JSON. Record it, resolving its identity from fetch evidence:

```bash
python3 "$PR/scripts/add_verdict.py" --workspace "$WS" \
  --json '{"claim_id":"C012","verdict":"CONFIRMED","validator_model":"haiku","quote":"..."}' \
  --infer-agent-from "<the claim url>"
```

**Escalation:** every `material` claim a haiku validator marked `CONFIRMED` gets a second
validator, **model `sonnet`**, dispatched identically. Both verdicts are recorded. A
material claim needs two CONFIRMED rulings to enter the pack.

## Phase 4 — Gap hunt

Dispatch `gap-hunter`, **model `opus`**. It writes `gaps.md`. If it emits questions and you
have run fewer than **2 rounds**, return to Phase 2 for those questions only. After 2 rounds,
stop: remaining gaps become the pack's "Open Questions" section.

## Phase 5 — Synthesis

Dispatch `synthesizer`, **model `fable`**. It writes `evidence-pack.md` using the fixed H2
section contract. Re-read the contract in the agent file if the build fails.

## Phase 5b — Build the vault

```bash
python3 "$PR/scripts/build_vault.py" --workspace "$WS"
```

Broken links exit non-zero. Fix the pack and rebuild rather than editing the vault by hand —
the vault is generated output.

## Phase 6 — The gate

```bash
python3 "$PR/scripts/verify_pack.py" --workspace "$WS"
```

**A non-zero exit blocks the pipeline.** Do not proceed to Phase 7, and do not present the
pack as trustworthy, until it passes. Typical failures and their real causes:

| Failure | Cause |
|---|---|
| `fetch-provenance` | The claim's URL was never retrieved — usually a fabricated citation, sometimes a missing `.active.json` |
| `validator-blindness` | A verdict was recorded for a page its validator never opened |
| `verdict-admission` | A material claim is missing its sonnet escalation pass |
| `uncited-prose` | The synthesizer asserted something with no claim behind it |

## HUMAN GATE

Present `evidence-pack.md`, `verify-report.md`, and the vault path. Say plainly what is
verified, what is low confidence, and what is in "Unverified & excluded".

**Stop. Do not draft the proposal until the user approves the pack.** The whole point of two
gates is that the proposal cannot inherit unvetted claims.

## Phase 7 — Draft the proposal

Only after approval. Dispatch `proposal-writer`, **model `fable`**, with the approved pack.
Then re-run both the gate and the builder over the proposal:

```bash
python3 "$PR/scripts/verify_pack.py" --workspace "$WS" --pack proposal.md
python3 "$PR/scripts/build_vault.py" --workspace "$WS" --with-proposal
```

## Phase 7b — Offer to copy out

Ask whether to copy the vault somewhere the user keeps proposals:

```bash
python3 "$PR/scripts/build_vault.py" --workspace "$WS" --with-proposal --copy-to "<path>"
```

## Rules for you, the orchestrator

- You never search and you never write to `claims.jsonl` or `verdicts.jsonl` by hand. Both
  are hook-protected.
- Dispatch parallel agents in **one message** with multiple tool calls, or they run serially.
- Never paste a researcher's quote into a validator's prompt. That single shortcut destroys
  the only independent check in the system.
- If the gate fails, report the failure honestly. Do not narrate around it, and do not
  present a failed pack as "mostly verified".
```

- [ ] **Step 4: Write the three commands**

Create `plugins/proposal-research/commands/research.md`:

```markdown
---
description: Research a product or solution proposal question and produce a cited evidence pack plus an Obsidian vault (stops at the human approval gate).
---

Run the `proposal-research` skill, Phases 0 through 6, for this question:

$ARGUMENTS

Stop at the human gate. Present the evidence pack, the verify report, and the vault path.
Do not draft the proposal until the user approves the pack.
```

Create `plugins/proposal-research/commands/draft.md`:

```markdown
---
description: Draft the client-facing proposal from an already-approved evidence pack (Phase 7).
---

Run Phase 7 of the `proposal-research` skill for the workspace named in $ARGUMENTS, or the
most recent run under `research/` if none is named.

Confirm the evidence pack has been approved by the user before dispatching the
proposal-writer. If `verify-report.md` shows a failed gate, refuse and report why.
```

Create `plugins/proposal-research/commands/verify.md`:

```markdown
---
description: Re-run the verification gate over an existing evidence pack or proposal.
---

Run `verify_pack.py` for the workspace named in $ARGUMENTS, or the most recent run under
`research/` if none is named. Report the result, then summarise each failure with its likely
cause using the table in the `proposal-research` skill.
```

- [ ] **Step 5: Run the contract test to verify it passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_skill_contract.py -v`
Expected: PASS — every test in the file passes

- [ ] **Step 6: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add plugins/proposal-research
git commit -m "feat(proposal-research): orchestrator skill and research/draft/verify commands"
```

---

### Task 14: End-to-end integration and installation

**Files:**
- Create: `plugins/proposal-research/tests/test_end_to_end.py`
- Modify: `.gitignore` (ignore generated run workspaces)
- Modify: `plugins/proposal-research/README.md` (installation section)

**Interfaces:**
- Consumes: every script from Tasks 1-13

- [ ] **Step 1: Write the failing end-to-end test**

Create `plugins/proposal-research/tests/test_end_to_end.py`:

```python
"""Drive a whole run through the deterministic scripts with no model in the loop.

Agents are simulated by calling the same CLIs they would call, so this proves the
file contracts hold end to end: ingest -> claims -> verdicts -> pack -> gate -> vault
-> export -> ingestable by the next run.
"""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import add_claim  # noqa: E402
import add_verdict  # noqa: E402
import build_vault  # noqa: E402
import ingest_context  # noqa: E402
import verify_pack  # noqa: E402
import workspace  # noqa: E402

URL = "https://learn.microsoft.com/copilot-studio/mcp-limits"
QUOTE = "A maximum of 10 tools per MCP server connection is supported."

PACK = """# Evidence Pack: Copilot Studio MCP

## Summary

The tool cap is the binding constraint on this design [C001].

## Recommendation

Proceed with Copilot Studio, splitting tools across two server connections [C001].

## Findings

### MCP tool limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

## Options

### Copilot Studio with MCP

Viable within the cap [C001].

## Constraints

### Tool cap

Ten tools per connection [C001].

## Open Questions

- Regional GA status

## Unverified & excluded

Nothing was excluded.
"""


def simulate_fetch(ws, agent_id, agent_type, url=URL):
    workspace.append_jsonl(ws / "fetch-log.jsonl", {
        "ts": workspace.utc_now(), "tool": "WebFetch", "url": url,
        "query": None, "agent_id": agent_id, "agent_type": agent_type,
    })


def test_full_run_passes_the_gate_and_builds_a_vault(tmp_path):
    ws = tmp_path / "research" / "copilot-mcp"
    ws.mkdir(parents=True)

    # Phase 0.5
    assert ingest_context.main([
        "--workspace", str(ws), "--question", "Copilot Studio MCP tool limits"]) == 0

    # Phase 2 — researcher fetches, then appends
    simulate_fetch(ws, "res-1", "researcher")
    assert add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio caps MCP tools at 10 per server connection",
        "url": URL, "quote": QUOTE, "source_type": "vendor_doc",
    })]) == 0

    # Phase 3 — haiku validator, then sonnet escalation
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        simulate_fetch(ws, agent_id, "validator")
        assert add_verdict.main([
            "--workspace", str(ws), "--infer-agent-from", URL,
            "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                  "validator_model": model, "quote": QUOTE}),
        ]) == 0

    # Phase 5
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")

    # Phase 6 — the gate must pass
    assert verify_pack.main(["--workspace", str(ws)]) == 0
    assert "GATE: PASS" in (ws / "verify-report.md").read_text()

    # Phase 5b — the vault must build with no broken links
    assert build_vault.main(["--workspace", str(ws)]) == 0
    vault = ws / "vault"
    assert (vault / "00-MOC" / "Proposal Brief.md").is_file()
    assert "### C001" in (vault / "06-Sources" / "Sources.md").read_text()


def test_fabricated_citation_is_caught_by_the_gate(tmp_path):
    """The failure this plugin exists to prevent."""
    ws = tmp_path / "research" / "fabricated"
    ws.mkdir(parents=True)

    simulate_fetch(ws, "res-1", "researcher")
    add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio supports 200 MCP tools per connection",
        "url": "https://learn.microsoft.com/never-fetched",  # never in the fetch log
        "quote": QUOTE, "source_type": "vendor_doc",
    })])
    simulate_fetch(ws, "val-h1", "validator")
    add_verdict.main(["--workspace", str(ws), "--infer-agent-from", URL,
                      "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                            "validator_model": "haiku", "quote": QUOTE})])
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")

    assert verify_pack.main(["--workspace", str(ws)]) == 1
    report = (ws / "verify-report.md").read_text()
    assert "GATE: FAIL" in report
    assert "never retrieved" in report


def test_internal_claim_cannot_reach_the_pack_as_material(tmp_path):
    """The ingestion firewall."""
    ws = tmp_path / "research" / "firewall"
    ws.mkdir(parents=True)
    rc = add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "From my own notes", "url": "https://example.com/x",
        "quote": "note text", "source_type": "internal",
    })])
    assert rc == 1
    assert not (ws / "claims.jsonl").exists()


def test_a_finished_run_seeds_the_next_one(tmp_path):
    """Runs compound: a built vault is a lane-1 source for the next run."""
    from datetime import datetime, timezone

    ws = tmp_path / "research" / "run-one"
    ws.mkdir(parents=True)
    simulate_fetch(ws, "res-1", "researcher")
    add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio caps MCP tools at 10 per server connection",
        "url": URL, "quote": QUOTE, "source_type": "vendor_doc",
    })])
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        simulate_fetch(ws, agent_id, "validator")
        add_verdict.main(["--workspace", str(ws), "--infer-agent-from", URL,
                          "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                                "validator_model": model, "quote": QUOTE})])
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")
    vault = build_vault.build(ws)

    carried = ingest_context.carry_forward(
        ingest_context.load_prior_ledger(vault), datetime.now(timezone.utc))
    assert len(carried) == 1
    assert carried[0]["url"] == URL
    assert carried[0]["needs_revalidation"] is True
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python3 -m pytest plugins/proposal-research/tests/test_end_to_end.py -v`
Expected: PASS if Tasks 1-13 are complete. If any test fails, the failure names the broken
file contract — fix that script, not the test.

- [ ] **Step 3: Ignore generated run workspaces**

Append to `.gitignore`:

```
research/
```

- [ ] **Step 4: Document installation**

Append to `plugins/proposal-research/README.md`:

```markdown
## Installation

    /plugin marketplace add ~/repos/CCAF
    /plugin install proposal-research@ccaf

Hook configuration hot-reloads, so no restart is needed.

## Verifying the install

    python3 -m pytest plugins/proposal-research/tests/ -v

All tests are stdlib-only and run under the system `python3`.

## How the guarantee works

`research/<slug>/` holds the audit trail for a run:

| File | What it proves |
|---|---|
| `claims.jsonl` | Every claim, with the verbatim quote it rests on |
| `verdicts.jsonl` | Who ruled on each claim and what they found |
| `fetch-log.jsonl` | Every page retrieved, and which agent retrieved it |
| `verify-report.md` | The gate result, with source mix and every warning |
| `vault/06-Sources/Sources.md` | Per-claim anchors plus derived reliability notes |

The gate cross-references the first three. A citation can only survive if the page behind it
was really fetched, by the validator that really ruled on it.
```

- [ ] **Step 5: Run the entire suite**

Run: `python3 -m pytest plugins/proposal-research/tests/ -v`
Expected: PASS — all tests green

- [ ] **Step 6: Install and smoke-test against the real question**

```bash
cd /Users/chandima/repos/CCAF
```

In Claude Code:

```
/plugin marketplace add ~/repos/CCAF
/plugin install proposal-research@ccaf
/proposal-research:research "ServiceNow agent via Copilot Studio with an MCP server, versus ServiceNow native AI Agent Studio agents"
```

Confirm by inspection:

- `research/<slug>/fetch-log.jsonl` contains rows with non-null `agent_id` (proves the hook
  fires inside subagents in the installed plugin, not just the probe)
- `verify-report.md` says `GATE: PASS`
- At least one `MISLEADING` verdict appears if any preview/GA caveat exists — this is the
  case the plugin exists for
- `research/<slug>/vault/` opens in Obsidian with a populated graph view

- [ ] **Step 6b: Blind-validation live check (the spec's adversarial fixture)**

Unit tests cannot prove a *model* validates blindly, so check it once by hand against the
finished run. Pick a real URL from `claims.jsonl` and dispatch a `validator` directly with a
claim that URL does not support — for example take a genuine Microsoft Learn page and assert
a limit of 200 tools rather than 10:

```
Agent(subagent_type="proposal-research:validator", model="haiku", prompt=
  'claim_id: C999\nclaim: Copilot Studio supports 200 MCP tools per server connection\nurl: <a real fetched URL>')
```

Expected: `NOT_FOUND` or `CONTRADICTED`, never `CONFIRMED`. A `CONFIRMED` here means the
validator is reasoning from model knowledge rather than the page, and the validator prompt
needs tightening before the plugin is trusted.

- [ ] **Step 7: Commit**

```bash
cd /Users/chandima/repos/CCAF
git add -A plugins/proposal-research .gitignore
git commit -m "test(proposal-research): end-to-end contract coverage and install docs"
```

---

## Appendix: Deviations from the spec

Three changes were made while planning. Each is a correction, not a scope change, and each is
flagged in the task that introduces it.

| # | Spec said | Plan does | Why |
|---|---|---|---|
| 1 | Researchers write `claims.jsonl` directly; `PostToolUse` lint | Appends go through `add_claim.py`; `PreToolUse` hook denies direct writes | Parallel researchers using `Write` on one file clobber each other, and `PostToolUse` fires after the row has landed, so "rejected before it lands" is unachievable on that event |
| 2 | Carried claims re-fetched only when older than 90 days | Every carried claim is re-validated | A carried claim cited in a new pack would fail gate checks 3 and 4 — nothing this session fetched its URL. Carving an exception into the gate would hole the exact guarantee the plugin provides. The saving survives because discovery, not re-fetching, is the expensive phase |
| 3 | `validator_agent_id` recorded by the validator | Resolved from `fetch-log.jsonl` | The validator has no Bash (granting it would reopen the blindness hole that removing `Read` closed), and identity derived from fetch evidence is stronger than self-report |
