"""The phase machine, advanced one tick at a time.

`research-agent` drives its phases with a straight-line async function, because
an SDK dispatch returns in seconds and the whole run fits in one process. A
batch may take 24 hours, so a straight line would mean a process held open
overnight and a run lost to a closed laptop.

So the driver here is a *step function*. `tick()` does as much as can be done
without waiting — collecting a finished batch, submitting the next phase,
running a local one — and then returns. Everything it needs to be called again
tomorrow is in `batch-state.json`.

The pipeline it drives is the same one: plan, research, validate, escalate,
hunt gaps, synthesise, gate, and stop at the human gate.

## What server-side tools took out of this file

`research_agent_batch` has the same shape and one more job: between collecting a
batch and submitting the next one, it runs every tool call the wave produced and
folds the results back in. A phase there is a stack of batches — the researchers
search, come back, get their results, search again — and `_poll` is the thing
that turns the crank.

Here the crank is gone. The searching and the fetching happened inside the
requests that just came back, so collecting a batch and completing a phase are
usually the same event, and `_poll` has nothing to dispatch. What it does
instead is read each message's retrieval blocks into the fetch log, which is the
only reason this process still needs to look inside a response at all.

The one thing that can still send a wave round again is `pause_turn`, and a
continuation resubmits what came back rather than computing anything.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import batching, provenance, state as st
from .agents import (
    GAP_HUNTER,
    PLANNER,
    PROPOSAL_WRITER,
    RESEARCHER,
    SYNTHESIZER,
    VALIDATOR,
    Role,
)
from .task import Task, make_custom_id
from .gate import verify
from .ingest import main as ingest_main
from .ledger.claims import append_claim
from .ledger.verdicts import record_rows
from .ledger.workspace import ensure_workspace, read_jsonl, slugify, utc_now
from .servertools import host_of
from .settings import model_for
from .vault.build import build as build_vault
from .vault.build import check_links

WAITING = "waiting"
BLOCKED = "blocked"
FINISHED = "finished"

IDS_PER_QUESTION = 20
PACK_MAX_TOKENS = 32000
PENDING = "pending-questions.json"

Reporter = Callable[[str], None]


def _noop(_: str) -> None:
    return None


class GateFailed(RuntimeError):
    def __init__(self, report_path: Path, failures: list[verify.Finding]):
        self.report_path = report_path
        self.failures = failures
        super().__init__(
            f"gate FAILED with {len(failures)} failure(s); report at {report_path}")


# --- starting a run -------------------------------------------------------

def start(intake: st.Intake, cwd: Path, max_gap_rounds: int = 2) -> st.RunState:
    """Phase 0 and 0.5: make the workspace and read local context. No batch yet."""
    slug = slugify(intake.question)
    workspace = ensure_workspace(Path(cwd) / "research" / slug)

    argv = ["--workspace", str(workspace), "--question", intake.question,
            "--repo", str(cwd), "--limit", "25"]
    for path in intake.prior_paths:
        argv += ["--prior", str(path)]
    for path in intake.context_paths:
        argv += ["--context", str(path)]
    ingest_main(argv)

    run = st.RunState(slug=slug, workspace=str(workspace), intake=intake,
                      max_gap_rounds=max_gap_rounds)
    run.save()
    return run


# --- the tick -------------------------------------------------------------

def tick(client: Any, run: st.RunState, *, report: Reporter = _noop) -> str:
    """Advance as far as possible without waiting. Returns WAITING/BLOCKED/FINISHED.

    Takes no HTTP client. The sibling needs one to run the wave's tool calls;
    nothing in this process retrieves anything.
    """
    while True:
        if run.phase in st.TERMINAL:
            return FINISHED

        if run.batch_id:
            if _poll(client, run, report) is WAITING:
                return WAITING
            continue

        outcome = _begin(client, run, report)
        if outcome is not None:
            return outcome


def _poll(client: Any, run: st.RunState, report: Reporter) -> str | None:
    """Collect the in-flight batch if it has ended, then move the run on.

    "Move on" is normally to the next phase: the tools already ran, so a
    collected task is a finished one. A task stays active only if a `pause_turn`
    asked for its turn to be continued, and then the continuation goes out as a
    batch of its own.
    """
    batch = batching.status(client, run.batch_id)
    if not batching.has_ended(batch):
        counts = batching.counts(batch)
        report(f"{run.phase}: batch {run.batch_id} {batch.processing_status} "
               f"({counts.get('succeeded', 0)}/{sum(counts.values()) or 0} done)")
        return WAITING

    collected = batching.collect(client, run.batch_id)
    retryable = {f.custom_id for f in collected.failures if f.retryable}

    for task in run.active:
        message = collected.messages.get(task.custom_id)
        if message is not None:
            # advance() returns what this request's server tools retrieved,
            # read out of the message's own result blocks. The row is written
            # here rather than inside advance() so the log stays a thing the
            # orchestrator owns: one workspace, one writer.
            found = task.advance(message)
            provenance.record(Path(run.workspace), task.custom_id,
                              task.role, found)
            continue
        if task.custom_id in retryable:
            # Expired, canceled, or a server-side error: the request is fine as
            # written, so it goes back unchanged — but a resubmission produces
            # no result, so it cannot be bounded by the continuation ceiling and
            # needs one of its own.
            failure = next(f for f in collected.failures
                           if f.custom_id == task.custom_id)
            if task.retry(f"{failure.kind} {failure.error_type}".strip()):
                continue
            report(f"{run.phase}: {task.custom_id} — {task.error}")
            continue
        failure = next((f for f in collected.failures
                        if f.custom_id == task.custom_id), None)
        task.status = "failed"
        task.error = (f"{failure.kind}: {failure.error_type} {failure.message}"
                              if failure else "no result returned for this request")

    for submission in run.history:
        if submission.batch_id == run.batch_id and not submission.ended_at:
            submission.ended_at = utc_now()
    run.batch_id = None

    for failure in collected.failures:
        if not failure.retryable:
            report(f"{run.phase}: {failure.custom_id} failed permanently "
                   f"({failure.error_type}): {failure.message}")

    if run.active:
        _submit(client, run, report)
        run.save()
        return WAITING

    _complete_phase(run, report)
    run.save()
    return None


def _submit(client: Any, run: st.RunState, report: Reporter) -> None:
    batch_id = batching.submit(client, run.active)
    run.batch_id = batch_id
    run.history.append(st.Submission(phase=run.phase, batch_id=batch_id,
                                     requests=len(run.active), submitted_at=utc_now()))
    resumed = sum(1 for c in run.active if c.continuations)
    report(f"{run.phase}: submitted batch {batch_id} — {len(run.active)} request(s)"
           + (f", {resumed} continuing a paused turn" if resumed else ""))


def _begin(client: Any, run: st.RunState, report: Reporter) -> str | None:
    """Build and submit the current phase, or run it locally. None = keep ticking."""
    workspace = Path(run.workspace)

    if run.phase == st.GATE:
        return _run_gate_phase(run, report)

    builders = {
        st.PLAN: _plan_wave,
        st.RESEARCH: _research_wave,
        st.VALIDATE: _validation_wave,
        st.ESCALATE: _escalation_wave,
        st.GAPS: _gap_wave,
        st.SYNTHESIZE: _synthesis_wave,
        st.DRAFT: _draft_wave,
    }
    run.tasks = builders[run.phase](run, workspace)

    if not run.tasks:
        # A phase with nothing to do is normal: no material claims to escalate,
        # no gaps worth another round.
        report(f"{run.phase}: nothing to do")
        _complete_phase(run, report)
        run.save()
        return None

    _submit(client, run, report)
    run.save()
    return WAITING


# --- building each wave ---------------------------------------------------

def _task(role: Role, phase: str, key: str, prompt: str, *,
          model: str = "", allowed_domains: list[str] | None = None,
          max_tokens: int = 16000) -> Task:
    """One agent's request.

    The tool grant is built here rather than carried on the Role because both
    of the things that shape it are per-request: the tool type variant follows
    the model, and `allowed_domains` follows the claim.
    """
    model = model or role.model
    return Task(
        custom_id=make_custom_id(phase, role.name, key),
        role=role.name,
        model=model,
        system=role.prompt(),
        messages=[{"role": "user", "content": prompt}],
        tools=role.tools(model, allowed_domains),
        output_config=role.output_config,
        max_continuations=role.max_continuations,
        max_tokens=max_tokens,
        key=key,
    )


def _plan_wave(run: st.RunState, workspace: Path) -> list[Task]:
    internal = read_jsonl(workspace / "internal-claims.jsonl")
    carried = read_jsonl(workspace / "carried-claims.jsonl")
    prompt = (
        f"{run.intake.brief()}\n\n"
        f"Internal notes (unverified, never evidence — use them to see what matters):\n"
        f"{_bullets(n.get('claim') for n in internal) or '  none'}\n\n"
        f"Claims carried from a prior run (already verified; do not rediscover these):\n"
        f"{_bullets(c.get('claim') for c in carried) or '  none'}"
    )
    return [_task(PLANNER, "p1", "main", prompt)]


def _research_wave(run: st.RunState, workspace: Path) -> list[Task]:
    questions = _load_pending(workspace)
    tasks = []
    for question in questions:
        block = run.take_id_block()
        first, last = _id_range(block)
        tasks.append(_task(
            RESEARCHER, f"p2r{run.gap_round}", question["id"],
            f"Sub-question {question['id']} ({question.get('tier', 'material')} tier), "
            f"stated in full:\n{question['question']}\n\n"
            f"A good answer: {question.get('good_answer', 'a first-party page stating it')}\n\n"
            f"Proposal context — {run.intake.brief()}\n\n"
            f"Record claims with ids from {first} to {last}. That range is yours alone; "
            f"other researchers are working other ranges in this same batch."))

    # Carried claims are re-fetched so this run has its own provenance for them.
    carried = read_jsonl(workspace / "carried-claims.jsonl")
    if carried and run.gap_round == 0:
        for index, group in enumerate(_chunks(carried, 5)):
            block = run.take_id_block()
            first, last = _id_range(block)
            listing = _bullets(f"{r.get('claim')} — {r.get('url')}" for r in group)
            tasks.append(_task(
                RESEARCHER, "p2c", f"g{index}",
                f"These claims were verified in a previous run and are being re-checked.\n"
                f"Fetch each URL and record what the page says NOW, with a fresh verbatim "
                f"quote. If a page no longer supports its claim, leave it out and say so "
                f"in could_not_source.\n\n{listing}\n\n"
                f"Use claim ids {first} to {last}."))
    return tasks


def _validation_wave(run: st.RunState, workspace: Path) -> list[Task]:
    return [_validator(claim, "p3", "a", model_for("validator"))
            for claim in _unruled(workspace)]


def _escalation_wave(run: st.RunState, workspace: Path) -> list[Task]:
    """A material claim needs two CONFIRMED rulings from two different validators
    on two different models. This is the second one; the gate checks both."""
    return [_validator(claim, "p3e", "b", model_for("validator-escalation"))
            for claim in _material_confirmed_once(workspace)]


def _validator(claim: dict, phase: str, suffix: str, model: str) -> Task:
    return _task(
        VALIDATOR, phase, f"{claim['id']}-{suffix}",
        # Three fields. The researcher's quote is not among them, so the one
        # shortcut that would destroy this system's only independent check is
        # not available to make.
        f"claim_id: {claim['id']}\nclaim: {claim['claim']}\nurl: {claim['url']}",
        # The model is passed in rather than set afterwards because the tool
        # grant is built from it: the haiku pass takes the basic web_fetch, the
        # sonnet escalation takes the dynamic-filtering one.
        model=model,
        # The single host this validator may reach — a field on the tool
        # definition, enforced before Anthropic's fetcher opens a socket, not an
        # instruction the model is asked to respect.
        allowed_domains=[host_of(claim["url"])])


def _gap_wave(run: st.RunState, workspace: Path) -> list[Task]:
    claims = read_jsonl(workspace / "claims.jsonl")
    verdicts = read_jsonl(workspace / "verdicts.jsonl")
    prompt = (
        f"{run.intake.brief()}\n\n"
        f"This is gap round {run.gap_round + 1} of {run.max_gap_rounds}.\n\n"
        f"The plan:\n{_bullets(q['question'] for q in _load_plan(workspace))}\n\n"
        f"Claims established so far:\n{_claim_digest(claims, verdicts)}"
    )
    return [_task(GAP_HUNTER, f"p4r{run.gap_round}", "main", prompt)]


def _synthesis_wave(run: st.RunState, workspace: Path) -> list[Task]:
    claims = read_jsonl(workspace / "claims.jsonl")
    verdicts = read_jsonl(workspace / "verdicts.jsonl")
    internal = read_jsonl(workspace / "internal-claims.jsonl")
    prompt = (
        f"{run.intake.brief()}\n\nSubject: {run.subject or run.intake.question}\n\n"
        f"THE LEDGER — this is everything. Every claim, with every verdict on it:\n\n"
        f"{_full_ledger(claims, verdicts)}\n\n"
        f"Internal notes (never evidence; appendix only, marked unverified):\n"
        f"{_bullets(n.get('claim') for n in internal) or '  none'}\n\n"
        f"Open gaps that were never closed:\n"
        f"{_bullets(g['question'] for g in _load_gaps(workspace)) or '  none'}"
    )
    return [_task(SYNTHESIZER, "p5", "main", prompt, max_tokens=PACK_MAX_TOKENS)]


def _draft_wave(run: st.RunState, workspace: Path) -> list[Task]:
    pack = (workspace / "evidence-pack.md").read_text(encoding="utf-8")
    report_text = _read_if_present(workspace / "verify-report.md")
    prompt = (
        f"{run.intake.brief()}\n\n"
        f"THE APPROVED EVIDENCE PACK — every fact you may state is in here:\n\n{pack}\n\n"
        f"Its verification report:\n\n{report_text}"
    )
    return [_task(PROPOSAL_WRITER, "p7", "main", prompt,
                          max_tokens=PACK_MAX_TOKENS)]


# --- completing each phase ------------------------------------------------

def _complete_phase(run: st.RunState, report: Reporter) -> None:
    """Consume the finished wave's results and choose the next phase."""
    workspace = Path(run.workspace)
    phase = run.phase

    for task in run.failed:
        report(f"{phase}: {task.custom_id} failed — {task.error}")

    if phase == st.PLAN:
        plan = _first_parsed(run) or {}
        questions = plan.get("sub_questions") or []
        run.subject = plan.get("subject", "") or run.intake.question
        _write_json(workspace / "plan.json", plan)
        (workspace / "plan.md").write_text(_render_plan(run.subject, questions),
                                           encoding="utf-8")
        _write_json(workspace / PENDING, questions)
        report(f"plan: {len(questions)} sub-questions "
               f"({sum(1 for q in questions if q.get('tier') == 'material')} material)")
        run.phase = st.RESEARCH

    elif phase == st.RESEARCH:
        recorded, rejected = _record_claims(run, workspace)
        report(f"research: {recorded} claim(s) recorded"
               + (f", {rejected} rejected" if rejected else ""))
        run.phase = st.VALIDATE

    elif phase in (st.VALIDATE, st.ESCALATE):
        recorded, rejections = _record_verdicts(run, workspace)
        for rejection in rejections:
            report(f"{phase}: REJECTED {rejection}")
        report(f"{phase}: {recorded} verdict(s) recorded")
        run.phase = st.ESCALATE if phase == st.VALIDATE else _after_escalation(run)

    elif phase == st.GAPS:
        result = _first_parsed(run) or {}
        gaps = [] if result.get("complete") else (result.get("gaps") or [])
        _write_json(workspace / "gaps.json", gaps)
        (workspace / "gaps.md").write_text(
            _render_gaps(run.gap_round + 1, gaps), encoding="utf-8")
        run.gap_round += 1
        if gaps and run.gap_round < run.max_gap_rounds:
            report(f"gaps: round {run.gap_round} found {len(gaps)}; researching them")
            _write_json(workspace / PENDING, gaps)
            run.phase = st.RESEARCH
        else:
            report(f"gaps: round {run.gap_round} found {len(gaps)}; "
                   f"remaining gaps become the pack's Open Questions")
            run.phase = st.SYNTHESIZE

    elif phase == st.SYNTHESIZE:
        markdown = (_first_parsed(run) or {}).get("markdown", "")
        (workspace / "evidence-pack.md").write_text(markdown, encoding="utf-8")
        report(f"synthesize: evidence pack written ({len(markdown):,} chars)")
        run.phase = st.GATE

    elif phase == st.DRAFT:
        markdown = (_first_parsed(run) or {}).get("markdown", "")
        (workspace / "proposal.md").write_text(markdown, encoding="utf-8")
        report(f"draft: proposal written ({len(markdown):,} chars)")
        run.phase = st.GATE

    run.retire()


