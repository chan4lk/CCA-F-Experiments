"""Model pinning and batch pricing."""
import pytest

from research_agent_batch.settings import (
    BATCH_DISCOUNT,
    MAX_ROUNDS,
    MODELS,
    PRICES_USD_PER_MTOK,
    cost_usd,
    model_for,
    poll_seconds,
    search_provider_name,
)


def test_every_role_has_a_pinned_model():
    for role in ("planner", "researcher", "validator", "validator-escalation",
                 "gap-hunter", "synthesizer", "proposal-writer"):
        assert MODELS[role].startswith("claude-")


def test_a_model_can_be_overridden_per_role(monkeypatch):
    monkeypatch.setenv("RESEARCH_BATCH_MODEL_VALIDATOR", "claude-sonnet-5")
    assert model_for("validator") == "claude-sonnet-5"
    assert model_for("planner") == MODELS["planner"]


def test_the_escalation_role_maps_to_its_own_env_var(monkeypatch):
    """The hyphen has to become an underscore or the override silently misses."""
    monkeypatch.setenv("RESEARCH_BATCH_MODEL_VALIDATOR_ESCALATION", "claude-opus-5")
    assert model_for("validator-escalation") == "claude-opus-5"


def test_the_pipeline_matches_research_agents_pairing():
    """The two ports differ in engine, not in model choice — otherwise a cost
    comparison between them measures the wrong thing."""
    assert MODELS["validator"] == "claude-haiku-4-5"
    assert MODELS["gap-hunter"] == "claude-opus-5"
    assert MODELS["synthesizer"] == "claude-fable-5"


# --- pricing --------------------------------------------------------------

def test_batch_work_is_half_price():
    assert BATCH_DISCOUNT == 0.5
    live = cost_usd("claude-sonnet-5", 1_000_000, 0, batch=False)
    assert cost_usd("claude-sonnet-5", 1_000_000, 0) == pytest.approx(live / 2)


def test_prices_are_per_mtok():
    assert cost_usd("claude-haiku-4-5", 1_000_000, 0, batch=False) == 1.0
    assert cost_usd("claude-haiku-4-5", 0, 1_000_000, batch=False) == 5.0


def test_an_unknown_model_prices_at_zero_rather_than_guessing():
    """A made-up number in a cost report is worse than a visible gap."""
    assert cost_usd("claude-something-new", 1_000_000, 1_000_000) == 0.0


def test_every_pinned_model_has_a_price():
    """Otherwise a run reports $0.00 and nobody notices until the invoice."""
    for role, model in MODELS.items():
        assert model in PRICES_USD_PER_MTOK, f"{role} -> {model} has no price"


# --- the loop's shape -----------------------------------------------------

def test_every_role_has_a_round_ceiling():
    assert set(MAX_ROUNDS) == set(MODELS) - {"validator-escalation"}


def test_polling_is_configurable(monkeypatch):
    monkeypatch.setenv("RESEARCH_BATCH_POLL_SECONDS", "5")
    assert poll_seconds() == 5


def test_a_nonsense_poll_interval_falls_back(monkeypatch):
    monkeypatch.setenv("RESEARCH_BATCH_POLL_SECONDS", "soon")
    assert poll_seconds() > 0


def test_polling_never_becomes_a_busy_loop(monkeypatch):
    monkeypatch.setenv("RESEARCH_BATCH_POLL_SECONDS", "0")
    assert poll_seconds() >= 1


# --- search selection -----------------------------------------------------

def test_the_keyless_provider_is_the_default(monkeypatch):
    for key in ("RESEARCH_BATCH_SEARCH_PROVIDER", "BRAVE_SEARCH_API_KEY",
                "SERPER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert search_provider_name() == "duckduckgo"


def test_a_present_key_selects_its_provider(monkeypatch):
    monkeypatch.delenv("RESEARCH_BATCH_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    assert search_provider_name() == "brave"


def test_an_explicit_choice_wins_over_a_present_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    monkeypatch.setenv("RESEARCH_BATCH_SEARCH_PROVIDER", "serper")
    assert search_provider_name() == "serper"
