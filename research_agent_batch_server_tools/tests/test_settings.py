"""Model pinning, batch pricing, and the budgets that bound a server tool."""
import pytest

from research_agent_batch_server_tools import settings
from research_agent_batch_server_tools.settings import (
    BATCH_DISCOUNT,
    MAX_CONTINUATIONS,
    MAX_USES,
    MODELS,
    PRICES_USD_PER_MTOK,
    WEB_SEARCH_USD_PER_REQUEST,
    cost_usd,
    max_uses,
    model_for,
    poll_seconds,
)


def test_every_role_has_a_pinned_model():
    for role in ("planner", "researcher", "validator", "validator-escalation",
                 "gap-hunter", "synthesizer", "proposal-writer"):
        assert MODELS[role].startswith("claude-")


def test_a_model_can_be_overridden_per_role(monkeypatch):
    monkeypatch.setenv("RESEARCH_SERVER_MODEL_VALIDATOR", "claude-sonnet-5")
    assert model_for("validator") == "claude-sonnet-5"
    assert model_for("planner") == MODELS["planner"]


def test_the_escalation_role_maps_to_its_own_env_var(monkeypatch):
    """The hyphen has to become an underscore or the override silently misses."""
    monkeypatch.setenv("RESEARCH_SERVER_MODEL_VALIDATOR_ESCALATION", "claude-opus-5")
    assert model_for("validator-escalation") == "claude-opus-5"


def test_the_pipeline_matches_research_agents_pairing():
    """The three ports differ in engine, not in model choice — otherwise a cost
    comparison between them measures the wrong thing."""
    assert MODELS["validator"] == "claude-haiku-4-5"
    assert MODELS["gap-hunter"] == "claude-opus-5"
    assert MODELS["synthesizer"] == "claude-fable-5"


def test_there_is_no_search_provider_to_choose():
    """The sibling picks between Brave, Serper and a keyless scrape, and a run
    that picks wrong changes its search backend without saying so. Searching is
    server-side here, so the whole surface is gone rather than defaulted."""
    for name in dir(settings):
        assert "SEARCH_PROVIDER" not in name.upper()
        assert "BRAVE" not in name.upper()
        assert "SERPER" not in name.upper()


# --- pricing --------------------------------------------------------------

def test_batch_work_is_half_price():
    assert BATCH_DISCOUNT == 0.5
    live = cost_usd("claude-sonnet-5", 1_000_000, 0, batch=False)
    assert cost_usd("claude-sonnet-5", 1_000_000, 0) == pytest.approx(live / 2)


def test_prices_are_per_mtok():
    assert cost_usd("claude-haiku-4-5", 1_000_000, 0, batch=False) == 1.0
    assert cost_usd("claude-haiku-4-5", 0, 1_000_000, batch=False) == 5.0


def test_an_unknown_models_tokens_price_at_zero_rather_than_guessing():
    """A made-up number in a cost report is worse than a visible gap."""
    assert cost_usd("claude-something-new", 1_000_000, 1_000_000) == 0.0


def test_every_pinned_model_has_a_price():
    """Otherwise a run reports $0.00 and nobody notices until the invoice."""
    for role, model in MODELS.items():
        assert model in PRICES_USD_PER_MTOK, f"{role} -> {model} has no price"


def test_searching_is_a_line_item_of_its_own():
    """The cost the sibling does not report, because it pays for search with a
    Brave subscription that is off its ledger entirely."""
    assert WEB_SEARCH_USD_PER_REQUEST == pytest.approx(0.01)
    assert cost_usd("claude-haiku-4-5", 0, 0, web_searches=100) == pytest.approx(1.0)


def test_searches_are_counted_even_for_an_unknown_model():
    """They are billed per request, so the model does not come into it — and a
    zeroed token estimate must not zero the search bill along with it."""
    assert cost_usd("claude-something-new", 0, 0, web_searches=50) == pytest.approx(0.5)


def test_tokens_and_searches_add_up():
    tokens = cost_usd("claude-sonnet-5", 1_000_000, 0)
    assert cost_usd("claude-sonnet-5", 1_000_000, 0, web_searches=10) == \
        pytest.approx(tokens + 0.1)


# --- tool budgets ---------------------------------------------------------

def test_only_the_roles_that_hold_tools_have_budgets():
    assert set(MAX_USES) == {"researcher", "validator", "gap-hunter"}


def test_a_role_without_a_budget_for_a_tool_gets_zero():
    """Not a permissive default: a missing budget is a missing grant."""
    assert max_uses("synthesizer", "web_search") == 0
    assert max_uses("gap-hunter", "web_fetch") == 0


def test_every_budget_is_a_real_ceiling():
    for role, tools in MAX_USES.items():
        for tool, limit in tools.items():
            assert 0 < limit <= 20, f"{role}.{tool}"


def test_the_validator_gets_barely_more_than_one_fetch():
    """One page, one fetch, plus a redirect or a retry. A validator that needs a
    fourth attempt at a single URL is not going to rule CONFIRMED on the fifth."""
    assert max_uses("validator", "web_fetch") <= 3


def test_the_researcher_gets_the_largest_budget():
    """It is the only role that searches, reads several pages, and then writes."""
    assert max_uses("researcher", "web_fetch") == max(
        limit for tools in MAX_USES.values() for limit in tools.values())


# --- what is left of the loop ---------------------------------------------

def test_every_role_bounds_its_continuations():
    assert set(MAX_CONTINUATIONS) == set(MODELS) - {"validator-escalation"}


def test_continuations_are_a_much_smaller_number_than_the_siblings_rounds():
    """The sibling's ceilings bound an agent loop it runs itself. These bound
    `pause_turn` alone, which is rare, so a large ceiling would just be a long
    wait before admitting a request will not converge."""
    assert max(MAX_CONTINUATIONS.values()) <= 4


def test_a_toolless_role_needs_no_continuation_at_all():
    """With no server tools there is nothing long-running to pause."""
    for role in ("planner", "synthesizer", "proposal-writer"):
        assert MAX_CONTINUATIONS[role] == 1


def test_polling_is_configurable(monkeypatch):
    monkeypatch.setenv("RESEARCH_SERVER_POLL_SECONDS", "5")
    assert poll_seconds() == 5


def test_a_nonsense_poll_interval_falls_back(monkeypatch):
    monkeypatch.setenv("RESEARCH_SERVER_POLL_SECONDS", "soon")
    assert poll_seconds() > 0


def test_polling_never_becomes_a_busy_loop(monkeypatch):
    monkeypatch.setenv("RESEARCH_SERVER_POLL_SECONDS", "0")
    assert poll_seconds() >= 1
