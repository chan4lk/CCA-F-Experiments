#!/usr/bin/env python3
"""Validate and atomically append one claim row to claims.jsonl.

Researchers MUST use this rather than writing the ledger directly: parallel
researchers sharing one file would otherwise clobber each other, and validation
here is deterministic rather than dependent on hook timing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import (  # noqa: E402
    normalize_url,
    CLAIM_ID_RE,
    MAX_QUOTE_WORDS,
    SOURCE_TYPES,
    TIERS,
    append_jsonl,
    read_jsonl,
    utc_now,
)

REQUIRED = ("id", "sub_q", "tier", "claim", "url", "quote", "source_type")


def validate_claim(row: dict, existing_ids: set[str]) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED:
        if key not in row:
            errors.append(f"missing required field: {key}")
        elif row[key] is None or (isinstance(row[key], str) and not row[key].strip()):
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


def provenance_warning(workspace: Path, url: str) -> str:
    """Warn now if nothing has retrieved this URL yet, rather than at the gate.

    The PostToolUse hook only sees WebFetch/WebSearch/MS-Learn. A researcher
    that reads a page with curl — which is what happens when WebFetch cannot
    decode a PDF — leaves no trace, and the gate rejects the claim an hour
    later. A real run lost 17 claims that way.

    This is a warning, not a rejection: the claim still lands, and a WebFetch
    of the same URL now makes its provenance appear retroactively.
    """
    log = Path(workspace) / "fetch-log.jsonl"
    if not log.is_file() or not log.stat().st_size:
        return (
            f"PROVENANCE: nothing has been retrieved in this run yet, so {url} has no "
            f"provenance and every claim will fail the gate.\n"
            f"  This usually means the run was never registered — check that "
            f"research/.active.json maps this session's id to this run's slug, then "
            f"WebFetch the URL before continuing."
        )
    target = normalize_url(url)
    for row in read_jsonl(log):
        if normalize_url(row.get("url")) == target:
            return ""
    return (
        f"PROVENANCE: {url} does not appear in fetch-log.jsonl, so this claim will fail "
        f"the gate's provenance and blindness checks.\n"
        f"  If you read that page with curl or wget, the hook could not see it. Call "
        f"WebFetch on the same URL now — the claim has been appended, and the retrieval "
        f"will attach to it retroactively."
    )


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
    existing_ids = {r["id"] for r in read_jsonl(ledger) if r.get("id")}

    errors = validate_claim(row, existing_ids)
    if errors:
        print("REJECTED: claim not appended. Fix and retry:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    row.setdefault("fetched_at", utc_now())
    append_jsonl(ledger, row)
    warning = provenance_warning(Path(args.workspace), row["url"])
    if warning:
        print(warning, file=sys.stderr)
    print(f"OK: appended {row['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