def _after_escalation(run: st.RunState) -> str:
    """Another gap round, or straight to synthesis if they are used up."""
    return st.GAPS if run.gap_round < run.max_gap_rounds else st.SYNTHESIZE


def _run_gate_phase(run: st.RunState, report: Reporter) -> str:
    """Phase 6 / 7: the gate, then the vault. Local, and blocking on failure."""
    workspace = Path(run.workspace)
    drafted = (workspace / "proposal.md").is_file() and _has_drafted(run)
    pack = "proposal.md" if drafted else "evidence-pack.md"

    passed, report_path, failures = run_gate(workspace, pack)
    report(f"gate: {'PASS' if passed else 'FAIL'} over {pack} "
           f"({len(failures)} failure(s)) — {report_path}")
    if not passed:
        # The vault is never built over a failed pack: a fully rendered vault is
        # the artefact a reader trusts most, so one must not exist for a pack
        # that did not pass.
        raise GateFailed(report_path, failures)

    vault = build_and_check(workspace, include_proposal=drafted)
    report(f"gate: vault at {vault}")
    run.phase = st.DONE if drafted else st.AWAITING_APPROVAL
    run.save()
    return FINISHED


def _has_drafted(run: st.RunState) -> bool:
    return any(s.phase == st.DRAFT for s in run.history)


