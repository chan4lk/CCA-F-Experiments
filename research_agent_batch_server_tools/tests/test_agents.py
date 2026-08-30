"""The tool grants and the prompt contracts.

Here a grant is a list of *server* tools, so the API enforces it: an agent not
given `web_search` cannot search, and there is no dispatcher in this repo that
could be talked into running one for it.

A grant is built per request rather than carried on the Role, because both of
the things that shape it are per-request — the tool type variant follows the
model, and `allowed_domains` follows the claim — so most of what is checked
here is `Role.tools()`, not a static attribute.
"""
import pytest

from research_agent_batch_server_tools import schemas
from research_agent_batch_server_tools.agents import (
    GAP_HUNTER,
    PLANNER,
    PROPOSAL_WRITER,
    RESEARCHER,
    ROLES,
    SYNTHESIZER,
    VALIDATOR,
)

EXPECTED_TOOLS = {
    "planner": set(),
    "researcher": {"web_search", "web_fetch"},
    "validator": {"web_fetch"},
    "gap-hunter": {"web_search"},
    "synthesizer": set(),
    "proposal-writer": set(),
}


def test_every_role_is_registered():
    assert set(ROLES) == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_tool_sets_match_the_design(name):
    assert set(ROLES[name].tool_names) == EXPECTED_TOOLS[name]


def test_every_role_has_a_description_a_prompt_and_a_schema():
    for name, role in ROLES.items():
        assert role.description, name
        assert len(role.prompt()) > 400, name
        assert role.output_config["format"]["type"] == "json_schema", name


# --- blindness ------------------------------------------------------------

def test_a_validator_cannot_search():
    """Searching is how a validator finds a friendlier source than the one it
    was asked about."""
    assert "web_search" not in VALIDATOR.tool_names


def test_a_validator_can_only_fetch():
    assert VALIDATOR.tool_names == ("web_fetch",)


def test_a_validator_needs_no_shell():
    """The plugin's validator held Bash because WebFetch cannot decode a PDF.
    The server-side fetcher returns a PDF as readable content, so the grant that
    reopened the blindness hole is simply not needed."""
    assert not any("bash" in name.lower() for name in VALIDATOR.tool_names)


# --- the grant, as it goes on the wire ------------------------------------

def test_a_built_grant_names_only_the_roles_tools():
    assert [t["name"] for t in RESEARCHER.tools()] == ["web_search", "web_fetch"]
    assert [t["name"] for t in VALIDATOR.tools()] == ["web_fetch"]


def test_every_built_tool_carries_a_budget():
    """A server tool runs unattended inside one request, so `max_uses` is the
    only brake — an unbudgeted grant is an unbounded one."""
    for name, role in ROLES.items():
        for tool in role.tools():
            assert tool["max_uses"] > 0, f"{name}.{tool['name']}"


def test_the_variant_follows_the_models_support():
    """The validator ships two different grants: the haiku pass takes the basic
    fetch tool, the sonnet escalation takes the dynamic-filtering one."""
    from research_agent_batch_server_tools.servertools import (
        WEB_FETCH_BASIC,
        WEB_FETCH_FILTERING,
    )
    assert VALIDATOR.tools()[0]["type"] == WEB_FETCH_BASIC
    assert VALIDATOR.tools("claude-sonnet-5")[0]["type"] == WEB_FETCH_FILTERING


def test_a_validators_fetch_is_pinned_to_one_host():
    """Enforced before Anthropic's fetcher opens a socket, rather than asked for
    in the prompt. The model cannot decline a field it never sees."""
    tool = VALIDATOR.tools(allowed_domains=["learn.microsoft.com"])[0]
    assert tool["allowed_domains"] == ["learn.microsoft.com"]


def test_an_unpinned_role_is_not_accidentally_restricted():
    """An empty `allowed_domains` would block everything, which is a very
    quiet way to make every researcher return nothing."""
    for tool in RESEARCHER.tools():
        assert "allowed_domains" not in tool


def test_a_pin_reaches_every_tool_in_a_grant():
    """A role with two tools must not have one of them left unpinned."""
    tools = RESEARCHER.tools(allowed_domains=["example.com"])
    assert all(t["allowed_domains"] == ["example.com"] for t in tools)


def test_the_pack_writers_have_no_tools_at_all():
    """They see only the ledger text the orchestrator inlines, so they cannot
    introduce a fact that is not in front of them."""
    assert SYNTHESIZER.tools() == [] and PROPOSAL_WRITER.tools() == []


def test_the_planner_cannot_search():
    assert PLANNER.tools() == []


def test_the_gap_hunter_can_search_but_not_fetch():
    """It establishes that material on a topic exists and stops. Reading the
    page would be doing the researcher's job."""
    assert set(GAP_HUNTER.tool_names) == {"web_search"}


# --- models and ceilings --------------------------------------------------

def test_every_role_pins_a_full_model_id():
    for name, role in ROLES.items():
        assert role.model.startswith("claude-"), name
        assert role.model not in {"sonnet", "opus", "haiku", "fable"}, name


