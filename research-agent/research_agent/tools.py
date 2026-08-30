"""The in-process MCP server the researcher writes claims through.

In the plugin a researcher recorded a claim by shelling out:

    python3 "$CLAUDE_PLUGIN_ROOT/scripts/add_claim.py" --workspace ... --json '{...}'

which meant every researcher had to hold Bash. Bash is a very large grant for
one append, and it came with a real cost: a page read with `curl` leaves no
trace in the retrieval log, and one run lost 17 claims that way — discovered an
hour later at the gate.

Running the same append as an in-process tool removes the grant and the hole
together. The researcher's whole write surface is this one validated call.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

from .agents import LEDGER_SERVER
from .ledger.claims import append_claim

ADD_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Claim id, zero-padded: C012. Must be "
                                                "inside the range you were given."},
        "sub_q": {"type": "string", "description": "The sub-question id, e.g. Q3."},
        "tier": {"type": "string", "enum": ["material", "context"]},
        "claim": {"type": "string", "description": "One factual statement, in your words."},
        "url": {"type": "string", "description": "The http(s) page the quote is on. Never "
                                                 "a web.archive.org mirror."},
        "quote": {"type": "string", "description": "The verbatim sentence from the page "
                                                   "that states the claim. Max 50 words."},
        "source_type": {"type": "string",
                        "enum": ["vendor_doc", "regulator", "analyst", "blog", "forum"]},
        "raw_hash": {"type": "string", "description": "Optional hex hash from "
                                                      "headroom_compress. Omit it rather "
                                                      "than writing a placeholder."},
    },
    "required": ["id", "sub_q", "tier", "claim", "url", "quote", "source_type"],
    "additionalProperties": False,
}


def ledger_server(workspace: Path):
    """An MCP server whose one tool appends to *this* run's claim ledger.

    The workspace is closed over rather than passed as a parameter, so a
    researcher cannot write into another run's ledger even by accident.
    """
    workspace = Path(workspace)

    @tool(
        "add_claim",
        "Append one validated claim to the run's claim ledger. Rejects malformed rows "
        "with reasons, and warns when the cited URL has no recorded retrieval.",
        ADD_CLAIM_SCHEMA,
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
    )
    async def add_claim(args: dict[str, Any]) -> dict[str, Any]:
        row = {k: v for k, v in args.items() if v is not None}
        ok, message, warning = append_claim(workspace, row)
        text = ("OK: " if ok else "REJECTED: ") + message
        if warning:
            # Surfaced to the researcher now, while it still has the page in
            # context — not an hour later at the gate.
            text += "\n\n" + warning
        return {"content": [{"type": "text", "text": text}], "is_error": not ok}

    return create_sdk_mcp_server(name=LEDGER_SERVER, version="1.0.0", tools=[add_claim])
