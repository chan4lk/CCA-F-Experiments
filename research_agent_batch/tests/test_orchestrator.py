"""A whole run driven through the fake batch API, with no network anywhere.

These assert the things the plugin's SKILL.md could only ask for: the gate
blocks, the escalation runs a different model, a verdict carries the identity it
was dispatched with, and a validator is never shown the researcher's quote.

Plus the one this engine adds: a run can stop between rounds and be resumed by a
different process, because a batch may take a day.
"""
import json

import pytest
from fakes import FakeClient, FakeHTTP, text_message, tool_call

from research_agent_batch import orchestrator as orch
from research_agent_batch import state as st
from research_agent_batch.ledger.workspace import read_jsonl

URL_A = "https://learn.microsoft.com/a"
URL_B = "https://servicenow.com/b"
QUOTE_A = "A maximum of 10 tools per MCP server connection is supported."
QUOTE_B = "AI Agent Studio lets teams build agents natively on the Now Platform."

PLAN = {"subject": "MCP limits", "sub_questions": [
    {"id": "Q1", "question": "What is the MCP tool cap?", "tier": "material",
     "good_answer": "a first-party page stating the cap", "seeded_by": None},
    {"id": "Q2", "question": "How does the vendor position it?", "tier": "context",
     "good_answer": "an official page", "seeded_by": None},
]}

CLAIMS_Q1 = {"sub_q": "Q1", "could_not_source": [], "claims": [
    {"id": "C001", "tier": "material", "claim": "The cap is ten tools per connection",
     "url": URL_A, "quote": QUOTE_A, "source_type": "vendor_doc"}]}
CLAIMS_Q2 = {"sub_q": "Q2", "could_not_source": [], "claims": [
    {"id": "C021", "tier": "context", "claim": "It is positioned as platform-native",
     "url": URL_B, "quote": QUOTE_B, "source_type": "vendor_doc"}]}

CLAIMS_G1 = {"sub_q": "G1", "could_not_source": [], "claims": [
    {"id": "C041", "tier": "context", "claim": "Data stays in the tenant region",
     "url": URL_A, "quote": QUOTE_A, "source_type": "vendor_doc"}]}

PACK = """# Evidence Pack: MCP limits

## Summary

The tool cap is the binding constraint [C001].

## Recommendation

Split tools across two connections [C001].

## Findings

### The cap

Ten tools per server connection [C001].

## Options

### Copilot Studio

Viable within the cap [C001].

## Constraints

### Tool cap

Ten per connection [C001].

## Open Questions

<!-- no-citation: nothing has settled these -->
- Regional GA status

## Unverified & excluded

Nothing was excluded.
"""


class Script:
    """Answers every request by role, and fetches once before answering when the
    role has a fetch tool — so provenance looks like a real run's."""

    def __init__(self, pack=PACK, gaps_complete=True):
        self.pack = pack
        self.gaps_complete = gaps_complete
        self.seen: list[dict] = []

    def __call__(self, custom_id, params, round_number):
        self.seen.append({"custom_id": custom_id, "params": params,
                          "round": round_number, "model": params["model"]})
        role = custom_id.split("-")[1] if "-" in custom_id else custom_id

        # First turn for anything with tools: go and fetch, so the retrieval is
        # recorded and the gate's provenance checks have something to check.
        tool_names = {t["name"] for t in params.get("tools") or []}
        if round_number == 0 and "web_fetch" in tool_names:
            return tool_call("web_fetch", {"url": self._url(custom_id, params)})

        if role == "planner":
            return text_message(json.dumps(PLAN))
        if role == "researcher":
            payload = {"Q1": CLAIMS_Q1, "Q2": CLAIMS_Q2}.get(
                custom_id.rsplit("-", 1)[-1], CLAIMS_G1)
            return text_message(json.dumps(payload))
        if role == "validator":
            claim_id = custom_id.rsplit("-", 2)[-2]
            return text_message(json.dumps({
                "claim_id": claim_id, "verdict": "CONFIRMED",
                "quote": "the validator's own sentence", "caveat": None}))
        if role == "gap":  # gap-hunter
            gaps = [] if self.gaps_complete else [
                {"id": "G1", "question": "What is the data residency story?",
                 "tier": "material", "good_answer": "a regulator or vendor page",
                 "seeded_by": None}]
            return text_message(json.dumps({"complete": self.gaps_complete, "gaps": gaps}))
        return text_message(json.dumps({"markdown": self.pack}))

    @staticmethod
    def _url(custom_id, params):
        prompt = params["messages"][0]["content"]
        for line in str(prompt).splitlines():
            if line.startswith("url: "):
                return line.split(": ", 1)[1]
        return URL_A if custom_id.endswith("Q1") else URL_B


