"""The phase driver. Phases 0 through 7, in Python.

The plugin's SKILL.md asked a model to do this: dispatch these agents, in this
order, with these models; batch the verdicts; do not proceed past a failing
gate; do not paste a researcher's quote into a validator's prompt. Every one of
those is a rule an instruction can only ask for.

Written as code they are properties instead. The gate is an `if` that raises.
The validator prompt is built from three fields, so there is no quote available
to leak into it. The escalation runs on a different model because the dispatch
says so. And the orchestrator has no context that grows across the run, which is
what the plugin measured as 65% of its own token cost.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .agents import (
    GAP_HUNTER,
    PLANNER,
    PROPOSAL_WRITER,
    RESEARCHER,
    SYNTHESIZER,
    VALIDATOR,
)
from .gate import verify
from .ingest import main as ingest_main
from .ledger.verdicts import record_rows
from .ledger.workspace import ensure_workspace, read_jsonl, slugify
from .runner import AgentRun, run_agent
from .settings import model_for
from .vault.build import build as build_vault
from .vault.build import check_links

MAX_GAP_ROUNDS = 2
# Claim ids are handed out in disjoint blocks so parallel researchers cannot
# collide. 20 wide with 19 usable keeps a block's ids inside one C0NN decade,
# which makes a range easy to state in a prompt and easy to read in the ledger.
IDS_PER_QUESTION = 20
# Enough parallelism to keep the run short; low enough not to open sixty
# sockets against one vendor's docs site at once.
MAX_CONCURRENT_AGENTS = 8

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "claim_id": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["CONFIRMED", "CONTRADICTED", "NOT_FOUND", "MISLEADING"],
            },
            "quote": {"type": ["string", "null"],
                      "description": "Your own verbatim quote from the page. Required for "
                                     "CONFIRMED, CONTRADICTED and MISLEADING."},
            "caveat": {"type": ["string", "null"],
                       "description": "Required for MISLEADING: what a reader would "
                                      "wrongly conclude."},
        },
        "required": ["claim_id", "verdict"],
        "additionalProperties": False,
    },
}


class GateFailed(RuntimeError):
    """Raised when verify_pack finds a FAIL. Blocks phases 6b and 7."""

    def __init__(self, report_path: Path, failures: list[verify.Finding]):
        self.report_path = report_path
        self.failures = failures
        super().__init__(
            f"gate FAILED with {len(failures)} failure(s); report at {report_path}")


@dataclass
class Intake:
    """Phase 0. What the plugin asked for with AskUserQuestion."""

    question: str
    client: str = ""
    audience: str = ""
    constraints: str = ""
    context_paths: list[Path] = field(default_factory=list)
    prior_paths: list[Path] = field(default_factory=list)

    def brief(self) -> str:
        lines = [f"Question: {self.question}"]
        for label, value in (("Client / prospect", self.client),
                             ("Audience", self.audience),
                             ("Hard constraints", self.constraints)):
            if value:
                lines.append(f"{label}: {value}")
        return "\n".join(lines)


@dataclass
class SubQuestion:
    id: str
    question: str
    tier: str = "material"
    good_answer: str = ""


@dataclass
class RunResult:
    workspace: Path
    slug: str
    gate_passed: bool
    report_path: Path
    vault_path: Path | None = None
    pack_path: Path | None = None
    runs: list[AgentRun] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.runs)


Reporter = Callable[[str], None]


def _noop(_: str) -> None:
    return None


# --- parsing the agents' markdown ---------------------------------------

# "## Q3 — how does X price per seat?" and "## G1 — ..." alike. Both an em dash
# and a plain hyphen are accepted: the prompt asks for an em dash, and a model
# that types a hyphen has not made a mistake worth losing a sub-question over.
HEADING_RE = re.compile(r"^##\s+([QG]\d+)\s*[—–-]\s*(.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^-\s*(tier|good answer)\s*:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)


def parse_questions(text: str) -> list[SubQuestion]:
    """Sub-questions from plan.md, or gaps from gaps.md — one grammar, both files."""
    found: list[SubQuestion] = []
    matches = list(HEADING_RE.finditer(text or ""))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end]
        fields = {k.lower(): v for k, v in FIELD_RE.findall(body)}
        tier = (fields.get("tier") or "material").strip().lower()
        found.append(SubQuestion(
            id=match.group(1),
            question=match.group(2).strip(),
            tier=tier if tier in ("material", "context") else "material",
            good_answer=(fields.get("good answer") or "").strip(),
        ))
    return found


def id_range(block: int) -> tuple[str, str]:
    """The disjoint claim-id block for the ``block``-th researcher of the run."""
    start = block * IDS_PER_QUESTION + 1
    return f"C{start:03d}", f"C{start + IDS_PER_QUESTION - 2:03d}"


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


# --- phases -------------------------------------------------------------

async def research(intake: Intake, cwd: Path | None = None, *,
                   report: Reporter = _noop,
                   max_gap_rounds: int = MAX_GAP_ROUNDS) -> RunResult:
    """Phases 0 through 6b. Stops at the human gate, exactly as the plugin did."""
    cwd = Path(cwd) if cwd else Path.cwd()
    slug = slugify(intake.question)
    workspace = ensure_workspace(cwd / "research" / slug)
    runs: list[AgentRun] = []

    report(f"phase 0: workspace {workspace}")

    # Phase 0.5 — local context. No agent involved; this is a file walk.
    ingest(intake, workspace, cwd, report=report)

    # Phase 1 — plan.
    plan_run = await run_agent(
        PLANNER,
        f"{intake.brief()}\n\n"
        f"Workspace: {workspace}\n"
        f"Write your plan to {workspace / 'plan.md'}.",
        workspace, cwd)
    runs.append(plan_run)
    plan_path = workspace / "plan.md"
    if not plan_path.is_file():
        raise RuntimeError(f"planner produced no plan.md; it said: {plan_run.text[:400]}")

    questions = parse_questions(plan_path.read_text(encoding="utf-8"))
    if not questions:
        raise RuntimeError(f"no sub-questions parsed from {plan_path}")
    report(f"phase 1: {len(questions)} sub-questions "
           f"({sum(1 for q in questions if q.tier == 'material')} material)")

    # Phases 2-4 — research, validate, hunt for gaps, and go round again once.
    block = 0
    for round_number in range(1, max_gap_rounds + 1):
        runs += await research_wave(questions, intake, workspace, cwd, block, report=report)
        block += len(questions) + 1  # +1 keeps the carried-claim block disjoint too

        runs += await validation_wave(workspace, cwd, report=report)

        if round_number == max_gap_rounds:
            break
        gap_run = await run_agent(
            GAP_HUNTER,
            f"{intake.brief()}\n\n"
            f"Workspace: {workspace}\n"
            f"This is gap round {round_number} of {max_gap_rounds}.\n"
            f"Write your gaps to {workspace / 'gaps.md'}.",
            workspace, cwd)
        runs.append(gap_run)

        gaps_path = workspace / "gaps.md"
        questions = parse_questions(gaps_path.read_text(encoding="utf-8")) \
            if gaps_path.is_file() else []
        report(f"phase 4: round {round_number} found {len(questions)} gap(s)")
        if not questions:
            break

    # Phase 5 — synthesis.
    synth_run = await run_agent(
        SYNTHESIZER,
        f"{intake.brief()}\n\n"
        f"Workspace: {workspace}\n"
        f"Read the ledgers there and write {workspace / 'evidence-pack.md'}.",
        workspace, cwd)
    runs.append(synth_run)
    report(f"phase 5: evidence pack written")

    # Phase 6 — the gate. A function call, not a rule.
    passed, report_path, failures = run_gate(workspace)
    report(f"phase 6: gate {'PASS' if passed else 'FAIL'} ({len(failures)} failure(s))")

    result = RunResult(workspace=workspace, slug=slug, gate_passed=passed,
                       report_path=report_path, pack_path=workspace / "evidence-pack.md",
                       runs=runs)
    if not passed:
        # Phase 6b never runs on a failed pack: a fully rendered vault is the
        # artefact a reader trusts most, so one must never exist for a pack that
        # did not pass.
        raise GateFailed(report_path, failures) from None

    # Phase 6b — the vault.
    result.vault_path = build_and_check(workspace)
    report(f"phase 6b: vault at {result.vault_path}")
    return result


def ingest(intake: Intake, workspace: Path, cwd: Path, *, report: Reporter = _noop) -> None:
    """Phase 0.5 — carry prior runs forward and read local notes."""
    argv = ["--workspace", str(workspace), "--question", intake.question,
            "--repo", str(cwd), "--limit", "25"]
    for path in intake.prior_paths:
        argv += ["--prior", str(path)]
    for path in intake.context_paths:
        argv += ["--context", str(path)]
    ingest_main(argv)
    carried = len(read_jsonl(workspace / "carried-claims.jsonl"))
    internal = len(read_jsonl(workspace / "internal-claims.jsonl"))
    report(f"phase 0.5: {carried} carried, {internal} internal note(s)")


async def research_wave(questions: list[SubQuestion], intake: Intake, workspace: Path,
                        cwd: Path, block: int, *, report: Reporter = _noop) -> list[AgentRun]:
    """Phase 2 — one researcher per sub-question, plus the carried-claim refresh."""
    tasks = []
    for offset, question in enumerate(questions):
        first, last = id_range(block + offset)
        tasks.append(run_agent(
            RESEARCHER,
            f"Sub-question {question.id} ({question.tier} tier), stated in full:\n"
            f"{question.question}\n\n"
            + (f"A good answer: {question.good_answer}\n\n" if question.good_answer else "")
            + f"Proposal context — {intake.brief()}\n\n"
            f"Use claim ids {first} through {last}. They are yours alone; other "
            f"researchers are running in parallel on other ranges.\n"
            f"Record every claim with the add_claim tool.",
            workspace, cwd))

    # Carried claims are re-fetched so this run has its own provenance for them.
    # The plugin dispatched one researcher per carried claim; a handful of URLs
    # is well within one researcher's reach, and grouping them turns thirty
    # dispatches into six without changing what lands in the ledger.
    carried = read_jsonl(workspace / "carried-claims.jsonl")
    for offset, group in enumerate(_chunks(carried, 5)):
        first, last = id_range(block + len(questions) + offset)
        urls = "\n".join(f"- {row.get('claim')} — {row.get('url')}" for row in group)
        tasks.append(run_agent(
            RESEARCHER,
            f"These claims were verified in a previous run and are being re-checked.\n"
            f"Re-fetch each URL and record what the page says NOW, with a fresh verbatim "
            f"quote. If a page no longer supports its claim, do not record it — say so in "
            f"your final message instead.\n\n{urls}\n\n"
            f"Use claim ids {first} through {last}.",
            workspace, cwd))

    report(f"phase 2: {len(tasks)} researchers dispatched")
    return await _gather_bounded(tasks)


async def validation_wave(workspace: Path, cwd: Path, *,
                          report: Reporter = _noop) -> list[AgentRun]:
    """Phase 3 — validate every unruled claim, then escalate the material ones."""
    runs = await _validate(workspace, cwd, _unruled(workspace), model_for("validator"),
                           report=report, label="phase 3")

    # Escalation: a material claim needs two CONFIRMED rulings from two different
    # validators running two different models. Passing a different model here is
    # what makes the second pass an escalation rather than a repeat; the gate
    # checks both the ids and the models.
    escalate = [c for c in _material_confirmed_once(workspace)]
    if escalate:
        runs += await _validate(workspace, cwd, escalate, model_for("validator-escalation"),
                                report=report, label="phase 3 escalation")
    return runs


async def _validate(workspace: Path, cwd: Path, claims: list[dict], model: str, *,
                    report: Reporter, label: str) -> list[AgentRun]:
    if not claims:
        return []
    report(f"{label}: {len(claims)} validators dispatched on {model}")

    tasks = [
        run_agent(
            VALIDATOR,
            # Three fields. The researcher's quote is not in scope here, so the
            # plugin's sharpest warning — never paste it into a validator prompt —
            # has nothing to warn about.
            f"claim_id: {claim['id']}\n"
            f"claim: {claim['claim']}\n"
            f"url: {claim['url']}",
            workspace, cwd, model=model, output_schema=VERDICT_SCHEMA)
        for claim in claims
    ]
    runs = await _gather_bounded(tasks)

    rows = []
    for claim, run in zip(claims, runs):
        verdict = _verdict_of(run)
        if verdict is None:
            report(f"{label}: {claim['id']} returned no readable verdict; skipped")
            continue
        rows.append({
            "claim_id": claim["id"],
            "verdict": verdict.get("verdict"),
            "quote": verdict.get("quote"),
            "caveat": verdict.get("caveat"),
            # Identity the orchestrator minted and dispatched with — never
            # self-reported, and never inferred from a cumulative fetch log.
            "validator_agent_id": run.agent_id,
            "validator_model": run.model,
        })

    recorded, rejections = record_rows(workspace, rows)
    for rejection in rejections:
        report(f"{label}: REJECTED {rejection}")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    report(f"{label}: {recorded} recorded — "
           + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    return runs


def _verdict_of(run: AgentRun) -> dict | None:
    """The validator's ruling, from structured output or from its final message.

    ``output_format`` makes the structured field the normal path. The text
    fallback exists because a run that hit its turn cap or its budget still
    returns whatever it had, and a readable verdict in that text is worth
    keeping.
    """
    if isinstance(run.structured, dict) and run.structured.get("verdict"):
        return run.structured
    match = re.search(r"\{.*\}", run.text or "", re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and parsed.get("verdict") else None


def _unruled(workspace: Path) -> list[dict]:
    ruled = {r.get("claim_id") for r in read_jsonl(workspace / "verdicts.jsonl")}
    return [c for c in read_jsonl(workspace / "claims.jsonl")
            if c.get("id") and c["id"] not in ruled and c.get("url")]


def _material_confirmed_once(workspace: Path) -> list[dict]:
    """Material claims with exactly one CONFIRMED ruling, awaiting escalation."""
    verdicts: dict[str, list[dict]] = {}
    for row in read_jsonl(workspace / "verdicts.jsonl"):
        verdicts.setdefault(row.get("claim_id"), []).append(row)

    ready = []
    for claim in read_jsonl(workspace / "claims.jsonl"):
        rulings = verdicts.get(claim.get("id"), [])
        if claim.get("tier") != "material" or len(rulings) != 1:
            continue
        if rulings[0].get("verdict") == "CONFIRMED":
            ready.append(claim)
    return ready


async def _gather_bounded(coros: list) -> list[AgentRun]:
    """Run coroutines with bounded concurrency, preserving order."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

    async def guarded(coro):
        async with semaphore:
            return await coro

    return list(await asyncio.gather(*(guarded(c) for c in coros)))


