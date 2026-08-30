"""The guards, as SDK hook callbacks.

The plugin's hooks were scripts that parsed stdin and exited 0 or 2. These are
async callables that return a decision dict, and — the point of the port — they
close over the workspace and the caller's identity instead of recovering them
from the payload.
"""
import json

import pytest

from research_agent import hooks

CTX = {"signal": None}


def decision(result: dict) -> str:
    return (result.get("hookSpecificOutput") or {}).get("permissionDecision", "allow")


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    return ws


# --- the retrieval recorder ---------------------------------------------

@pytest.mark.asyncio
async def test_fetch_is_recorded_against_the_dispatched_identity(workspace):
    """The whole provenance spine. The gate proves a validator opened the page
    it ruled on by joining this row's agent_id against the verdict's."""
    record = hooks.fetch_recorder(workspace, "validator-abc123", "validator")
    await record({"tool_name": "WebFetch", "tool_input": {"url": "https://x/a"}}, None, CTX)

    row = json.loads((workspace / "fetch-log.jsonl").read_text().strip())
    assert row["agent_id"] == "validator-abc123"
    assert row["agent_type"] == "validator"
    assert row["url"] == "https://x/a"
    assert row["tool"] == "WebFetch"
    assert row["ts"]


@pytest.mark.asyncio
async def test_agent_type_is_bare_so_the_gate_can_match_it(workspace):
    """Claude Code namespaced a plugin's agents — the log held
    `proposal-research:validator`, and two checks comparing against `validator`
    were dead for all 531 retrievals of the first real run. Nothing namespaces
    these, and workspace.agent_role still normalises either way."""
    from research_agent.ledger.workspace import agent_role
    record = hooks.fetch_recorder(workspace, "v1", "validator")
    await record({"tool_name": "WebFetch", "tool_input": {"url": "https://x/a"}}, None, CTX)
    row = json.loads((workspace / "fetch-log.jsonl").read_text().strip())
    assert row["agent_type"] == "validator" == agent_role(row["agent_type"])


@pytest.mark.asyncio
async def test_a_websearch_records_its_query(workspace):
    record = hooks.fetch_recorder(workspace, "r1", "researcher")
    await record({"tool_name": "WebSearch", "tool_input": {"query": "mcp tool cap"}}, None, CTX)
    row = json.loads((workspace / "fetch-log.jsonl").read_text().strip())
    assert row["query"] == "mcp tool cap" and row["url"] is None


@pytest.mark.asyncio
async def test_the_recorder_never_raises(tmp_path):
    """It runs on every retrieval. A logging hook that throws takes the run down."""
    unwritable = tmp_path / "nope" / "\0bad"
    record = hooks.fetch_recorder(unwritable, "r1", "researcher")
    assert await record({"tool_name": "WebFetch"}, None, CTX) == {}


@pytest.mark.asyncio
async def test_two_agents_write_disjoint_rows_to_one_log(workspace):
    """Validators run in parallel over the same log; appends must not interleave."""
    for agent in ("v1", "v2"):
        await hooks.fetch_recorder(workspace, agent, "validator")(
            {"tool_name": "WebFetch", "tool_input": {"url": "https://x/a"}}, None, CTX)
    rows = [json.loads(line) for line in
            (workspace / "fetch-log.jsonl").read_text().splitlines()]
    assert [r["agent_id"] for r in rows] == ["v1", "v2"]


# --- the validator guard -------------------------------------------------

