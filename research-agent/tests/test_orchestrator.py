"""The phase driver, with the model replaced by a stub.

Every rule the plugin's SKILL.md could only *ask* the orchestrator to follow is
asserted here against the code that now enforces it: the gate blocks, the
escalation runs a different model, the verdict carries the identity it was
dispatched with, and the validator's prompt cannot contain the researcher's
quote because the quote is never in scope.
"""
import pytest

from research_agent import orchestrator as orch
from research_agent.agents import PLANNER, RESEARCHER, SYNTHESIZER, VALIDATOR
from research_agent.ledger.claims import append_claim
from research_agent.ledger.workspace import append_jsonl, read_jsonl, utc_now
from research_agent.runner import AgentRun

URL_A = "https://learn.microsoft.com/a"
URL_B = "https://learn.microsoft.com/b"
QUOTE_A = "A maximum of 10 tools per MCP server connection is supported."
QUOTE_B = "AI Agent Studio lets teams build agents natively on the Now Platform."

PLAN = """# Research Plan

## Q1 — What is the MCP tool cap per server connection?
- tier: material
- good answer: a first-party page stating the numeric cap

## Q2 — How does the vendor position the product?
- tier: context
"""

PACK = """# Evidence Pack: MCP limits

## Summary

The tool cap is the binding constraint on this design [C001].

## Recommendation

Proceed, splitting tools across two server connections [C001].

## Findings

### MCP tool limits

The cap is ten tools per server connection [C001].

## Options

### Copilot Studio with MCP

Viable within the cap [C001].

## Constraints

### Tool cap

Ten tools per connection [C001].

## Open Questions

<!-- no-citation: nothing has settled these -->
- Regional GA status

## Unverified & excluded

Nothing was excluded.
"""


class Stub:
    """Stands in for run_agent. Records every dispatch and writes what the real
    agent would have written."""

    def __init__(self, plan=PLAN, pack=PACK, gaps="# Gap Round 1\n"):
        self.calls = []
        self.plan, self.pack, self.gaps = plan, pack, gaps

    async def __call__(self, role, prompt, workspace, cwd=None, model=None,
                       agent_id=None, output_schema=None):
        agent_id = agent_id or f"{role.name}-{len(self.calls):03d}"
        model = model or role.model
        self.calls.append({"role": role.name, "prompt": prompt, "model": model,
                           "agent_id": agent_id, "schema": output_schema})
        run = AgentRun(role=role.name, agent_id=agent_id, model=model, cost_usd=0.01)

        if role.name == "planner":
            (workspace / "plan.md").write_text(self.plan, encoding="utf-8")
        elif role.name == "researcher":
            self._research(workspace, prompt, agent_id)
        elif role.name == "validator":
            run.structured = self._rule(prompt)
            # In a real run the recorder hook logs this; without it every verdict
            # would fail validator-blindness at the gate.
            self._fetch(workspace, _field(prompt, "url"), agent_id, "validator")
        elif role.name == "gap-hunter":
            (workspace / "gaps.md").write_text(self.gaps, encoding="utf-8")
        elif role.name == "synthesizer":
            (workspace / "evidence-pack.md").write_text(self.pack, encoding="utf-8")
        elif role.name == "proposal-writer":
            (workspace / "proposal.md").write_text(self.pack, encoding="utf-8")
        return run

    def _research(self, workspace, prompt, agent_id):
        if "C001" not in prompt:   # only the first researcher records claims
            return
        for claim_id, url, quote, tier in [
            ("C001", URL_A, QUOTE_A, "material"), ("C002", URL_B, QUOTE_B, "context")
        ]:
            append_claim(workspace, {
                "id": claim_id, "sub_q": "Q1", "tier": tier,
                "claim": f"claim behind {claim_id}", "url": url, "quote": quote,
                "source_type": "vendor_doc"})
            self._fetch(workspace, url, agent_id, "researcher")

    def _rule(self, prompt):
        return {"claim_id": _field(prompt, "claim_id"), "verdict": "CONFIRMED",
                "quote": "the validator's own sentence", "caveat": None}

    @staticmethod
    def _fetch(workspace, url, agent_id, agent_type):
        append_jsonl(workspace / "fetch-log.jsonl",
                     {"ts": utc_now(), "tool": "WebFetch", "url": url, "query": None,
                      "agent_id": agent_id, "agent_type": agent_type})


def _field(prompt, key):
    return next(line.split(": ", 1)[1] for line in prompt.splitlines()
                if line.startswith(f"{key}: "))


@pytest.fixture
def stub(monkeypatch):
    s = Stub()
    monkeypatch.setattr(orch, "run_agent", s)
    return s


# --- parsing -------------------------------------------------------------

