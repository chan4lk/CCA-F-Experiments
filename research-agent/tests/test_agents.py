"""The tool grants are the design. These tests are what keeps them honest.

The plugin asserted this against YAML frontmatter it parsed by hand. Here the
grants are Python, so the assertions read the same objects the SDK is handed —
there is no second representation that could drift from the first.
"""
import pytest
from claude_agent_sdk import AgentDefinition

from research_agent.agents import (
    ADD_CLAIM_TOOL,
    GAP_HUNTER,
    PLANNER,
    PROPOSAL_WRITER,
    RESEARCHER,
    ROLES,
    SYNTHESIZER,
    VALIDATOR,
    agent_definitions,
)

EXPECTED_TOOLS = {
    "planner": {"Read", "Write"},
    "researcher": {"WebSearch", "WebFetch", ADD_CLAIM_TOOL,
                   "mcp__microsoft_docs_mcp__microsoft_docs_search",
                   "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
                   "mcp__headroom__headroom_compress"},
    "validator": {"WebFetch", "Bash", "mcp__microsoft_docs_mcp__microsoft_docs_fetch"},
    "gap-hunter": {"Read", "WebSearch", "Write"},
    "synthesizer": {"Read", "Write"},
    "proposal-writer": {"Read", "Write"},
}


def test_every_role_is_registered():
    assert set(ROLES) == set(EXPECTED_TOOLS)


def test_every_role_has_a_description_and_a_prompt():
    for name, role in ROLES.items():
        assert role.description, name
        assert len(role.prompt()) > 400, name


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_tool_sets_match_the_design(name):
    assert set(ROLES[name].tools) == EXPECTED_TOOLS[name]


# --- blindness, now a property of the grant ------------------------------

def test_validator_cannot_read_the_filesystem():
    """No Read, no Grep, no Glob. Bash is granted, and hooks.validator_guard
    is what stops Bash from becoming a read — see test_hooks."""
    tools = set(VALIDATOR.tools)
    assert not tools & {"Read", "Grep", "Glob", "NotebookEdit"}


def test_validator_cannot_search():
    assert "WebSearch" not in VALIDATOR.tools


def test_validator_cannot_write_anywhere():
    assert not {"Write", "Edit"} & set(VALIDATOR.tools)


def test_synthesizer_has_no_web_tools():
    assert not [t for t in SYNTHESIZER.tools
                if t.startswith("Web") or "docs_fetch" in t or "docs_search" in t]


def test_proposal_writer_has_no_web_tools():
    assert not [t for t in PROPOSAL_WRITER.tools if t.startswith("Web")]


def test_planner_cannot_search():
    assert "WebSearch" not in PLANNER.tools


def test_gap_hunter_can_search_but_only_to_confirm_a_gap():
    assert "WebSearch" in GAP_HUNTER.tools
    assert "only" in GAP_HUNTER.prompt().lower()


# --- what the port changed ----------------------------------------------

def test_researcher_holds_no_shell():
    """The plugin's researcher held Bash solely to shell out to add_claim.py.

    The in-process tool replaced that, and dropping Bash closed the provenance
    hole with it: a page read with `curl` is invisible to the retrieval
    recorder, and one run lost 17 claims that way.
    """
    assert "Bash" not in RESEARCHER.tools


def test_the_researchers_only_write_path_is_the_ledger_tool():
    assert ADD_CLAIM_TOOL in RESEARCHER.tools
    assert not {"Write", "Edit", "NotebookEdit"} & set(RESEARCHER.tools)


def test_every_role_that_must_produce_a_file_can_write_one():
    for role in ROLES.values():
        if role.writes:
            assert "Write" in role.tools, role.name


# --- models --------------------------------------------------------------

def test_every_role_pins_a_full_model_id():
    """Aliases resolve somewhere else; a full id is a decision this repo owns."""
    for name, role in ROLES.items():
        assert role.model.startswith("claude-"), name
        assert role.model not in {"sonnet", "opus", "haiku", "fable", "inherit"}, name