def run_gate(workspace: Path, pack: str = "evidence-pack.md"
             ) -> tuple[bool, Path, list[verify.Finding]]:
    """Phase 6 — run every check and write the report. Returns (passed, path, failures)."""
    ctx = verify.load_context(Path(workspace), pack)
    findings = verify.run_checks(ctx)
    stats = verify.collect_stats(ctx)
    failures = [f for f in findings if f.severity == verify.FAIL]
    passed = not failures

    name = "verify-report.md" if pack == "evidence-pack.md" \
        else f"verify-report-{Path(pack).stem}.md"
    report_path = Path(workspace) / name
    report_path.write_text(verify.render_report(findings, stats, passed), encoding="utf-8")
    return passed, report_path, failures


def build_and_check(workspace: Path, include_proposal: bool = False) -> Path:
    """Phase 6b / 7 — build the vault and refuse to hand back a broken one."""
    vault = build_vault(Path(workspace), include_proposal=include_proposal)
    problems = check_links(vault)
    if problems:
        raise RuntimeError(
            f"vault built with {len(problems)} broken link(s): " + "; ".join(problems[:5]))
    return vault


async def draft(workspace: Path, intake: Intake, cwd: Path | None = None, *,
                report: Reporter = _noop) -> RunResult:
    """Phase 7 — the proposal. Only reachable once a human has approved the pack.

    Re-runs the gate over the draft before the vault is rebuilt, for the same
    reason phase 6b follows phase 6: a vault built over a proposal that failed
    the gate looks exactly like one that passed.
    """
    workspace = Path(workspace)
    cwd = Path(cwd) if cwd else Path.cwd()

    passed, _, _ = run_gate(workspace)
    if not passed:
        raise GateFailed(workspace / "verify-report.md",
                         [verify.Finding("gate", verify.FAIL,
                                         "the evidence pack does not pass its own gate; "
                                         "the proposal would inherit unvetted claims")])

    run = await run_agent(
        PROPOSAL_WRITER,
        f"{intake.brief()}\n\n"
        f"Workspace: {workspace}\n"
        f"The approved pack is {workspace / 'evidence-pack.md'} and its report is "
        f"{workspace / 'verify-report.md'}.\n"
        f"Write the proposal to {workspace / 'proposal.md'}.",
        workspace, cwd)
    report("phase 7: proposal drafted")

    passed, report_path, failures = run_gate(workspace, "proposal.md")
    report(f"phase 7: gate {'PASS' if passed else 'FAIL'} over proposal.md")

    result = RunResult(workspace=workspace, slug=workspace.name, gate_passed=passed,
                       report_path=report_path, pack_path=workspace / "proposal.md",
                       runs=[run])
    if not passed:
        raise GateFailed(report_path, failures)

    result.vault_path = build_and_check(workspace, include_proposal=True)
    report(f"phase 7: vault rebuilt at {result.vault_path}")
    return result
