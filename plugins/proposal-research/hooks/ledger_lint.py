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
    except Exception:  # noqa: BLE001
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