def test_the_escalation_runs_a_different_model_from_the_first_pass():
    """Two CONFIRMED rulings only mean something if two models produced them.

    The gate checks that the models differ; if these two were ever pinned to the
    same id, every material claim would fail verdict-admission.
    """
    from research_agent.settings import model_for
    assert model_for("validator") != model_for("validator-escalation")


def test_cheap_first_pass_expensive_judgement():
    from research_agent.settings import model_for
    assert model_for("validator") == "claude-haiku-4-5"
    assert model_for("gap-hunter") == "claude-opus-5"


# --- turn ceilings -------------------------------------------------------

def test_every_role_bounds_its_own_turns():
    for name, role in ROLES.items():
        assert 0 < role.max_turns <= 60, name


def test_the_validator_is_the_tightest_loop():
    """It fetches one page and rules. Anything more is a validator going looking."""
    assert VALIDATOR.max_turns <= min(r.max_turns for r in ROLES.values() if r is not VALIDATOR)


# --- AgentDefinition assembly -------------------------------------------

def test_definitions_are_sdk_agent_definitions():
    for name, definition in agent_definitions().items():
        assert isinstance(definition, AgentDefinition), name
        assert definition.prompt and definition.description and definition.model


def test_mcp_tools_are_dropped_when_their_server_is_not_configured():
    bare = agent_definitions(servers={})
    assert bare["researcher"].tools == ["WebSearch", "WebFetch", ADD_CLAIM_TOOL]
    assert bare["validator"].tools == ["WebFetch", "Bash"]


def test_mcp_tools_survive_when_their_server_is_configured():
    wired = agent_definitions(servers={"microsoft_docs_mcp": {}, "headroom": {}})
    assert set(wired["researcher"].tools) == EXPECTED_TOOLS["researcher"]


# --- prompt contracts the gate depends on --------------------------------

def test_both_pack_writers_document_the_no_citation_marker():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "<!-- no-citation:" in role.prompt(), role.name


def test_both_pack_writers_state_the_marker_is_per_block():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "one marker per block" in role.prompt().lower(), role.name


def test_proposal_writer_names_every_section_that_needs_a_marker():
    """A proposal written to this prompt's own structure must pass the gate."""
    rules = PROPOSAL_WRITER.prompt().split("## Citation rules", 1)[1]
    for section in ("The problem we are solving", "What we need from you",
                    "Effort and phasing", "Open questions"):
        assert section in rules, section


def test_both_pack_writers_are_told_bullets_and_tables_are_checked():
    for role in (SYNTHESIZER, PROPOSAL_WRITER):
        assert "bullets and table rows" in role.prompt().lower(), role.name


def test_synthesizer_is_given_the_exact_headings_the_vault_builder_parses():
    from research_agent.vault.build import REQUIRED_SECTIONS
    prompt = SYNTHESIZER.prompt()
    for heading in REQUIRED_SECTIONS:
        assert f"## {heading}" in prompt, heading


def test_researcher_is_warned_off_unvalidatable_sources():
    """A real run lost 28 claims to sources no validator could re-fetch."""
    prompt = RESEARCHER.prompt()
    assert "web.archive.org" in prompt
    assert "10485760" in prompt or "10 MB" in prompt


def test_researcher_is_told_raw_hash_is_optional_and_not_a_placeholder():
    assert "n/a" in RESEARCHER.prompt()


def test_the_curl_warning_is_gone_because_the_researcher_has_no_shell():
    """Warning an agent off a tool it does not hold is noise that ages badly."""
    assert "curl" not in RESEARCHER.prompt()


def test_validator_prompt_still_explains_its_one_legitimate_use_of_bash():
    prompt = VALIDATOR.prompt()
    assert "curl" in prompt and "pdftotext" in prompt
    assert "NOT_FOUND" in prompt


def test_planner_is_told_the_heading_shape_the_orchestrator_parses():
    """The orchestrator regex-parses plan.md; a shape change silently costs
    sub-questions their researchers, so the prompt must state the contract."""
    assert "## Q1 —" in PLANNER.prompt()
    assert "## G1 —" in GAP_HUNTER.prompt()
