"""A whole run driven through the fake batch API, with no network anywhere.

These assert the things the plugin's SKILL.md could only ask for: the gate
blocks, the escalation runs a different model, a verdict carries the identity it
was dispatched with, and a validator is never shown the researcher's quote.

Plus the two this engine adds. A run can stop between batches and be resumed by
a different process, because a batch may take a day. And a phase is *one* batch:
the fake responds to a researcher with its searches, its fetches and its answer
in a single message, because that is what a server-tool turn actually returns.
"""
import json

import pytest
from fakes import FakeClient, answered, fetched, paused, searched, text_message

from research_agent_batch_server_tools import orchestrator as orch
from research_agent_batch_server_tools import state as st
from research_agent_batch_server_tools.ledger.workspace import read_jsonl

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
    """Answers every request by role.

    A tooled role answers with its retrievals *and* its answer in one message,
    because that is the shape a server-tool turn comes back in: the searching
    and the fetching happened inside the request that is now returning. In
    `research_agent_batch`'s equivalent this took three round trips.
    """

    def __init__(self, pack=PACK, gaps_complete=True, pause_first=()):
        self.pack = pack
        self.gaps_complete = gaps_complete
        # custom_ids whose first turn comes back paused, to exercise the one
        # continuation this engine has.
        self.pause_first = set(pause_first)
        self.seen: list[dict] = []

    def __call__(self, custom_id, params, round_number):
        self.seen.append({"custom_id": custom_id, "params": params,
                          "round": round_number, "model": params["model"]})
        role = custom_id.split("-")[1] if "-" in custom_id else custom_id

        if custom_id in self.pause_first and round_number == 0:
            return paused(fetched(URL_A, call_id=f"{custom_id}-p"))

        if role == "planner":
            return text_message(json.dumps(PLAN))

        if role == "researcher":
            payload = {"Q1": CLAIMS_Q1, "Q2": CLAIMS_Q2}.get(
                custom_id.rsplit("-", 1)[-1], CLAIMS_G1)
            # Every page it is about to cite, actually fetched — which is what
            # the gate's provenance check proves.
            urls = list(dict.fromkeys(c["url"] for c in payload["claims"]))
            blocks = [searched(payload["sub_q"], urls, call_id=f"{custom_id}-s")]
            blocks += [fetched(url, call_id=f"{custom_id}-f{i}")
                       for i, url in enumerate(urls)]
            return answered(json.dumps(payload), *blocks, web_searches=1)

        if role == "validator":
            claim_id = custom_id.rsplit("-", 2)[-2]
            return answered(
                json.dumps({"claim_id": claim_id, "verdict": "CONFIRMED",
                            "quote": "the validator\'s own sentence", "caveat": None}),
                fetched(self._url(params), call_id=f"{custom_id}-f"))

        if role == "gap":  # gap-hunter
            gaps = [] if self.gaps_complete else [
                {"id": "G1", "question": "What is the data residency story?",
                 "tier": "material", "good_answer": "a regulator or vendor page",
                 "seeded_by": None}]
            return answered(json.dumps({"complete": self.gaps_complete, "gaps": gaps}),
                            searched("data residency", [URL_A],
                                     call_id=f"{custom_id}-s"),
                            web_searches=1)

        return text_message(json.dumps({"markdown": self.pack}))

    @staticmethod
    def _url(params):
        """The one URL a validator was given, read back out of its prompt."""
        prompt = params["messages"][0]["content"]
        for line in str(prompt).splitlines():
            if line.startswith("url: "):
                return line.split(": ", 1)[1]
        raise AssertionError("a validator was dispatched with no url")


def run_to_completion(tmp_path, script=None, max_ticks=40, **kw):
    script = script or Script(**kw)
    client = FakeClient(script)
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    for _ in range(max_ticks):
        if orch.tick(client, run) is orch.FINISHED:
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


# --- one batch per phase --------------------------------------------------

def test_a_research_phase_is_one_batch(tmp_path):
    """This is what pushing the tools to the server buys. The sibling spends one
    batch per round and a researcher takes several; here the searching and the
    fetching happen inside the request, so the phase is the batch."""
    _, _, client = run_to_completion(tmp_path)
    research_batches = [b for b in client.batches.submitted
                        if all(r["custom_id"].startswith("p2r0") for r in b)]
    assert len(research_batches) == 1, "the whole research phase in one batch"
    assert len(research_batches[0]) == 2, "both researchers in it"


def test_no_agent_is_asked_for_a_second_turn(tmp_path):
    """Every request comes back answered, so nothing is resubmitted. A run that
    sent a second turn would be paying for a loop it does not need."""
    _, script, _ = run_to_completion(tmp_path)
    assert all(call["round"] == 0 for call in script.seen)