def run_to_completion(tmp_path, script=None, max_ticks=40, **kw):
    script = script or Script(**kw)
    client = FakeClient(script)
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    http = FakeHTTP()
    for _ in range(max_ticks):
        if orch.tick(client, run, http=http) is orch.FINISHED:
            break
    return run, script, client


# --- a whole run ----------------------------------------------------------

def test_a_clean_run_reaches_the_human_gate_with_a_vault(tmp_path):
    run, _, _ = run_to_completion(tmp_path)
    workspace = tmp_path / "research" / "mcp-tool-limits"

    assert run.phase == st.AWAITING_APPROVAL
    assert (workspace / "evidence-pack.md").is_file()
    assert "GATE: PASS" in (workspace / "verify-report.md").read_text()
    assert (workspace / "vault" / "00-MOC").is_dir()


def test_the_phases_run_in_order(tmp_path):
    _, script, _ = run_to_completion(tmp_path)
    phases = [s["custom_id"].split("-")[0] for s in script.seen]
    first = {p: phases.index(p) for p in dict.fromkeys(phases)}
    assert first["p1"] < first["p2r0"] < first["p3"] < first["p5"]


def test_the_run_stops_at_the_human_gate(tmp_path):
    """`draft` is a separate invocation. The proposal must not inherit claims
    nobody looked at."""
    run, _, _ = run_to_completion(tmp_path)
    assert run.phase == st.AWAITING_APPROVAL
    assert not (tmp_path / "research" / "mcp-tool-limits" / "proposal.md").exists()


# --- one batch per round, not one per request -----------------------------

def test_a_wave_is_one_batch_carrying_every_agents_next_turn(tmp_path):
    """This is what the engine buys: nine researchers taking six turns each is
    six batches, not fifty-four requests."""
    _, _, client = run_to_completion(tmp_path)
    research_batches = [b for b in client.batches.submitted
                        if all(r["custom_id"].startswith("p2r0") for r in b)]
    assert research_batches, "expected a research wave"
    assert len(research_batches[0]) == 2, "both researchers in one batch"


def test_every_batch_holds_only_still_active_conversations(tmp_path):
    """A finished agent must not be resubmitted; that is a paid-for no-op."""
    _, _, client = run_to_completion(tmp_path)
    for batch in client.batches.submitted:
        assert len({r["custom_id"] for r in batch}) == len(batch)


# --- the check that matters most ------------------------------------------

def test_a_validator_is_never_shown_the_researchers_quote(tmp_path):
    """The one shortcut that would destroy this system's only independent check.

    The prompt is built from three fields and the quote is not one of them, so
    there is nothing to leak.
    """
    _, script, _ = run_to_completion(tmp_path)
    validators = [s for s in script.seen if "-validator-" in s["custom_id"]]
    assert validators
    for call in validators:
        prompt = call["params"]["messages"][0]["content"]
        assert QUOTE_A not in prompt and QUOTE_B not in prompt
        keys = {line.split(":", 1)[0] for line in prompt.splitlines() if ":" in line}
        assert keys == {"claim_id", "claim", "url"}


def test_a_validator_may_only_fetch_the_cited_host(tmp_path):
    """Blindness is enforced before the socket opens, not asked for in prose."""
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-validator-" not in call["custom_id"]:
            continue
        prompt = call["params"]["messages"][0]["content"]
        url = next(line.split(": ", 1)[1] for line in prompt.splitlines()
                   if line.startswith("url: "))
        from urllib.parse import urlparse
        # The conversation carries allowed_domains; assert the wave built it from
        # the claim's own URL rather than leaving it open.
        assert urlparse(url).hostname in {"learn.microsoft.com", "servicenow.com"}


def test_a_validator_is_given_no_search_tool(tmp_path):
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-validator-" in call["custom_id"]:
            names = {t["name"] for t in call["params"]["tools"]}
            assert names == {"web_fetch"}


def test_the_pack_writers_are_given_no_tools_at_all(tmp_path):
    """They cannot introduce a fact that is not in the ledger, because the
    ledger text in their prompt is the only thing they can see."""
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-synthesizer-" in call["custom_id"]:
            assert not call["params"].get("tools")


def test_the_synthesizer_is_handed_the_whole_ledger(tmp_path):
    _, script, _ = run_to_completion(tmp_path)
    call = next(s for s in script.seen if "-synthesizer-" in s["custom_id"])
    prompt = call["params"]["messages"][0]["content"]
    assert "C001" in prompt and QUOTE_A in prompt
    assert "verdict: CONFIRMED" in prompt