# --- local helpers --------------------------------------------------------

def run_gate(workspace: Path, pack: str = "evidence-pack.md"
             ) -> tuple[bool, Path, list[verify.Finding]]:
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
    vault = build_vault(Path(workspace), include_proposal=include_proposal)
    problems = check_links(vault)
    if problems:
        raise RuntimeError(
            f"vault built with {len(problems)} broken link(s): " + "; ".join(problems[:5]))
    return vault


def _record_claims(run: st.RunState, workspace: Path) -> tuple[int, int]:
    recorded = rejected = 0
    for task in run.done:
        payload = task.parsed or {}
        for row in payload.get("claims") or []:
            row = dict(row)
            row["sub_q"] = payload.get("sub_q") or task.key
            ok, _message, _warning = append_claim(workspace, row)
            recorded += ok
            rejected += not ok
    return recorded, rejected


def _record_verdicts(run: st.RunState, workspace: Path) -> tuple[int, list[str]]:
    rows = []
    for task in run.done:
        verdict = task.parsed or {}
        if not verdict.get("verdict"):
            continue
        rows.append({
            "claim_id": verdict.get("claim_id") or task.key.rsplit("-", 1)[0],
            "verdict": verdict["verdict"],
            "quote": verdict.get("quote"),
            "caveat": verdict.get("caveat"),
            # The identity this process dispatched, which is also the custom_id
            # of the batch request and the agent_id in the fetch log. Never
            # self-reported, never inferred.
            "validator_agent_id": task.custom_id,
            "validator_model": task.model,
        })
    return record_rows(workspace, rows)