def test_the_whole_run_is_a_handful_of_batches(tmp_path):
    """One per phase that had work: plan, research, validate, escalate,
    synthesize. The equivalent run in the sibling is roughly twice this."""
    _, _, client = run_to_completion(tmp_path)
    assert len(client.batches.submitted) <= 8


def test_every_batch_holds_only_still_active_tasks(tmp_path):
    """A finished agent must not be resubmitted; that is a paid-for no-op."""
    _, _, client = run_to_completion(tmp_path)
    for batch in client.batches.submitted:
        assert len({r["custom_id"] for r in batch}) == len(batch)


def test_a_paused_turn_is_continued_in_a_batch_of_its_own(tmp_path):
    """The one continuation left. Only the paused request goes back — the
    researcher that answered first time must not be re-run alongside it."""
    run, script, client = run_to_completion(
        tmp_path, script=Script(pause_first=["p2r0-researcher-Q1"]))
    assert run.phase == st.AWAITING_APPROVAL
    continuation = [b for b in client.batches.submitted
                    if [r["custom_id"] for r in b] == ["p2r0-researcher-Q1"]]
    assert continuation, "the paused request went back on its own"
    assert any(call["round"] == 1 for call in script.seen)


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
    """Blindness is a field on the tool definition the API enforces, not a rule
    the prompt asks the model to respect."""
    from urllib.parse import urlparse
    _, script, _ = run_to_completion(tmp_path)
    validators = [c for c in script.seen if "-validator-" in c["custom_id"]]
    assert validators
    for call in validators:
        prompt = call["params"]["messages"][0]["content"]
        url = next(line.split(": ", 1)[1] for line in prompt.splitlines()
                   if line.startswith("url: "))
        fetch = next(t for t in call["params"]["tools"] if t["name"] == "web_fetch")
        assert fetch["allowed_domains"] == [urlparse(url).hostname]


def test_a_researchers_fetch_is_not_pinned(tmp_path):
    """Only the validator has one page to read. Pinning a researcher would stop
    it reading anything, and an empty allowed_domains blocks everything."""
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-researcher-" in call["custom_id"]:
            assert all("allowed_domains" not in t for t in call["params"]["tools"])


def test_the_escalation_pass_gets_the_variant_its_model_supports(tmp_path):
    """The same role ships two different grants: haiku takes the basic fetch
    tool, the sonnet escalation takes the dynamic-filtering one. Sending the
    wrong one is a 400 on every validator in the wave at once."""
    from research_agent_batch_server_tools.servertools import (
        supports_dynamic_filtering,
        WEB_FETCH_FILTERING,
    )
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-validator-" not in call["custom_id"]:
            continue
        fetch = next(t for t in call["params"]["tools"] if t["name"] == "web_fetch")
        assert (fetch["type"] == WEB_FETCH_FILTERING) is \
            supports_dynamic_filtering(call["model"])


def test_a_validator_is_given_no_search_tool(tmp_path):
    """Searching is how a validator finds a friendlier source than the one it
    was asked about. There is no search in its grant to be talked into using."""
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        if "-validator-" in call["custom_id"]:
            names = {t["name"] for t in call["params"]["tools"]}
            assert names == {"web_fetch"}


def test_every_granted_tool_is_a_server_tool(tmp_path):
    """A client-side tool in a grant is a request nothing can finish: the turn
    stops at tool_use and no process here would ever continue it."""
    _, script, _ = run_to_completion(tmp_path)
    for call in script.seen:
        for tool in call["params"].get("tools") or []:
            assert tool["type"].startswith(("web_search_", "web_fetch_")), tool
            assert "input_schema" not in tool, "a server tool carries no schema"


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
    from research_agent_batch_server_tools.settings import model_for
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
    """Read out of each response's own result blocks rather than written by this
    process, which is the one thing this port does at arm's length."""
    run, _, _ = run_to_completion(tmp_path)
    rows = read_jsonl(tmp_path / "research" / "mcp-tool-limits" / "fetch-log.jsonl")
    assert rows
    for row in rows:
        assert row["agent_id"]
        assert row["agent_type"] in {"researcher", "validator", "gap-hunter"}
        assert row["tool"] in {"web_fetch", "web_search"}