def test_plan_headings_become_sub_questions():
    questions = orch.parse_questions(PLAN)
    assert [q.id for q in questions] == ["Q1", "Q2"]
    assert [q.tier for q in questions] == ["material", "context"]
    assert questions[0].good_answer.startswith("a first-party page")


def test_a_plain_hyphen_heading_is_accepted():
    """The prompt asks for an em dash. Losing a sub-question over a hyphen would
    be a parser being right at the run's expense."""
    assert orch.parse_questions("## Q1 - a question\n- tier: material\n")[0].id == "Q1"


def test_gap_headings_use_the_same_grammar():
    assert orch.parse_questions("## G1 — a gap\n- tier: material\n")[0].id == "G1"


def test_an_unknown_tier_falls_back_to_material():
    """Material is the strict path: two validators, two models. Guessing the
    cheap tier from a typo would quietly weaken the claim's admission bar."""
    assert orch.parse_questions("## Q1 — q\n- tier: importantish\n")[0].tier == "material"


def test_id_ranges_never_overlap():
    ranges = [orch.id_range(i) for i in range(8)]
    seen = set()
    for first, last in ranges:
        block = set(range(int(first[1:]), int(last[1:]) + 1))
        assert not block & seen
        seen |= block


# --- the run -------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_clean_run_passes_the_gate_and_builds_a_vault(tmp_path, stub):
    result = await orch.research(orch.Intake(question="MCP tool limits"), tmp_path,
                                 max_gap_rounds=1)
    assert result.gate_passed
    assert result.report_path.is_file()
    assert result.vault_path and (result.vault_path / "00-MOC").is_dir()
    assert "GATE: PASS" in result.report_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_the_phases_run_in_order(tmp_path, stub):
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    order = [c["role"] for c in stub.calls]
    assert order[0] == "planner"
    assert order.index("researcher") < order.index("validator")
    assert order.index("validator") < order.index("synthesizer")


@pytest.mark.asyncio
async def test_one_researcher_per_sub_question_each_with_its_own_id_range(tmp_path, stub):
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    prompts = [c["prompt"] for c in stub.calls if c["role"] == "researcher"]
    assert len(prompts) == 2
    assert "C001 through C019" in prompts[0]
    assert "C021 through C039" in prompts[1]


# --- the check that matters most ----------------------------------------

@pytest.mark.asyncio
async def test_a_validator_is_never_shown_the_researchers_quote(tmp_path, stub):
    """The single shortcut that would destroy the only independent check here.

    The plugin could only forbid it in prose. In this port the validator prompt
    is built from three fields — claim_id, claim, url — so the quote is not a
    value the call site holds.
    """
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    for call in stub.calls:
        if call["role"] != "validator":
            continue
        assert QUOTE_A not in call["prompt"]
        assert QUOTE_B not in call["prompt"]
        assert set(line.split(":", 1)[0] for line in call["prompt"].splitlines()) == {
            "claim_id", "claim", "url"}


# --- escalation ----------------------------------------------------------

@pytest.mark.asyncio
async def test_a_material_claim_is_ruled_twice_by_two_models(tmp_path, stub):
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    verdicts = [v for v in read_jsonl(tmp_path / "research" / "mcp-tool-limits" /
                                      "verdicts.jsonl") if v["claim_id"] == "C001"]
    assert len(verdicts) == 2
    assert len({v["validator_model"] for v in verdicts}) == 2
    assert len({v["validator_agent_id"] for v in verdicts}) == 2


@pytest.mark.asyncio
async def test_a_context_claim_is_ruled_once(tmp_path, stub):
    """Escalation is what material tier buys. Spending it on context claims
    would double the validation bill for nothing."""
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    verdicts = [v for v in read_jsonl(tmp_path / "research" / "mcp-tool-limits" /
                                      "verdicts.jsonl") if v["claim_id"] == "C002"]
    assert len(verdicts) == 1


@pytest.mark.asyncio
async def test_the_escalation_model_is_the_pinned_one(tmp_path, stub):
    from research_agent.settings import model_for
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    models = [c["model"] for c in stub.calls if c["role"] == "validator"]
    assert model_for("validator") in models
    assert model_for("validator-escalation") in models


@pytest.mark.asyncio
async def test_a_verdict_carries_the_identity_it_was_dispatched_with(tmp_path, stub):
    """Never self-reported, and never inferred from a cumulative fetch log —
    the inference the plugin needed could not tell two validators of one page
    apart once both had opened it."""
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    dispatched = {c["agent_id"] for c in stub.calls if c["role"] == "validator"}
    recorded = {v["validator_agent_id"] for v in
                read_jsonl(tmp_path / "research" / "mcp-tool-limits" / "verdicts.jsonl")}
    assert recorded <= dispatched


@pytest.mark.asyncio
async def test_validators_are_asked_for_structured_output(tmp_path, stub):
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    schemas = [c["schema"] for c in stub.calls if c["role"] == "validator"]
    assert schemas and all(s == orch.VERDICT_SCHEMA for s in schemas)
    assert [c["schema"] for c in stub.calls if c["role"] == "researcher"] == [None, None]


