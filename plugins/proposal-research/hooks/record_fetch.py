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
