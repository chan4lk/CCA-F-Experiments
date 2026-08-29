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
        claim_id = verdict.get("claim_id")
        if claim_id:  # Skip verdicts with no claim_id
            verdicts_by_claim.setdefault(claim_id, []).append(verdict)

    rows = []
    for row in read_jsonl(claims_path):
        claim_id = row.get("id")
        if claim_id:  # Skip claims with no id
            row["verdicts"] = verdicts_by_claim.get(claim_id, [])
            row.setdefault("_slug", path.name)
            rows.append(row)
    return rows


def carry_forward(prior: list[dict], now: datetime) -> list[dict]:
    """Keep only claims every validator confirmed. Re-id and mark for re-validation."""
    carried: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in prior:
        if row.get("source_type") == "internal" or not row.get("url"):
            continue

        verdicts = row.get("verdicts") or []
        if not verdicts:
            continue
        if any(v.get("verdict") != "CONFIRMED" for v in verdicts):
            continue

        url_key = row["url"].split("#", 1)[0].rstrip("/")
        claim_text = row.get("claim", "")
        dedup_key = (url_key, claim_text)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

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
    """Term overlap between the question and the note's identifying text.

    Front matter (title, tags) is authored metadata and counts double, so it can
    move the score even when the filename alone already overlaps the question —
    otherwise two notes sharing a filename stem would always tie regardless of
    what their title says.
    """
    q_terms = set(_WORD_RE.findall(question.lower()))
    filename_terms = set(_WORD_RE.findall(path.stem.replace("-", " ").replace("_", " ")))
    meta_text = " ".join([
        str(meta.get("title", "")),
        " ".join(meta.get("tags", []) if isinstance(meta.get("tags"), list) else []),
    ]).lower()
    meta_terms = set(_WORD_RE.findall(meta_text))
    return len(q_terms & filename_terms) + 2 * len(q_terms & meta_terms)


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