# --- the gate blocks -----------------------------------------------------

@pytest.mark.asyncio
async def test_a_fabricated_citation_fails_the_gate_and_builds_no_vault(tmp_path, monkeypatch):
    """C999 is in no ledger. The pack must not become a vault."""
    stub = Stub(pack=PACK.replace("[C001]", "[C999]"))
    monkeypatch.setattr(orch, "run_agent", stub)

    with pytest.raises(orch.GateFailed) as exc:
        await orch.research(orch.Intake(question="MCP tool limits"), tmp_path,
                            max_gap_rounds=1)

    assert any(f.check == "citations-resolve" for f in exc.value.failures)
    workspace = tmp_path / "research" / "mcp-tool-limits"
    assert not (workspace / "vault").exists()
    assert "GATE: FAIL" in (workspace / "verify-report.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_the_report_is_written_even_when_the_gate_fails(tmp_path, monkeypatch):
    """A failure the reader cannot see is worse than no gate."""
    monkeypatch.setattr(orch, "run_agent", Stub(pack=PACK.replace("[C001]", "[C999]")))
    with pytest.raises(orch.GateFailed) as exc:
        await orch.research(orch.Intake(question="MCP tool limits"), tmp_path,
                            max_gap_rounds=1)
    assert exc.value.report_path.is_file()


@pytest.mark.asyncio
async def test_a_missing_plan_stops_the_run_before_any_researcher(tmp_path, monkeypatch):
    """A phase whose file never appeared failed, however cheerful its message."""
    class Silent(Stub):
        async def __call__(self, role, prompt, workspace, cwd=None, model=None,
                           agent_id=None, output_schema=None):
            self.calls.append({"role": role.name})
            return AgentRun(role=role.name, agent_id="a1", model="m")

    silent = Silent()
    monkeypatch.setattr(orch, "run_agent", silent)
    with pytest.raises(RuntimeError, match="no plan.md"):
        await orch.research(orch.Intake(question="MCP tool limits"), tmp_path)
    assert [c["role"] for c in silent.calls] == ["planner"]


# --- verdict extraction --------------------------------------------------

def test_a_structured_verdict_is_used_directly():
    run = AgentRun(role="validator", agent_id="v1", model="m",
                   structured={"claim_id": "C001", "verdict": "CONFIRMED", "quote": "q"})
    assert orch._verdict_of(run)["verdict"] == "CONFIRMED"


def test_a_verdict_is_recovered_from_text_when_structured_output_is_missing():
    """A run that hit its turn cap still returns what it had."""
    run = AgentRun(role="validator", agent_id="v1", model="m",
                   text='here it is: {"claim_id":"C001","verdict":"NOT_FOUND"} done')
    assert orch._verdict_of(run)["verdict"] == "NOT_FOUND"


def test_unreadable_output_yields_no_verdict_rather_than_a_guess():
    for run in [AgentRun(role="validator", agent_id="v1", model="m", text="I could not tell"),
                AgentRun(role="validator", agent_id="v1", model="m", text="{not json}"),
                AgentRun(role="validator", agent_id="v1", model="m", text="{}")]:
        assert orch._verdict_of(run) is None


# --- phase 7 -------------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_refuses_over_a_pack_that_does_not_pass(tmp_path, monkeypatch):
    """The whole point of two gates: the proposal cannot inherit unvetted claims."""
    monkeypatch.setattr(orch, "run_agent", Stub())
    workspace = tmp_path / "research" / "run-a"
    workspace.mkdir(parents=True)
    (workspace / "evidence-pack.md").write_text("Unsupported assertion [C999].",
                                                encoding="utf-8")
    with pytest.raises(orch.GateFailed):
        await orch.draft(workspace, orch.Intake(question="q"), tmp_path)


@pytest.mark.asyncio
async def test_draft_runs_the_gate_again_over_the_proposal(tmp_path, stub):
    await orch.research(orch.Intake(question="MCP tool limits"), tmp_path, max_gap_rounds=1)
    workspace = tmp_path / "research" / "mcp-tool-limits"
    result = await orch.draft(workspace, orch.Intake(question="MCP tool limits"), tmp_path)
    assert result.gate_passed
    assert result.report_path.name == "verify-report-proposal.md"
    assert (workspace / "proposal.md").is_file()


# --- cost accounting -----------------------------------------------------

@pytest.mark.asyncio
async def test_every_dispatch_is_priced(tmp_path, stub):
    result = await orch.research(orch.Intake(question="MCP tool limits"), tmp_path,
                                 max_gap_rounds=1)
    assert result.cost_usd == pytest.approx(0.01 * len(result.runs))
    assert len(result.runs) == len(stub.calls)
