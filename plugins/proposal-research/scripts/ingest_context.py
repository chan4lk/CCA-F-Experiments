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
