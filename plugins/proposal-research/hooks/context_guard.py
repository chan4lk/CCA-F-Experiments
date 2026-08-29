#!/usr/bin/env python3
"""PostToolUse hook: make the orchestrator's context cost visible while it runs.

In the first real run the main session's context grew 107K -> 706K across 488
turns. Cache reads are turns x context, so that came to 172 million tokens —
65% of everything the run processed, against 90 million for all ninety
subagents combined. Of the ~600K of growth, tool results were only ~104K; the
rest was the orchestrator's own prose, re-read on every turn that followed it.

Nothing observed any of that until the run was over.

**What this guard can and cannot do.** It cannot block prose the way
validator_guard blocks a Bash command — prose is not a tool call, so there is
nothing to deny. It measures instead: it samples the live context from the
session transcript, says so immediately when one turn balloons, and writes the
curve to context-log.jsonl so the cost lands in verify-report.md rather than
requiring transcript archaeology afterwards.

That is weaker than an enforced constraint. It is stated plainly here so no one
mistakes it for one.

Never blocks, never raises: it runs on every tool call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# One turn adding this much means a very long message was just written.
TURN_GROWTH_WARN = 15_000
# Past this, every remaining turn is expensive whatever you do next.
CONTEXT_CEILING = 600_000
# Enough of the tail to hold the last assistant turn without parsing the file.
TAIL_BYTES = 256_000


def latest_usage(transcript_path: Path) -> tuple[int, int] | None:
    """(context_tokens, output_tokens) of the most recent assistant turn.

    Reads only the tail: this runs on every tool call and the transcript of a
    real run reaches 10 MB.
    """
    try:
        path = Path(transcript_path)
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()  # discard the partial line
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None

    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") != "assistant":
            continue
        usage = (record.get("message") or {}).get("usage") or {}
        if "cache_read_input_tokens" in usage:
            return int(usage.get("cache_read_input_tokens") or 0), int(
                usage.get("output_tokens") or 0)
    return None


def advisory(transcript_path: Path, prev: int | None) -> str:
    """What to tell the orchestrator, if anything."""
    usage = latest_usage(transcript_path)
    if usage is None:
        return ""
    context, _output = usage

    if prev is not None and context - prev >= TURN_GROWTH_WARN:
        grew = context - prev
        return (
            f"CONTEXT: that turn added {grew:,} tokens, and your context is now "
            f"{context:,}. Everything you write is re-read on every later turn, so a long "
            f"message here is paid for again on each one. Narrate once per wave, not once "
            f"per agent, and do not restate what an agent returned — the ledgers hold the "
            f"state."
        )
    if context >= CONTEXT_CEILING:
        return (
            f"CONTEXT: {context:,} tokens, past the {CONTEXT_CEILING:,} ceiling. Every "
            f"remaining turn now costs at least this much to re-read. Keep messages to one "
            f"line per wave and push work to subagents, whose context is discarded when "
            f"they finish."
        )
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        # Subagent context is discarded when the agent finishes; only the
        # orchestrator's is re-read on every later turn.
        if payload.get("agent_id"):
            return 0

        from workspace import append_jsonl, get_active_run, utc_now

        cwd = Path(payload.get("cwd") or ".")
        slug = get_active_run(cwd, payload.get("session_id") or "")
        if not slug:
            return 0

        transcript = payload.get("transcript_path")
        if not transcript:
            return 0

        log = cwd / "research" / slug / "context-log.jsonl"
        previous = None
        if log.is_file():
            try:
                last = log.read_text(encoding="utf-8").strip().splitlines()[-1]
                previous = json.loads(last).get("context")
            except (OSError, ValueError, IndexError):
                previous = None

        usage = latest_usage(Path(transcript))
        if usage is None:
            return 0
        context, output = usage

        append_jsonl(log, {"ts": utc_now(), "tool": payload.get("tool_name"),
                           "context": context, "output": output,
                           "grew": None if previous is None else context - previous})

        message = advisory(Path(transcript), previous)
        if message:
            print(message)
    except Exception:  # noqa: BLE001 — never break the run
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
