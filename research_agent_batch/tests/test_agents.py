"""The tool grants and the prompt contracts.

Here the grant is a `tools` array on a Messages request, and it is enforced
twice: the model is offered nothing else, and the dispatcher has nothing else to
run even if it asks.
"""
import pytest

from research_agent_batch import schemas
from research_agent_batch.agents import (
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
    Fetching in-process makes a PDF just bytes to parse, so the grant that
    reopened the blindness hole is simply not needed."""
    assert not any("bash" in name.lower() for name in VALIDATOR.tool_names)


def test_the_pack_writers_have_no_tools_at_all():
    """They see only the ledger text the orchestrator inlines, so they cannot
    introduce a fact that is not in front of them."""
    assert SYNTHESIZER.tools == () and PROPOSAL_WRITER.tools == ()


def test_the_planner_cannot_search():
    assert PLANNER.tools == ()


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
    from research_agent_batch.settings import model_for
    assert model_for("validator") != model_for("validator-escalation")


def test_every_role_bounds_its_rounds():
    """Each round is one batch, so an unbounded agent is unbounded wall-clock
    as well as unbounded spend."""
    for name, role in ROLES.items():
        assert 0 < role.max_rounds <= 12, name


def test_a_toolless_role_needs_barely_any_rounds():
    """With no tools there is nothing to loop on: one turn and an answer."""
    for role in (PLANNER, SYNTHESIZER, PROPOSAL_WRITER):
        assert role.max_rounds <= 2, role.name


def test_the_researcher_gets_the_most_rounds():
    """It is the only role that searches, reads several pages, and then writes."""
    assert RESEARCHER.max_rounds == max(r.max_rounds for r in ROLES.values())


# --- schemas --------------------------------------------------------------

def test_a_claim_schema_matches_what_the_ledger_requires():
    from research_agent_batch.ledger.claims import REQUIRED
    fields = set(schemas.CLAIM["required"]) | {"sub_q"}
    assert fields == set(REQUIRED)


def test_the_claim_schema_refuses_the_internal_source_type():
    """`internal` is a ledger source type but never an admissible claim."""
    from research_agent_batch.ledger.workspace import SOURCE_TYPES
    assert set(schemas.CLAIM["properties"]["source_type"]["enum"]) == \
        SOURCE_TYPES - {"internal"}


def test_the_verdict_schema_offers_exactly_the_ledger_verdicts():
    from research_agent_batch.ledger.workspace import VERDICTS
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
    from research_agent_batch.vault.build import REQUIRED_SECTIONS
    prompt = SYNTHESIZER.prompt()
    for heading in REQUIRED_SECTIONS:
        assert f"## {heading}" in prompt, heading


def test_the_researcher_is_told_a_snippet_is_not_evidence():
    """It now sees search snippets directly in a tool result, which is a new way
    to fabricate a quote that the SDK port's researcher never had."""
    prompt = RESEARCHER.prompt()
    assert "snippet is never evidence" in prompt
    assert "web.archive.org" in prompt


def test_the_validator_is_told_its_fetch_is_pinned():
    """It will get a refusal if it tries elsewhere; saying so up front saves a
    round, and a round here is a whole batch."""
    prompt = " ".join(VALIDATOR.prompt().split())
    assert "only retrieve that page's host" in prompt
    assert "comes back refused" in prompt