def _unruled(workspace: Path) -> list[dict]:
    ruled = {r.get("claim_id") for r in read_jsonl(workspace / "verdicts.jsonl")}
    return [c for c in read_jsonl(workspace / "claims.jsonl")
            if c.get("id") and c["id"] not in ruled and c.get("url")]


def _material_confirmed_once(workspace: Path) -> list[dict]:
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


def _first_parsed(run: st.RunState) -> dict | None:
    for task in run.done:
        if task.parsed:
            return task.parsed
    return None


def _id_range(block: int) -> tuple[str, str]:
    start = block * IDS_PER_QUESTION + 1
    return f"C{start:03d}", f"C{start + IDS_PER_QUESTION - 2:03d}"


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _bullets(values) -> str:
    return "\n".join(f"- {v}" for v in values if v)


def _claim_digest(claims: list[dict], verdicts: list[dict]) -> str:
    """Enough for the gap hunter to see what is covered, without the quotes."""
    rulings: dict[str, list[str]] = {}
    for row in verdicts:
        rulings.setdefault(row.get("claim_id"), []).append(row.get("verdict", "?"))
    return "\n".join(
        f"- [{c['id']}] ({c.get('tier')}) {c.get('claim')} "
        f"[{'/'.join(rulings.get(c['id'], ['unruled']))}]"
        for c in claims) or "  none"


