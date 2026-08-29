#!/usr/bin/env python3
"""Validate and atomically append one verdict row to verdicts.jsonl.

A CONFIRMED verdict must carry the validator's OWN supporting quote. That is
what distinguishes verification from echoing the researcher: the validator
never saw the researcher's quote, so supplying one proves it found its own.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import (  # noqa: E402
    CLAIM_ID_RE,
    VERDICTS,
    append_jsonl,
    read_jsonl,
    utc_now,
)

REQUIRED = ("claim_id", "verdict", "validator_agent_id", "validator_model")


def validate_verdict(row: dict) -> list[str]:
    errors: list[str] = []

    for key in REQUIRED:
        if key not in row:
            errors.append(f"missing required field: {key}")
        elif row[key] is None or (isinstance(row[key], str) and not row[key].strip()):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append a validated verdict to verdicts.jsonl")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--json", required=True, help="verdict row as a JSON object")
    parser.add_argument("--infer-agent-from", default=None,
                        help="resolve validator_agent_id from the fetch log for this URL")
    args = parser.parse_args(argv)

    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as exc:
        print(f"REJECTED: --json is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(row, dict):
        print("REJECTED: --json must be a JSON object", file=sys.stderr)
        return 1

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

    errors = validate_verdict(row)
    if errors:
        print("REJECTED: verdict not appended. Fix and retry:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    row.setdefault("ruled_at", utc_now())
    append_jsonl(Path(args.workspace) / "verdicts.jsonl", row)
    print(f"OK: recorded {row['verdict']} for {row['claim_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
