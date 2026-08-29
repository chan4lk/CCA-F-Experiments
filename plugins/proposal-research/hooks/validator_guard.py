#!/usr/bin/env python3
"""PreToolUse hook: keep the validator blind, mechanically.

The validator holds `Bash` because 57% of the claims in the first real run
cited PDFs and WebFetch cannot decode a PDF binary. That grant reopened the
hole removing `Read` had closed: `cat claims.jsonl` is a read.

So blindness is enforced here instead. A validator may fetch and convert a
document; it may not reach the workspace, and it may not search. Its
independence is again a property of what it *cannot* do.

Exit 2 blocks the call and returns stderr to the model. Exit 0 allows.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# Anything that would reveal what the researcher wrote, or what another
# validator ruled. Matched against the raw command text, so an absolute path,
# a relative path and a glob are all caught.
LEDGER_NAMES = ("claims.jsonl", "verdicts.jsonl", "internal-claims.jsonl",
                "carried-claims.jsonl", "fetch-log.jsonl", "evidence-pack.md",
                "plan.md", "gaps.md")
WORKSPACE_RE = re.compile(r"(^|[\s'\"=/])research/", re.MULTILINE)

# Tools that read the local filesystem. The validator has none of these in its
# frontmatter; this is defence in depth against a future grant.
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookEdit"}


def _deny(message: str) -> int:
    print(
        f"BLOCKED: {message}\n\n"
        f"You are a validator. Your independence is the point: you rule on a claim "
        f"having seen only the claim text and its URL. Reaching the workspace would "
        f"show you the researcher's own quote, and searching would let you find a "
        f"friendlier source than the one cited.\n\n"
        f"Fetch the cited URL and rule on what that page says. If you cannot read it, "
        f"return NOT_FOUND — that is a valid and useful answer.",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        from workspace import agent_role

        if agent_role(payload.get("agent_type")) != "validator":
            return 0

        tool = payload.get("tool_name") or ""
        tool_input = payload.get("tool_input") or {}

        if tool == "WebSearch":
            return _deny("a validator may not search.")
        if tool in READ_TOOLS:
            return _deny(f"a validator may not use {tool} on the local filesystem.")
        if tool != "Bash":
            return 0

        command = str(tool_input.get("command") or "")
        hit = next((n for n in LEDGER_NAMES if n in command), None)
        if hit:
            return _deny(f"that command touches {hit}, which is run state you must not read.")
        if WORKSPACE_RE.search(command):
            return _deny("that command reaches into the research/ workspace.")
    except Exception:  # noqa: BLE001
        # An agent we cannot identify cannot be judged a validator. Failing
        # closed here would block every call in the session on a parse bug.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
