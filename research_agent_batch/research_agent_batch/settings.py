"""Model pinning, spend ceilings, and the search backend.

Batch requests are billed at 50% of standard rates, which changes what a model
choice costs but not which model is right for a job. The pairing below is the
same one `research-agent` uses, so the two are comparable: only the engine
differs.
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


def model_for(role: str) -> str:
    """The pinned model for a role, overridable per role from the environment."""
    env_key = "RESEARCH_BATCH_MODEL_" + role.upper().replace("-", "_")
    return os.environ.get(env_key) or MODELS[role]


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             batch: bool = True) -> float:
    """Estimated dollars for one request's usage.

    Unknown models price at zero rather than guessing: a made-up number in a
    cost report is worse than a visible gap.
    """
    rates = PRICES_USD_PER_MTOK.get(model)
    if not rates:
        return 0.0
    dollars = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
    return dollars * (BATCH_DISCOUNT if batch else 1.0)


# --- the agent loop's shape ----------------------------------------------

# One batch carries every active agent's next turn, so a wave of nine
# researchers taking six turns each is six batches. This caps the turns, which
# is what caps the batches.
MAX_ROUNDS: dict[str, int] = {
    "planner": 2,
    "researcher": 10,
    "validator": 4,
    "gap-hunter": 5,
    "synthesizer": 2,
    "proposal-writer": 2,
}

# How long to sleep between polls when running with --wait. Most batches finish
# well inside an hour; the SLA is 24.
POLL_SECONDS = 30


def poll_seconds() -> int:
    try:
        return max(1, int(os.environ.get("RESEARCH_BATCH_POLL_SECONDS", POLL_SECONDS)))
    except ValueError:
        return POLL_SECONDS


# --- the search backend --------------------------------------------------

# Client-side tools mean this process performs the search, so a provider is
# needed. Brave and Serper are key-based JSON APIs; the DuckDuckGo fallback
# needs no key and is best-effort.
SEARCH_PROVIDER_ENV = "RESEARCH_BATCH_SEARCH_PROVIDER"
BRAVE_KEY_ENV = "BRAVE_SEARCH_API_KEY"
SERPER_KEY_ENV = "SERPER_API_KEY"


def search_provider_name() -> str:
    """Which provider to use: explicit choice, else whichever key is present."""
    explicit = os.environ.get(SEARCH_PROVIDER_ENV)
    if explicit:
        return explicit.strip().lower()
    if os.environ.get(BRAVE_KEY_ENV):
        return "brave"
    if os.environ.get(SERPER_KEY_ENV):
        return "serper"
    return "duckduckgo"


# A fetched page larger than this is truncated rather than dropped. WebFetch in
# the Agent SDK refuses anything over 10 MB outright and returns nothing, which
# cost one run six claims to a single oversized PDF.
MAX_FETCH_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 120_000
FETCH_TIMEOUT_SECONDS = 60