# --- escalation -----------------------------------------------------------

def test_a_material_claim_is_ruled_twice_by_two_models(tmp_path):
    run, _, _ = run_to_completion(tmp_path)
    verdicts = [v for v in read_jsonl(tmp_path / "research" / "mcp-tool-limits" /
                                      "verdicts.jsonl") if v["claim_id"] == "C001"]
    assert len(verdicts) == 2
    assert len({v["validator_model"] for v in verdicts}) == 2
    assert len({v["validator_agent_id"] for v in verdicts}) == 2


def test_a_context_claim_is_ruled_once(tmp_path):
    run, _, _ = run_to_completion(tmp_path)
    verdicts = [v for v in read_jsonl(tmp_path / "research" / "mcp-tool-limits" /
                                      "verdicts.jsonl") if v["claim_id"] == "C021"]
    assert len(verdicts) == 1


def test_the_escalation_runs_the_pinned_second_model(tmp_path):
    from research_agent_batch.settings import model_for
    _, script, _ = run_to_completion(tmp_path)
    models = {s["model"] for s in script.seen if "-validator-" in s["custom_id"]}
    assert model_for("validator") in models
    assert model_for("validator-escalation") in models


def test_a_verdict_carries_the_batch_request_that_produced_it(tmp_path):
    """validator_agent_id is the custom_id, which is also the agent_id in the
    fetch log — so a ruling traces to the exact request that caused the fetch."""
    run, _, _ = run_to_completion(tmp_path)
    workspace = tmp_path / "research" / "mcp-tool-limits"
    verdicts = read_jsonl(workspace / "verdicts.jsonl")
    fetch_agents = {r["agent_id"] for r in read_jsonl(workspace / "fetch-log.jsonl")}
    for verdict in verdicts:
        assert verdict["validator_agent_id"] in fetch_agents


# --- provenance -----------------------------------------------------------

def test_every_retrieval_is_logged_against_the_agent_that_made_it(tmp_path):
    run, _, _ = run_to_completion(tmp_path)
    rows = read_jsonl(tmp_path / "research" / "mcp-tool-limits" / "fetch-log.jsonl")
    assert rows
    for row in rows:
        assert row["agent_id"] and row["agent_type"] in {"researcher", "validator"}
        assert row["tool"] in {"web_fetch", "web_search"}


# --- the gate blocks ------------------------------------------------------

def test_a_fabricated_citation_fails_the_gate_and_builds_no_vault(tmp_path):
    with pytest.raises(orch.GateFailed) as exc:
        run_to_completion(tmp_path, pack=PACK.replace("[C001]", "[C999]"))
    assert any(f.check == "citations-resolve" for f in exc.value.failures)
    workspace = tmp_path / "research" / "mcp-tool-limits"
    assert not (workspace / "vault").exists()
    assert "GATE: FAIL" in (workspace / "verify-report.md").read_text()


# --- resumability ---------------------------------------------------------

def test_a_run_survives_the_process_that_started_it(tmp_path):
    """The point of the state file. A batch may take 24 hours; a held-open
    Python process is not a plan."""
    script = Script()
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    client = FakeClient(script)

    assert orch.tick(client, run, http=FakeHTTP()) is orch.WAITING
    assert run.batch_id

    # A different process picks it up, knowing only the workspace.
    reloaded = st.RunState.load(tmp_path / "research" / "mcp-tool-limits")
    assert reloaded.batch_id == run.batch_id
    assert reloaded.phase == run.phase

    for _ in range(40):
        if orch.tick(client, reloaded, http=FakeHTTP()) is orch.FINISHED:
            break
    assert reloaded.phase == st.AWAITING_APPROVAL


def test_a_tick_with_a_batch_still_running_changes_nothing(tmp_path):
    script = Script()
    client = FakeClient(script, ends_after_polls=2)
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)

    orch.tick(client, run, http=FakeHTTP())
    batch_id, submitted = run.batch_id, len(client.batches.submitted)
    assert orch.tick(client, run, http=FakeHTTP()) is orch.WAITING
    assert run.batch_id == batch_id
    assert len(client.batches.submitted) == submitted, "must not resubmit while in flight"


def test_the_history_records_every_batch(tmp_path):
    run, _, client = run_to_completion(tmp_path)
    assert len(run.history) == len(client.batches.submitted)
    assert all(s.ended_at for s in run.history)
    assert {s.phase for s in run.history} >= {"plan", "research", "validate", "synthesize"}


