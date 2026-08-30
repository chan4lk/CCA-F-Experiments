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

from .workspace import (
    agent_role,
    CLAIM_ID_RE,
    VERDICTS,
    append_jsonl,
    normalize_url,
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


def validators_that_fetched(workspace: Path, url: str) -> list[str]:
    """Every distinct validator that fetched this URL, in first-seen order.

    Identity comes from fetch evidence rather than self-report: the id is derived
    from the same log the gate checks, so a verdict can only carry an id that
    genuinely fetched the page.

    Returns all of them rather than one. Picking the last silently attributed
    both verdicts on a claim to whichever validator happened to finish second,
    which made two rulings by one validator look like an escalation.
    """
    target = normalize_url(url)
    found: list[str] = []
    for row in read_jsonl(Path(workspace) / "fetch-log.jsonl"):
        if agent_role(row.get("agent_type")) != "validator":
            continue
        if normalize_url(row.get("url")) != target:
            continue
        agent_id = row.get("agent_id")
        if agent_id and agent_id not in found:
            found.append(agent_id)
    return found


def validators_that_ruled(workspace: Path, claim_id: str) -> set[str]:
    """Validators already carrying a verdict on this claim."""
    return {
        row["validator_agent_id"]
        for row in read_jsonl(Path(workspace) / "verdicts.jsonl")
        if row.get("claim_id") == claim_id and row.get("validator_agent_id")
    }


def resolve_validator_agent_id(workspace: Path, url: str, claim_id: str) -> tuple[str | None, str]:
    """Return (agent_id, error). Exactly one candidate, or nothing at all.

    The candidate set is the validators that fetched this URL and have not yet
    ruled on this claim. The fetch log is cumulative, so "fetched this URL" alone
    stops being unambiguous the moment the escalation validator opens the same
    page; subtracting the validators that have already ruled is what makes
    inference unambiguous by construction, provided each verdict is recorded
    before the next validator is dispatched.
    """
    fetched = validators_that_fetched(workspace, url)
    if not fetched:
        return None, (
            f"no validator fetched {url} in this run, so the verdict's independence "
            f"cannot be proven"
        )

    ruled = validators_that_ruled(workspace, claim_id)
    candidates = [a for a in fetched if a not in ruled]

    if not candidates:
        return None, (
            f"every validator that fetched {url} ({', '.join(fetched)}) has already ruled "
            f"on {claim_id}. Recording another verdict would have to invent an author. "
            f"Pass --validator-agent-id <id> if this really is a distinct validator."
        )
    if len(candidates) > 1:
        return None, (
            f"{len(candidates)} validators fetched {url} without yet ruling on {claim_id} "
            f"({', '.join(candidates)}), so this verdict's author cannot be inferred. "
            f"Guessing would attribute both rulings on a claim to one validator and make a "
            f"single pass look like an escalation.\n"
            f"Record each verdict immediately after that validator returns, before "
            f"dispatching the next one, or pass --validator-agent-id <id> explicitly."
        )
    return candidates[0], ""


INFER_KEY = "_infer_from_url"


def record_one(workspace: Path, row: dict, infer_from: str | None = None,
               agent_id: str | None = None) -> tuple[bool, str]:
    """Validate and append one verdict. Returns (ok, message)."""
    if agent_id:
        row["validator_agent_id"] = agent_id

    if infer_from:
        resolved, error = resolve_validator_agent_id(workspace, infer_from, row.get("claim_id"))
        if error:
            return False, error
        row["validator_agent_id"] = resolved

    errors = validate_verdict(row)
    if errors:
        return False, "; ".join(errors)

    row.setdefault("ruled_at", utc_now())
    append_jsonl(workspace / "verdicts.jsonl", row)
    return True, f"recorded {row['verdict']} for {row['claim_id']}"


def record_rows(workspace: Path, rows: list[dict]) -> tuple[int, list[str]]:
    """Record many verdicts at once. Returns ``(recorded, rejections)``.

    In the plugin this batching was a token optimisation the orchestrator had to
    remember: recording 468 verdicts one at a time cost 468 model turns, each
    re-reading a 362,000-token context — about 65% of that run's entire spend.

    Here the orchestrator is Python, so recording a verdict costs nothing at all
    and the batching is just the natural shape of the call. The rejection list is
    the part that still matters: a malformed row is reported and skipped, and the
    rest still land.
    """
    recorded, rejections = 0, []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            rejections.append(f"row {index}: not a JSON object")
            continue
        infer_from = row.pop(INFER_KEY, None)
        good, message = record_one(Path(workspace), dict(row), infer_from=infer_from)
        if good:
            recorded += 1
        else:
            rejections.append(f"{row.get('claim_id', f'row {index}')}: {message}")
    return recorded, rejections


def run_batch(workspace: Path, batch_path: Path) -> int:
    """Record many verdicts in one call.

    The first real run spent roughly 468 orchestrator turns recording 468
    verdicts one at a time, and every one of those turns re-read a context
    averaging 362,000 tokens — about 65% of the entire run's token cost. The
    work is identical; only the number of turns changes.

    A malformed row is reported and skipped; the rest still land.
    """
    ok, rejections = record_rows(workspace, read_jsonl(batch_path))
    for rejection in rejections:
        print(f"REJECTED {rejection}", file=sys.stderr)
    print(f"OK: recorded {ok} verdict(s)"
          + (f", rejected {len(rejections)}" if rejections else ""))
    return 1 if rejections else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append validated verdicts to verdicts.jsonl")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--json", default=None, help="one verdict row as a JSON object")
    parser.add_argument("--batch", default=None,
                        help="path to a JSONL file of verdict rows; each row may carry "
                             "\"_infer_from_url\" to resolve its own validator_agent_id")
    parser.add_argument("--infer-agent-from", default=None,
                        help="resolve validator_agent_id from the fetch log for this URL; "
                             "refuses if more than one validator fetched it")
    parser.add_argument("--validator-agent-id", default=None,
                        help="state the validator's agent_id explicitly; the unambiguous "
                             "path when several validators fetched the same URL")
    args = parser.parse_args(argv)

    if bool(args.json) == bool(args.batch):
        print("REJECTED: pass exactly one of --json or --batch", file=sys.stderr)
        return 1

    if args.batch:
        return run_batch(Path(args.workspace), Path(args.batch))

    if args.infer_agent_from and args.validator_agent_id:
        print(
            "REJECTED: pass either --infer-agent-from or --validator-agent-id, not both",
            file=sys.stderr,
        )
        return 1

    try:
        row = json.loads(args.json)
    except json.JSONDecodeError as exc:
        print(f"REJECTED: --json is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(row, dict):
        print("REJECTED: --json must be a JSON object", file=sys.stderr)
        return 1

    good, message = record_one(
        Path(args.workspace), row,
        infer_from=args.infer_agent_from, agent_id=args.validator_agent_id)
    if not good:
        print(f"REJECTED: {message}", file=sys.stderr)
        return 1
    print(f"OK: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