def test_a_validators_own_fetch_is_what_proves_its_independence(tmp_path):
    """The gate joins the fetch log against the verdicts on agent_id. A ruling
    on a page that agent never opened is either echoing the researcher or
    inventing a verdict."""
    run, _, _ = run_to_completion(tmp_path)
    workspace = tmp_path / "research" / "mcp-tool-limits"
    claims = {c["id"]: c["url"] for c in read_jsonl(workspace / "claims.jsonl")}
    by_agent: dict[str, set] = {}
    for row in read_jsonl(workspace / "fetch-log.jsonl"):
        by_agent.setdefault(row["agent_id"], set()).add(row["url"])
    for verdict in read_jsonl(workspace / "verdicts.jsonl"):
        assert claims[verdict["claim_id"]] in by_agent[verdict["validator_agent_id"]]


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

    assert orch.tick(client, run) is orch.WAITING
    assert run.batch_id

    # A different process picks it up, knowing only the workspace.
    reloaded = st.RunState.load(tmp_path / "research" / "mcp-tool-limits")
    assert reloaded.batch_id == run.batch_id
    assert reloaded.phase == run.phase

    for _ in range(40):
        if orch.tick(client, reloaded) is orch.FINISHED:
            break
    assert reloaded.phase == st.AWAITING_APPROVAL


def test_a_tick_with_a_batch_still_running_changes_nothing(tmp_path):
    script = Script()
    client = FakeClient(script, ends_after_polls=2)
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)

    orch.tick(client, run)
    batch_id, submitted = run.batch_id, len(client.batches.submitted)
    assert orch.tick(client, run) is orch.WAITING
    assert run.batch_id == batch_id
    assert len(client.batches.submitted) == submitted, "must not resubmit while in flight"


def test_the_history_records_every_batch(tmp_path):
    run, _, client = run_to_completion(tmp_path)
    assert len(run.history) == len(client.batches.submitted)
    assert all(s.ended_at for s in run.history)
    assert {s.phase for s in run.history} >= {"plan", "research", "validate", "synthesize"}


def test_the_cost_survives_phases_being_retired(tmp_path):
    """Tasks are cleared between phases so the state file does not grow a
    transcript of the whole run — but the money they spent has to survive."""
    run, _, _ = run_to_completion(tmp_path)
    assert run.tasks == []
    assert run.cost_usd > 0


def test_the_run_reports_what_it_spent_on_searching(tmp_path):
    """Searching is a metered line item here rather than a search subscription
    paid off the books, so a run that does not count it under-reports."""
    run, _, _ = run_to_completion(tmp_path)
    assert sum(r.get("web_searches", 0) for r in run.retired) > 0


# --- failures -------------------------------------------------------------

def test_a_permanently_failed_request_does_not_stall_the_wave(tmp_path):
    """A batch is a set of independent requests. One malformed validator must
    not discard the ones that succeeded alongside it."""
    script = Script()
    # A malformed request fails identically however often it is resubmitted, so
    # the wave must give up on it rather than retrying it forever.
    client = FakeClient(script, fail={"p2r0-researcher-Q2": ("invalid_request_error", "bad")})
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)
    for _ in range(40):
        if orch.tick(client, run) is orch.FINISHED:
            break

    workspace = tmp_path / "research" / "mcp-tool-limits"
    claims = read_jsonl(workspace / "claims.jsonl")
    assert [c["id"] for c in claims] == ["C001"], "Q1's claim still landed"
    assert run.phase == st.AWAITING_APPROVAL, "the run finished despite the failure"


def test_a_retryable_failure_is_resubmitted_unchanged(tmp_path):
    """An expired request is fine as written; it goes back unchanged."""
    from research_agent_batch_server_tools.batching import Failure
    assert Failure("a", "expired").retryable
    assert Failure("a", "errored", "api_error").retryable
    assert not Failure("a", "errored", "invalid_request_error").retryable


# --- phase 7 --------------------------------------------------------------

def test_draft_runs_the_gate_again_over_the_proposal(tmp_path):
    run, script, client = run_to_completion(tmp_path)
    run.phase = st.DRAFT
    run.save()
    for _ in range(10):
        if orch.tick(client, run) is orch.FINISHED:
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
        if orch.tick(client, run) is orch.FINISHED:
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
        if orch.tick(client, run) is orch.FINISHED:
            break
    # One entry per researcher. Each takes exactly one turn here, but keying by
    # custom_id keeps this true if a pause_turn ever adds a second.
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
    from research_agent_batch_server_tools.task import MAX_RETRIES
    script = Script()
    client = FakeClient(script, fail={"p1-planner-main": ("overloaded_error", "busy")})
    run = orch.start(st.Intake(question="MCP tool limits"), tmp_path)

    for _ in range(MAX_RETRIES + 5):
        orch.tick(client, run)
        if run.phase != st.PLAN:
            break

    planner_batches = [b for b in client.batches.submitted
                       if any(r["custom_id"].startswith("p1-") for r in b)]
    assert len(planner_batches) == MAX_RETRIES + 1, "the first send plus three retries"
    assert run.phase != st.PLAN, "it gave up rather than looping forever"