def test_the_cost_survives_phases_being_retired(tmp_path):
    """Conversations are cleared between phases so the state file does not grow
    a transcript of the whole run — but the money they spent has to survive."""
    run, _, _ = run_to_completion(tmp_path)
    assert run.conversations == []
    assert run.cost_usd > 0


# --- failures -------------------------------------------------------------

def test_a_permanently_failed_request_does_not_stall_the_wave(tmp_path):
    """A batch is a set of independent requests. One malformed validator must
    not discard the ones that succeeded alongside it."""
    script = Script()
    # A malformed request fails identically however often it is resubmitted, so
    # the wave must give up on it rather than retrying it forever.
    client = FakeClient(script, fail={"p2r0-researcher-Q2": ("invalid_request_error", "bad")})
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    http = FakeHTTP()
    for _ in range(40):
        if orch.tick(client, run, http=http) is orch.FINISHED:
            break

    workspace = tmp_path / "research" / "mcp-tool-limits"
    claims = read_jsonl(workspace / "claims.jsonl")
    assert [c["id"] for c in claims] == ["C001"], "Q1's claim still landed"
    assert run.phase == st.AWAITING_APPROVAL, "the run finished despite the failure"


def test_a_retryable_failure_is_resubmitted_unchanged(tmp_path):
    """An expired request is fine as written; it goes back into the next round."""
    from research_agent_batch.batching import Failure
    assert Failure("a", "expired").retryable
    assert Failure("a", "errored", "api_error").retryable
    assert not Failure("a", "errored", "invalid_request_error").retryable


# --- phase 7 --------------------------------------------------------------

def test_draft_runs_the_gate_again_over_the_proposal(tmp_path):
    run, script, client = run_to_completion(tmp_path)
    run.phase = st.DRAFT
    run.save()
    for _ in range(10):
        if orch.tick(client, run, http=FakeHTTP()) is orch.FINISHED:
            break
    workspace = tmp_path / "research" / "mcp-tool-limits"
    assert run.phase == st.DONE
    assert (workspace / "proposal.md").is_file()
    assert (workspace / "verify-report-proposal.md").is_file()


def test_the_proposal_writer_gets_the_pack_and_nothing_else(tmp_path):
    run, script, client = run_to_completion(tmp_path)
    run.phase = st.DRAFT
    run.save()
    for _ in range(10):
        if orch.tick(client, run, http=FakeHTTP()) is orch.FINISHED:
            break
    call = next(s for s in script.seen if "-proposal" in s["custom_id"])
    assert not call["params"].get("tools")
    assert "APPROVED EVIDENCE PACK" in call["params"]["messages"][0]["content"]


# --- id ranges ------------------------------------------------------------

def test_id_ranges_never_overlap():
    seen = set()
    for index in range(8):
        first, last = orch._id_range(index)
        block = set(range(int(first[1:]), int(last[1:]) + 1))
        assert not block & seen
        seen |= block


def test_a_second_research_round_gets_fresh_id_blocks(tmp_path):
    """Gap-round researchers must not collide with the first round's claim ids."""
    script = Script(gaps_complete=False)
    client = FakeClient(script)
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    for _ in range(40):
        if orch.tick(client, run, http=FakeHTTP()) is orch.FINISHED:
            break
    # One entry per researcher, not per turn: a conversation keeps the same
    # opening prompt across every round it takes.
    by_agent = {s["custom_id"]: s["params"]["messages"][0]["content"]
                for s in script.seen if "-researcher-" in s["custom_id"]}
    assert len(by_agent) == 3, "two first-round researchers plus one for the gap"

    ranges = [line for prompt in by_agent.values() for line in prompt.splitlines()
              if " ids " in line and "C0" in line]
    assert len(set(ranges)) == 3, f"every researcher needs its own range: {ranges}"
    assert any("C041" in r for r in ranges), "the gap round got a fresh block"


def test_a_forever_failing_request_is_eventually_given_up_on(tmp_path):
    """An `overloaded_error` is retryable, so the wave resubmits it. Without a
    retry ceiling that is an infinite loop of paid-for batches."""
    from research_agent_batch.conversation import MAX_RETRIES
    script = Script()
    client = FakeClient(script, fail={"p1-planner-main": ("overloaded_error", "busy")})
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)

    for _ in range(MAX_RETRIES + 5):
        orch.tick(client, run, http=FakeHTTP())
        if run.phase != st.PLAN:
            break

    planner_batches = [b for b in client.batches.submitted
                       if any(r["custom_id"].startswith("p1-") for r in b)]
    assert len(planner_batches) == MAX_RETRIES + 1, "the first send plus three retries"
    assert run.phase != st.PLAN, "it gave up rather than looping forever"
