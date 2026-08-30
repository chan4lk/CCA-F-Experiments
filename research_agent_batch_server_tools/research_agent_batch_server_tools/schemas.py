"""JSON schemas for the structured turn each agent ends on.

The Agent SDK port could let an agent write its own file with a Write tool and
parse the markdown afterwards. Nothing here has a filesystem: a batch request
returns a message and nothing else. So every agent ends on a structured object
this process writes to disk, which removes markdown parsing from the pipeline
entirely — a malformed heading can no longer cost a sub-question its researcher.
"""
from __future__ import annotations

from typing import Any


def _format(schema: dict[str, Any]) -> dict[str, Any]:
    return {"format": {"type": "json_schema", "schema": schema}}


SUB_QUESTION = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Q1, Q2, ... or G1, G2 for a gap."},
        "question": {"type": "string",
                     "description": "Stated in full, answerable by someone who has read "
                                    "none of the others."},
        "tier": {"type": "string", "enum": ["material", "context"]},
        "good_answer": {"type": "string",
                        "description": "What would settle this, so a researcher knows "
                                       "when to stop."},
        "seeded_by": {"type": ["string", "null"],
                      "description": "An internal note id, if one prompted this."},
    },
    "required": ["id", "question", "tier", "good_answer"],
    "additionalProperties": False,
}

PLAN = _format({
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "What this pack is about."},
        "sub_questions": {"type": "array", "items": SUB_QUESTION,
                          "minItems": 1, "maxItems": 12},
    },
    "required": ["subject", "sub_questions"],
    "additionalProperties": False,
})

CLAIM = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Zero-padded, inside your assigned range: C012."},
        "tier": {"type": "string", "enum": ["material", "context"]},
        "claim": {"type": "string", "description": "One factual statement, in your words."},
        "url": {"type": "string", "description": "The page the quote is on."},
        "quote": {"type": "string",
                  "description": "The verbatim sentence from the page. Max 50 words. "
                                 "Copied, not summarised."},
        "source_type": {"type": "string",
                        "enum": ["vendor_doc", "regulator", "analyst", "blog", "forum"]},
    },
    "required": ["id", "tier", "claim", "url", "quote", "source_type"],
    "additionalProperties": False,
}

CLAIMS = _format({
    "type": "object",
    "properties": {
        "sub_q": {"type": "string"},
        "claims": {"type": "array", "items": CLAIM},
        "could_not_source": {
            "type": "array", "items": {"type": "string"},
            "description": "Anything you looked for and could not stand up. Say so here "
                           "rather than inferring it.",
        },
    },
    "required": ["sub_q", "claims", "could_not_source"],
    "additionalProperties": False,
})

VERDICT = _format({
    "type": "object",
    "properties": {
        "claim_id": {"type": "string"},
        "verdict": {"type": "string",
                    "enum": ["CONFIRMED", "CONTRADICTED", "NOT_FOUND", "MISLEADING"]},
        "quote": {"type": ["string", "null"],
                  "description": "Your OWN verbatim quote from the page. Required for "
                                 "CONFIRMED, CONTRADICTED and MISLEADING."},
        "caveat": {"type": ["string", "null"],
                   "description": "Required for MISLEADING: what a reader would wrongly "
                                  "conclude from the claim as stated."},
    },
    "required": ["claim_id", "verdict"],
    "additionalProperties": False,
})

GAPS = _format({
    "type": "object",
    "properties": {
        "complete": {"type": "boolean",
                     "description": "True if the pack is genuinely complete. That is a "
                                    "valid result; emit no gaps with it."},
        "gaps": {"type": "array", "items": SUB_QUESTION},
    },
    "required": ["complete", "gaps"],
    "additionalProperties": False,
})

# The pack and the proposal are markdown by nature — the gate reads their prose
# and the vault builder parses their headings — so these two return one string.
PACK = _format({
    "type": "object",
    "properties": {
        "markdown": {"type": "string", "description": "The complete document."},
    },
    "required": ["markdown"],
    "additionalProperties": False,
})
