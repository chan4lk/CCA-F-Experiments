"""Model pinning, spend ceilings, and the tool budgets.

Batch requests are billed at 50% of standard rates, which changes what a model
choice costs but not which model is right for a job. The pairing below is the
same one `research-agent` and `research_agent_batch` use, so all three are
comparable: only the engine differs.

What is missing from here compared to `research_agent_batch` is the whole
search-provider section — no Brave key, no Serper key, no keyless fallback to
scrape. Searching happens on Anthropic's servers now, so there is no backend to
choose and no run that can quietly change one.

What is new is `MAX_USES`. A server tool runs unattended inside one request, so
the thing that bounds it is a budget stated up front rather than a loop this
process gets to interrupt.
"""
from __future__ import annotations

import os

MODELS: dict[str, str] = {
    "planner": "claude-sonnet-5",
    "researcher": "claude-sonnet-5",
    "validator": "claude-haiku-4-5",
    # A material claim needs two CONFIRMED rulings from two different validators
    # running two different models. This is the second one.
    "validator-escalation": "claude-sonnet-5",
    "gap-hunter": "claude-opus-5",
    "synthesizer": "claude-fable-5",
    "proposal-writer": "claude-fable-5",
}

# Batch pricing is half of standard. Kept here so the run's cost estimate says
# what it actually cost rather than what the same work would have cost live.
BATCH_DISCOUNT = 0.5

# Per-MTok list prices, for estimating a run's cost from reported usage. The
# Batches API does not return a dollar figure the way the Agent SDK does.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

# Server-side search bills per search on top of tokens: $10 per 1,000. This is
# the line item the sibling does not have — it pays for search with a Brave
# subscription instead, off this ledger entirely, which makes its reported cost
# look lower than its real one.
#
# Counted at list rate. The 50% batch discount is applied to tokens only, so if
# the surcharge is discounted too the figure here is an over-estimate — which is
# the direction a cost report should be wrong in.
WEB_SEARCH_USD_PER_REQUEST = 10.0 / 1000

# web_fetch has no per-request charge; a fetched page is billed as the input
# tokens it becomes, which MAX_CONTENT_TOKENS in servertools.py caps.


def model_for(role: str) -> str:
    """The pinned model for a role, overridable per role from the environment."""
    env_key = "RESEARCH_SERVER_MODEL_" + role.upper().replace("-", "_")
    return os.environ.get(env_key) or MODELS[role]


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             web_searches: int = 0, batch: bool = True) -> float:
    """Estimated dollars for one request's usage.

    Unknown models price at zero rather than guessing: a made-up number in a
    cost report is worse than a visible gap. Server-tool searches are still
    counted for an unknown model — they are priced per request, not per token,
    so the model does not come into it.
    """
    rates = PRICES_USD_PER_MTOK.get(model)
    tokens = 0.0
    if rates:
        tokens = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
        tokens *= BATCH_DISCOUNT if batch else 1.0
    return tokens + web_searches * WEB_SEARCH_USD_PER_REQUEST


# --- what one request may spend on tools ----------------------------------

# Server tools run unattended: the model searches, reads, searches again and
# answers, all inside one request that this process cannot interrupt. `max_uses`
# is therefore the only brake, and it is enforced by the API rather than by a
# round ceiling here.
#
# Exceeding it is not an error — the tool comes back refused and the model is
# expected to answer with what it has. A researcher that hits the ceiling
# reports fewer claims; it does not fail.
MAX_USES: dict[str, dict[str, int]] = {
    # Enough to work several angles on one sub-question and read the good ones.
    "researcher": {"web_search": 8, "web_fetch": 15},
    # One page, one fetch — plus headroom for a redirect chain or a retry after
    # a transient failure. A validator that needs a fourth attempt at a single
    # URL is not going to rule CONFIRMED on the fifth.
    "validator": {"web_fetch": 3},
    # Establishing that material on a topic exists, and stopping there. No
    # fetch: reading the page would be doing the researcher's job.
    "gap-hunter": {"web_search": 6},
}


def max_uses(role: str, tool: str, default: int = 0) -> int:
    return MAX_USES.get(role, {}).get(tool, default)


# --- the shape of the loop that is left -----------------------------------

# A server-tool turn that runs long comes back `stop_reason: "pause_turn"`: the
# work so far is in the message and the turn is expected to be resubmitted to
# continue. That is the only reason a request here comes back unfinished, and
# resubmitting is the only continuation this engine performs — there are no tool
# results to compute, so a continuation round is a resend of what came back.
#
# The sibling's ceilings bound an agent loop it runs itself (a researcher taking
# ten turns is ten batches). These bound something much rarer, so they are much
# smaller. A run that trips them has a request that will not converge.
MAX_CONTINUATIONS: dict[str, int] = {
    "planner": 1,
    "researcher": 4,
    "validator": 2,
    "gap-hunter": 3,
    "synthesizer": 1,
    "proposal-writer": 1,
}

# How long to sleep between polls when running with --wait. Most batches finish
# well inside an hour; the SLA is 24.
POLL_SECONDS = 30


def poll_seconds() -> int:
    try:
        return max(1, int(os.environ.get("RESEARCH_SERVER_POLL_SECONDS", POLL_SECONDS)))
    except ValueError:
        return POLL_SECONDS
