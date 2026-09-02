"""Batch path: half the cost, up to 24h, no latency SLA. Right for an overnight run
over a document backlog, wrong for anything a user is waiting on.

The batch API cannot run a tool loop inside a request, so the retry from extract.py
does not exist here - a failed record comes back in the next batch instead.
"""

import json
from pathlib import Path

import anthropic
import prompts
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv
from extract import tool_choice
from review import route
from schema import TOOLS
from settings import MAX_TOKENS, MODEL
from validate import validate

load_dotenv()

STATE = Path("batch-state.json")


def _params(document: str, doc_type: str | None):
    return MessageCreateParamsNonStreaming(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": prompts.SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        tool_choice=tool_choice(doc_type),
        messages=[{"role": "user", "content": document}],
    )


def submit(documents: dict[str, str], doc_type: str | None = None, client=None) -> str:
    """documents maps custom_id -> text. The id is the only handle on a result:
    results come back in arbitrary order, so nothing may be matched by position."""
    client = client or anthropic.Anthropic()
    batch = client.messages.batches.create(
        requests=[Request(custom_id=cid, params=_params(text, doc_type)) for cid, text in documents.items()]
    )
    STATE.write_text(json.dumps({"batch_id": batch.id, "custom_ids": list(documents)}, indent=2))
    return batch.id


def status(batch_id: str | None = None, client=None) -> str:
    client = client or anthropic.Anthropic()
    return client.messages.batches.retrieve(batch_id or _load()["batch_id"]).processing_status


def collect(batch_id: str | None = None, client=None):
    """Returns (records, failed_ids). Resubmit only the failures - a whole-batch
    resubmit pays again for every document that already succeeded."""
    client = client or anthropic.Anthropic()
    records, failed = {}, []

    for entry in client.messages.batches.results(batch_id or _load()["batch_id"]):
        if entry.result.type != "succeeded":
            failed.append((entry.custom_id, entry.result.type))
            continue
        block = next((b for b in entry.result.message.content if b.type == "tool_use"), None)
        if block is None:
            failed.append((entry.custom_id, "no_tool_use"))
            continue
        issues = validate(block.input)
        records[entry.custom_id] = {
            "tool_name": block.name,
            "record": block.input,
            "issues": [str(i) for i in issues],
            "decision": route(block.input, issues),
        }

    return records, failed


def _load() -> dict:
    if not STATE.exists():
        raise RuntimeError(f"no {STATE} - submit a batch first")
    return json.loads(STATE.read_text())
