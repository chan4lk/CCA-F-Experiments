"""fetch-log.jsonl — every retrieval, and which agent caused it.

The gate reads this file to prove two things: that a cited page was actually
retrieved during the run, and that the validator who ruled on a claim opened
that claim's page itself. Both checks are the difference between a citation and
a plausible-looking string.

The Agent SDK port had to observe retrievals through a PostToolUse hook, because
the harness performed them. Here this process performs them, so a row is written
at the moment the socket closes — the log is a record of what happened rather
than a reconstruction of it.
"""
from __future__ import annotations

from pathlib import Path

from .ledger.workspace import append_jsonl, utc_now
from .tools import Retrieval


def record(workspace: Path, agent_id: str, agent_type: str,
           retrievals: list[Retrieval]) -> int:
    """Log what one agent retrieved this round. Returns how many rows landed."""
    log = Path(workspace) / "fetch-log.jsonl"
    for item in retrievals:
        append_jsonl(log, {
            "ts": utc_now(),
            # web_fetch/web_search here rather than WebFetch/WebSearch: these are
            # this repo's tools, not the harness's, and naming them otherwise
            # would imply a provenance the run does not have.
            "tool": item.tool,
            "url": item.url,
            "query": item.query,
            "agent_id": agent_id,
            "agent_type": agent_type,
        })
    return len(retrievals)
