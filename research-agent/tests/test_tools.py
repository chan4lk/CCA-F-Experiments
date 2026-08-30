"""The in-process MCP server the researcher records claims through."""
import pytest

from research_agent.agents import ADD_CLAIM_TOOL, LEDGER_SERVER
from research_agent.tools import ADD_CLAIM_SCHEMA, ledger_server

VALID = {
    "id": "C001", "sub_q": "Q1", "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": "https://learn.microsoft.com/a",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc",
}


def handler(server):
    """The one tool's implementation, off the server instance."""
    return server["instance"]


def test_the_server_name_matches_the_tool_name_the_agent_is_granted():
    """A mismatch here means the researcher holds a tool that does not exist."""
    assert ledger_server("/tmp")["name"] == LEDGER_SERVER
    assert ADD_CLAIM_TOOL == f"mcp__{LEDGER_SERVER}__add_claim"


def test_the_server_runs_in_process():
    assert ledger_server("/tmp")["type"] == "sdk"


def test_the_schema_requires_everything_the_ledger_validates():
    from research_agent.ledger.claims import REQUIRED
    assert set(ADD_CLAIM_SCHEMA["required"]) == set(REQUIRED)


def test_raw_hash_is_the_one_optional_field():
    """It is optional on purpose: a placeholder is worse than an absent hash."""
    optional = set(ADD_CLAIM_SCHEMA["properties"]) - set(ADD_CLAIM_SCHEMA["required"])
    assert optional == {"raw_hash"}


def test_the_schema_refuses_unknown_fields():
    assert ADD_CLAIM_SCHEMA["additionalProperties"] is False


def test_the_tiers_and_source_types_match_the_ledger():
    from research_agent.ledger.workspace import SOURCE_TYPES, TIERS
    assert set(ADD_CLAIM_SCHEMA["properties"]["tier"]["enum"]) == TIERS
    # `internal` is a ledger source type but never an admissible claim, so it is
    # deliberately absent from what a researcher may choose.
    assert set(ADD_CLAIM_SCHEMA["properties"]["source_type"]["enum"]) == \
        SOURCE_TYPES - {"internal"}


# --- behaviour -----------------------------------------------------------

@pytest.mark.asyncio
async def test_a_valid_claim_lands_in_this_runs_ledger(tmp_path):
    from research_agent.ledger.claims import append_claim
    from research_agent.ledger.workspace import read_jsonl
    ok, message, _ = append_claim(tmp_path, dict(VALID))
    assert ok and "C001" in message
    assert [r["id"] for r in read_jsonl(tmp_path / "claims.jsonl")] == ["C001"]


@pytest.mark.asyncio
async def test_a_duplicate_id_is_rejected_with_a_reason(tmp_path):
    from research_agent.ledger.claims import append_claim
    append_claim(tmp_path, dict(VALID))
    ok, message, _ = append_claim(tmp_path, dict(VALID))
    assert not ok and "duplicate id" in message


@pytest.mark.asyncio
async def test_a_claim_with_no_recorded_retrieval_warns(tmp_path):
    """Surfaced now, while the researcher still has the page — not an hour
    later at the gate, where it costs the claim."""
    from research_agent.ledger.claims import append_claim
    ok, _, warning = append_claim(tmp_path, dict(VALID))
    assert ok and "PROVENANCE" in warning


def test_the_workspace_is_bound_to_the_server_not_passed_by_the_agent(tmp_path):
    """A researcher cannot append into another run's ledger, even by accident:
    the path is closed over, and there is no workspace parameter to get wrong."""
    assert "workspace" not in ADD_CLAIM_SCHEMA["properties"]
