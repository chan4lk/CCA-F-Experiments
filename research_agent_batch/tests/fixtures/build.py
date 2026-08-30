"""Synthetic workspace builder for gate tests.

Defaults describe a workspace that PASSES every check, so each test mutates
exactly one thing and asserts exactly one failure.
"""
from __future__ import annotations

import json
from pathlib import Path

URL_A = "https://learn.microsoft.com/a"
URL_B = "https://learn.microsoft.com/b"

CLAIM_MATERIAL = {
    "id": "C001", "sub_q": "Q1", "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": URL_A,
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc", "fetched_at": "2026-08-29T09:41:00Z",
}
CLAIM_CONTEXT = {
    "id": "C002", "sub_q": "Q2", "tier": "context",
    "claim": "ServiceNow positions AI Agent Studio for platform-native agents",
    "url": URL_B,
    "quote": "AI Agent Studio lets teams build agents natively on the Now Platform.",
    "source_type": "vendor_doc", "fetched_at": "2026-08-29T09:42:00Z",
}

VERDICTS_OK = [
    {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
     "validator_model": "haiku", "quote": "A maximum of 10 tools per MCP server connection is supported.",
     "ruled_at": "2026-08-29T09:50:00Z"},
    {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-s1",
     "validator_model": "sonnet", "quote": "A maximum of 10 tools per MCP server connection is supported.",
     "ruled_at": "2026-08-29T09:51:00Z"},
    {"claim_id": "C002", "verdict": "CONFIRMED", "validator_agent_id": "val-h2",
     "validator_model": "haiku", "quote": "AI Agent Studio lets teams build agents natively.",
     "ruled_at": "2026-08-29T09:52:00Z"},
]

FETCHES_OK = [
    {"ts": "2026-08-29T09:41:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "res-1", "agent_type": "researcher"},
    {"ts": "2026-08-29T09:42:00Z", "tool": "WebFetch", "url": URL_B, "query": None,
     "agent_id": "res-1", "agent_type": "researcher"},
    {"ts": "2026-08-29T09:50:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "val-h1", "agent_type": "validator"},
    {"ts": "2026-08-29T09:51:00Z", "tool": "WebFetch", "url": URL_A, "query": None,
     "agent_id": "val-s1", "agent_type": "validator"},
    {"ts": "2026-08-29T09:52:00Z", "tool": "WebFetch", "url": URL_B, "query": None,
     "agent_id": "val-h2", "agent_type": "validator"},
]

PACK_OK = """# Evidence Pack

## Capability limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

ServiceNow positions AI Agent Studio for platform-native agents [C002].

## Unverified & excluded

Nothing was excluded in this run.
"""


def make_workspace(tmp_path, claims=None, verdicts=None, fetches=None, pack=None,
                   pack_name="evidence-pack.md") -> Path:
    ws = Path(tmp_path) / "research" / "run-a"
    ws.mkdir(parents=True, exist_ok=True)

    rows = [CLAIM_MATERIAL, CLAIM_CONTEXT] if claims is None else claims
    _write_jsonl(ws / "claims.jsonl", rows)
    _write_jsonl(ws / "verdicts.jsonl", VERDICTS_OK if verdicts is None else verdicts)
    _write_jsonl(ws / "fetch-log.jsonl", FETCHES_OK if fetches is None else fetches)
    (ws / pack_name).write_text(PACK_OK if pack is None else pack, encoding="utf-8")
    return ws


def _write_jsonl(path: Path, rows) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