@pytest.mark.asyncio
async def test_validator_may_not_search(workspace):
    guard = hooks.validator_guard(workspace)
    result = await guard({"tool_name": "WebSearch", "tool_input": {"query": "q"}}, None, CTX)
    assert decision(result) == "deny"
    assert "may not search" in result["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "NotebookEdit"])
async def test_validator_may_not_read_the_filesystem(workspace, tool):
    guard = hooks.validator_guard(workspace)
    assert decision(await guard({"tool_name": tool, "tool_input": {}}, None, CTX)) == "deny"


@pytest.mark.asyncio
@pytest.mark.parametrize("ledger", [
    "claims.jsonl", "verdicts.jsonl", "fetch-log.jsonl", "plan.md",
    "evidence-pack.md", "gaps.md", "internal-claims.jsonl", "proposal.md",
])
async def test_validator_bash_may_not_touch_run_state(workspace, ledger):
    guard = hooks.validator_guard(workspace)
    result = await guard(
        {"tool_name": "Bash", "tool_input": {"command": f"cat /somewhere/{ledger}"}}, None, CTX)
    assert decision(result) == "deny"
    assert ledger in result["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.asyncio
async def test_validator_bash_may_not_reach_the_workspace_by_absolute_path(workspace):
    """The plugin matched a literal `research/` prefix. An absolute path to this
    run's directory is the same reach and must be denied the same way."""
    guard = hooks.validator_guard(workspace)
    result = await guard(
        {"tool_name": "Bash", "tool_input": {"command": f"ls -la {workspace}"}}, None, CTX)
    assert decision(result) == "deny"


@pytest.mark.asyncio
async def test_validator_bash_may_not_reach_a_relative_research_path(workspace):
    guard = hooks.validator_guard(workspace)
    result = await guard(
        {"tool_name": "Bash", "tool_input": {"command": "cat research/other-run/plan.md"}},
        None, CTX)
    assert decision(result) == "deny"


@pytest.mark.asyncio
async def test_validator_may_curl_the_url_it_was_given(workspace):
    """The one legitimate use of Bash: a PDF WebFetch could not decode."""
    guard = hooks.validator_guard(workspace)
    command = ('curl -sL --max-time 60 "https://example.com/spec.pdf" -o /tmp/v.bin && '
               'pdftotext /tmp/v.bin - | head -c 200000')
    assert decision(await guard(
        {"tool_name": "Bash", "tool_input": {"command": command}}, None, CTX)) == "allow"


@pytest.mark.asyncio
async def test_validator_webfetch_is_never_blocked(workspace):
    guard = hooks.validator_guard(workspace)
    assert decision(await guard(
        {"tool_name": "WebFetch", "tool_input": {"url": "https://x/a"}}, None, CTX)) == "allow"


@pytest.mark.asyncio
async def test_the_denial_tells_the_validator_what_to_do_instead(workspace):
    """A block that does not name the valid alternative just costs a turn."""
    guard = hooks.validator_guard(workspace)
    result = await guard({"tool_name": "WebSearch", "tool_input": {}}, None, CTX)
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert "NOT_FOUND" in reason and "independence" in reason


# --- the ledger guard ----------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("ledger", ["claims.jsonl", "verdicts.jsonl"])
async def test_direct_writes_to_a_ledger_are_denied(ledger):
    guard = hooks.ledger_guard()
    result = await guard(
        {"tool_name": "Write", "tool_input": {"file_path": f"research/run-a/{ledger}"}},
        None, CTX)
    assert decision(result) == "deny"


@pytest.mark.asyncio
async def test_writing_a_normal_workspace_file_is_allowed():
    """plan.md, gaps.md and the pack are all written with Write, by design."""
    guard = hooks.ledger_guard()
    for name in ("plan.md", "gaps.md", "evidence-pack.md", "proposal.md"):
        result = await guard(
            {"tool_name": "Write", "tool_input": {"file_path": f"research/run-a/{name}"}},
            None, CTX)
        assert decision(result) == "allow", name


# --- assembly ------------------------------------------------------------

def test_only_the_validator_gets_the_blindness_guard(workspace):
    assert len(hooks.hooks_for("validator", workspace, "v1")["PreToolUse"]) == 2
    for role in ("planner", "researcher", "synthesizer", "gap-hunter", "proposal-writer"):
        assert len(hooks.hooks_for(role, workspace, "a1")["PreToolUse"]) == 1, role


def test_every_role_records_its_own_retrievals(workspace):
    for role in ("planner", "researcher", "validator", "gap-hunter"):
        assert len(hooks.hooks_for(role, workspace, "a1")["PostToolUse"]) == 1, role


def test_the_fetch_matcher_does_not_cover_bash():
    """A page read with Bash leaves no provenance. That is why the researcher
    holds no Bash — not something the matcher should paper over."""
    assert "Bash" not in hooks.FETCH_MATCHER
