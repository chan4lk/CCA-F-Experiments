"""Hook callbacks, bound to the agent the orchestrator is about to dispatch.

The plugin's hooks were standalone scripts that read a JSON payload on stdin and
had to *recover* their context from it: which run is active (from a session-id
map on disk), and who is calling (from an `agent_id` Claude Code attached to
tool-lifecycle events fired inside a Task-spawned subagent).

Neither recovery is needed here. Python dispatches every agent, so the workspace
and the caller's identity are values in scope when the hook is built, and each
factory below closes over them. That deletes the plugin's single worst failure
mode outright: a mistyped session-id key left `fetch-log.jsonl` empty, and an
empty fetch log fails every claim's provenance an hour later at the gate.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import HookContext, HookMatcher

from .ledger.workspace import append_jsonl, utc_now

# PostToolUse matcher for tools that retrieve a page. Bash is deliberately absent:
# a page read with curl leaves no provenance, which is why the researcher no
# longer holds Bash at all.
FETCH_MATCHER = r"WebFetch|WebSearch|mcp__microsoft_docs_mcp__.*"

WRITE_MATCHER = r"Write|Edit|NotebookEdit"
VALIDATOR_MATCHER = r"Bash|WebSearch|Read|Grep|Glob|NotebookEdit"

GUARDED_LEDGERS = {"claims.jsonl": "add_claim", "verdicts.jsonl": "the orchestrator"}

# Anything that would reveal what the researcher wrote, or what another validator
# ruled. Matched against raw command text, so an absolute path, a relative path
# and a glob are all caught.
LEDGER_NAMES = (
    "claims.jsonl", "verdicts.jsonl", "internal-claims.jsonl", "carried-claims.jsonl",
    "fetch-log.jsonl", "evidence-pack.md", "plan.md", "gaps.md", "proposal.md",
)
# Longest first, so `internal-claims.jsonl` is named as itself rather than as
# `claims.jsonl`, which it contains. The block was right either way; the message
# was not, and a denial that names the wrong file sends the agent looking in the
# wrong place.
LEDGER_NAMES_BY_LENGTH = tuple(sorted(LEDGER_NAMES, key=len, reverse=True))
WORKSPACE_RE = re.compile(r"(^|[\s'\"=/])research/", re.MULTILINE)

# Tools that read the local filesystem. The validator is granted none of these;
# this is defence in depth against a future grant.
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookEdit"}


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def fetch_recorder(workspace: Path, agent_id: str, agent_type: str):
    """PostToolUse: record every retrieval against the agent that made it.

    This is the provenance spine. A URL cited in the evidence pack but absent
    from fetch-log.jsonl is the exact signature of a hallucinated citation, and
    the agent_id lets the gate prove the validator that ruled on a claim fetched
    that claim's URL itself.

    Never blocks. Any failure is swallowed — a logging hook that raises would
    take the whole run down with it.
    """
    log = Path(workspace) / "fetch-log.jsonl"

    async def record(payload: dict, tool_use_id: str | None, context: HookContext) -> dict:
        try:
            tool_input = payload.get("tool_input") or {}
            append_jsonl(log, {
                "ts": utc_now(),
                "tool": payload.get("tool_name"),
                "url": tool_input.get("url"),
                "query": tool_input.get("query"),
                "agent_id": agent_id,
                "agent_type": agent_type,
            })
        except Exception:  # noqa: BLE001 — never break the run
            pass
        return {}

    return record


def ledger_guard():
    """PreToolUse: deny direct writes to the append-only ledgers.

    No agent is granted a tool that can reach these — the researcher has no Write
    and the writers have no ledger to write to. This guard is what makes that a
    property of the system rather than of the current tool lists.
    """
    async def guard(payload: dict, tool_use_id: str | None, context: HookContext) -> dict:
        file_path = ((payload.get("tool_input") or {}).get("file_path")) or ""
        name = Path(file_path).name
        if name not in GUARDED_LEDGERS:
            return {}
        return _deny(
            f"{name} is append-only and written concurrently by parallel agents. A direct "
            f"write would clobber other agents' rows and skip validation. It is written by "
            f"{GUARDED_LEDGERS[name]}, and nothing else."
        )

    return guard


def validator_guard(workspace: Path):
    """PreToolUse: keep the validator blind, mechanically.

    The validator holds Bash because WebFetch cannot decode a PDF binary, and
    `cat claims.jsonl` is a read. So blindness is enforced here: a validator may
    fetch and convert a document; it may not reach the workspace, and it may not
    search.
    """
    workspace = Path(workspace)
    # Both spellings the agent could plausibly type for its own run directory.
    paths = {str(workspace), str(workspace.resolve())}

    async def guard(payload: dict, tool_use_id: str | None, context: HookContext) -> dict:
        tool = payload.get("tool_name") or ""
        if tool == "WebSearch":
            return _deny(_why("a validator may not search."))
        if tool in READ_TOOLS:
            return _deny(_why(f"a validator may not use {tool} on the local filesystem."))
        if tool != "Bash":
            return {}

        command = str((payload.get("tool_input") or {}).get("command") or "")
        hit = next((n for n in LEDGER_NAMES_BY_LENGTH if n in command), None)
        if hit:
            return _deny(_why(f"that command touches {hit}, which is run state you must not read."))
        if any(p in command for p in paths) or WORKSPACE_RE.search(command):
            return _deny(_why("that command reaches into the research workspace."))
        return {}

    return guard


def _why(what: str) -> str:
    return (
        f"BLOCKED: {what}\n\n"
        f"You are a validator. Your independence is the point: you rule on a claim having "
        f"seen only the claim text and its URL. Reaching the workspace would show you the "
        f"researcher's own quote, and searching would let you find a friendlier source than "
        f"the one cited.\n\n"
        f"Fetch the cited URL and rule on what that page says. If you cannot read it, return "
        f"NOT_FOUND — that is a valid and useful answer."
    )


def hooks_for(role_name: str, workspace: Path, agent_id: str) -> dict[str, list[HookMatcher]]:
    """The hook set for one dispatch. Every role records its own retrievals."""
    pre = [HookMatcher(matcher=WRITE_MATCHER, hooks=[ledger_guard()])]
    if role_name == "validator":
        pre.append(HookMatcher(matcher=VALIDATOR_MATCHER, hooks=[validator_guard(workspace)]))
    return {
        "PreToolUse": pre,
        "PostToolUse": [
            HookMatcher(matcher=FETCH_MATCHER,
                        hooks=[fetch_recorder(workspace, agent_id, role_name)]),
        ],
    }
