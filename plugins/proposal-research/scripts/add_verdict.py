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