def test_the_escalation_runs_a_different_model_from_the_first_pass():
    """Two CONFIRMED rulings mean nothing unless two models produced them, and
    the gate checks exactly that."""
    from research_agent_batch_server_tools.settings import model_for
    assert model_for("validator") != model_for("validator-escalation")


def test_every_role_bounds_its_continuations():
    """A `pause_turn` round is a whole batch, so an unbounded one is unbounded
    wall-clock as well as unbounded spend."""
    for name, role in ROLES.items():
        assert 0 < role.max_continuations <= 4, name


def test_a_toolless_role_needs_no_continuation():
    """With no server tools there is nothing long-running to pause."""
    for role in (PLANNER, SYNTHESIZER, PROPOSAL_WRITER):
        assert role.max_continuations == 1, role.name


# --- schemas --------------------------------------------------------------

def test_a_claim_schema_matches_what_the_ledger_requires():
    from research_agent_batch_server_tools.ledger.claims import REQUIRED
    fields = set(schemas.CLAIM["required"]) | {"sub_q"}
    assert fields == set(REQUIRED)


def test_the_claim_schema_refuses_the_internal_source_type():
    """`internal` is a ledger source type but never an admissible claim."""
    from research_agent_batch_server_tools.ledger.workspace import SOURCE_TYPES
    assert set(schemas.CLAIM["properties"]["source_type"]["enum"]) == \
        SOURCE_TYPES - {"internal"}


def test_the_verdict_schema_offers_exactly_the_ledger_verdicts():
    from research_agent_batch_server_tools.ledger.workspace import VERDICTS
    offered = set(schemas.VERDICT["format"]["schema"]["properties"]["verdict"]["enum"])
    # INTERNAL_UNVERIFIED is a ledger state for internal notes, never something
    # a validator may return.
    assert offered == VERDICTS - {"INTERNAL_UNVERIFIED"}


def test_every_schema_refuses_unknown_fields():
    for name in ("PLAN", "CLAIMS", "VERDICT", "GAPS", "PACK"):
        schema = getattr(schemas, name)["format"]["schema"]
        assert schema["additionalProperties"] is False, name


def test_the_plan_schema_caps_the_sub_questions():
    """6-12 in the prompt; the schema is what actually holds the line."""
    assert schemas.PLAN["format"]["schema"]["properties"]["sub_questions"]["maxItems"] == 12


# --- prompt contracts the gate depends on ---------------------------------

def test_both_pack_writers_document_the_no_citation_marker():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "<!-- no-citation:" in role.prompt(), role.name


def test_both_pack_writers_state_the_marker_is_per_block():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "one marker per block" in role.prompt().lower(), role.name


def test_both_pack_writers_are_told_bullets_and_tables_are_checked():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "bullets and table rows" in role.prompt().lower(), role.name


def test_proposal_writer_names_every_section_that_needs_a_marker():
    rules = PROPOSAL_WRITER.prompt().split("## Citation rules", 1)[1]
    for section in ("The problem we are solving", "What we need from you",
                    "Effort and phasing", "Open questions"):
        assert section in rules, section


def test_synthesizer_is_given_the_exact_headings_the_vault_builder_parses():
    from research_agent_batch_server_tools.vault.build import REQUIRED_SECTIONS
    prompt = SYNTHESIZER.prompt()
    for heading in REQUIRED_SECTIONS:
        assert f"## {heading}" in prompt, heading


def test_the_researcher_is_told_a_snippet_is_not_evidence():
    """It sees search snippets in a result block, which is a way to fabricate a
    quote that the SDK port's researcher never had."""
    prompt = RESEARCHER.prompt()
    assert "snippet is never evidence" in prompt
    assert "web.archive.org" in prompt


def test_the_researcher_is_told_its_budget_is_finite():
    """It cannot defer work to a next turn — there is no next turn — and running
    out of fetches mid-research is a thing it has to plan around rather than
    discover."""
    prompt = " ".join(RESEARCHER.prompt().split()).lower()
    assert "tool budget" in prompt
    assert "could_not_source" in prompt


def test_the_researcher_is_told_a_redirect_is_fine():
    """Both URLs are logged, so a claim citing either passes the gate. Without
    saying so, a careful researcher drops a good claim on a redirect."""
    assert "redirect" in RESEARCHER.prompt().lower()


def test_the_validator_is_told_its_fetch_is_pinned():
    """It will get a refusal if it tries elsewhere; saying so up front saves a
    wasted fetch out of a budget of three."""
    prompt = " ".join(VALIDATOR.prompt().split())
    assert "restricted to that page's host" in prompt
    assert "comes back refused" in prompt


def test_the_validator_is_told_it_has_no_search():
    """The grant already makes this true. Saying it stops the model spending a
    turn discovering it."""
    assert "no `web_search`" in VALIDATOR.prompt()


def test_the_gap_hunter_is_told_a_snippet_is_all_it_will_ever_see():
    """It has no fetch, so judging a gap from a snippet is not a shortcut — it
    is the job."""
    assert "no `web_fetch`" in GAP_HUNTER.prompt()
