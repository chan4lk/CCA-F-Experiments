"""The tool grants, as server-side tool definitions.

The whole of this engine's tool surface is these three functions, so these tests
are where the restrictions live: the domain pin a validator cannot talk its way
past, the variant that must not be sent to a model that would 400 on it, and the
citations flag that would 400 against the structured output every agent uses.
"""
import pytest

from research_agent_batch_server_tools import servertools as st


def test_a_search_grant_is_a_type_a_name_and_a_budget():
    tool = st.web_search("claude-sonnet-5", max_uses=5)
    assert tool["name"] == "web_search"
    assert tool["type"].startswith("web_search_")
    assert tool["max_uses"] == 5


def test_a_fetch_grant_caps_what_a_page_may_cost():
    """A page's text is input tokens on every later turn of the same request, so
    an unbounded fetch of a 400-page PDF spends the budget for the ten pages
    after it."""
    tool = st.web_fetch("claude-sonnet-5", max_uses=5)
    assert tool["max_content_tokens"] == st.MAX_CONTENT_TOKENS


# --- the variant follows the model ----------------------------------------

def test_a_supported_model_gets_the_dynamic_filtering_variant():
    assert st.web_search("claude-sonnet-5", max_uses=1)["type"] == st.WEB_SEARCH_FILTERING
    assert st.web_fetch("claude-opus-5", max_uses=1)["type"] == st.WEB_FETCH_FILTERING


def test_haiku_gets_the_basic_variant():
    """The validator runs on haiku, which does not take the filtering tools. The
    same role therefore ships two different grants depending on which validation
    pass built it."""
    assert st.web_fetch("claude-haiku-4-5", max_uses=1)["type"] == st.WEB_FETCH_BASIC


def test_an_unknown_model_degrades_to_the_variant_that_works_everywhere():
    """A model released after this file was written must not 400 on a tool type
    it has never heard of; the basic tools are supported by every model."""
    assert st.web_search("claude-something-new", max_uses=1)["type"] == st.WEB_SEARCH_BASIC
    assert st.web_fetch("claude-something-new", max_uses=1)["type"] == st.WEB_FETCH_BASIC


def test_every_model_in_the_pipeline_is_classified_one_way_or_the_other():
    from research_agent_batch_server_tools.settings import MODELS
    for model in MODELS.values():
        assert isinstance(st.supports_dynamic_filtering(model), bool)


# --- the domain pin -------------------------------------------------------

def test_an_unpinned_grant_carries_no_allowed_domains():
    """An empty list is not the same as unrestricted, so the key is absent
    rather than empty."""
    assert "allowed_domains" not in st.web_fetch("claude-sonnet-5", max_uses=1)


def test_a_pinned_grant_names_its_host():
    tool = st.web_fetch("claude-haiku-4-5", max_uses=3,
                        allowed_domains=["learn.microsoft.com"])
    assert tool["allowed_domains"] == ["learn.microsoft.com"]


def test_host_of_lowercases_and_drops_everything_but_the_host():
    assert st.host_of("https://Learn.Microsoft.COM/en-us/x?y=1#z") == "learn.microsoft.com"


def test_host_of_survives_a_url_that_is_not_one():
    """A malformed url in a ledger row must produce an empty pin rather than an
    exception in the middle of assembling a wave."""
    assert st.host_of("not a url") == ""
    assert st.host_of("") == ""


# --- what must never be set -----------------------------------------------

@pytest.mark.parametrize("model", ["claude-sonnet-5", "claude-haiku-4-5"])
def test_citations_are_never_enabled_on_a_fetch(model):
    """Citations make the API return cited text blocks, which is a 400 alongside
    `output_config.format` — and every agent here ends on a structured object.
    Enabling it would fail every request in the wave at once."""
    assert "citations" not in st.web_fetch(model, max_uses=1)


def test_a_grant_never_sets_both_domain_lists():
    """`allowed_domains` and `blocked_domains` together are a validation error."""
    for tool in (st.web_search("claude-sonnet-5", max_uses=1, allowed_domains=["a.com"]),
                 st.web_fetch("claude-sonnet-5", max_uses=1, allowed_domains=["a.com"])):
        assert "blocked_domains" not in tool