def _full_ledger(claims: list[dict], verdicts: list[dict]) -> str:
    """Every claim with its quote and every ruling on it.

    The synthesizer has no filesystem, so this text is literally all it knows.
    That is the point: it cannot state a fact that is not here.
    """
    rulings: dict[str, list[dict]] = {}
    for row in verdicts:
        rulings.setdefault(row.get("claim_id"), []).append(row)

    blocks = []
    for claim in claims:
        lines = [f"[{claim['id']}] tier={claim.get('tier')} "
                 f"source_type={claim.get('source_type')}",
                 f"  claim: {claim.get('claim')}",
                 f"  url:   {claim.get('url')}",
                 f"  quote: \"{claim.get('quote')}\""]
        for ruling in rulings.get(claim["id"], []):
            lines.append(f"  verdict: {ruling.get('verdict')} "
                         f"by {ruling.get('validator_model')}")
            if ruling.get("caveat"):
                lines.append(f"    caveat (must appear verbatim in the pack if you state "
                             f"this claim): {ruling['caveat']}")
        if claim["id"] not in rulings:
            lines.append("  verdict: NONE — this claim was never validated")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "  the ledger is empty"


def _render_plan(subject: str, questions: list[dict]) -> str:
    lines = [f"# Research Plan — {subject}", ""]
    for question in questions:
        lines += [f"## {question.get('id')} — {question.get('question')}",
                  f"- tier: {question.get('tier')}",
                  f"- good answer: {question.get('good_answer')}",
                  f"- seeded by: {question.get('seeded_by') or 'none'}", ""]
    return "\n".join(lines)


def _render_gaps(round_number: int, gaps: list[dict]) -> str:
    lines = [f"# Gap Round {round_number}", ""]
    if not gaps:
        lines += ["No gaps that would change the proposal.", ""]
    for gap in gaps:
        lines += [f"## {gap.get('id')} — {gap.get('question')}",
                  f"- why it matters: {gap.get('good_answer')}",
                  f"- tier: {gap.get('tier')}", ""]
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    if not Path(path).is_file():
        return default
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _read_if_present(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8") if Path(path).is_file() else ""


def _load_pending(workspace: Path) -> list[dict]:
    return _read_json(workspace / PENDING, [])


def _load_plan(workspace: Path) -> list[dict]:
    return (_read_json(workspace / "plan.json", {}) or {}).get("sub_questions", [])


def _load_gaps(workspace: Path) -> list[dict]:
    return _read_json(workspace / "gaps.json", [])
