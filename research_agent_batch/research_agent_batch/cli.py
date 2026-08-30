"""research / resume / status / draft / verify.

`resume` exists because a batch may take 24 hours and holding a process open for
that is not a plan. Every command is a thin wrapper around `orchestrator.tick`,
which advances the run as far as it can and then returns; `--wait` just calls it
in a loop.

The human gate is still a separate invocation, for the same reason it is in the
plugin and in `research-agent`: the proposal must not inherit claims nobody
looked at.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import batching, state as st
from .orchestrator import BLOCKED, FINISHED, GateFailed, WAITING, run_gate, start, tick
from .settings import poll_seconds

SUBCOMMANDS = ("research", "resume", "status", "draft", "verify")


def report(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def make_client():
    """Built here rather than at import time so `status` and `verify` — which
    never call the API — work without a key."""
    import anthropic
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return anthropic.Anthropic()


def latest_workspace(cwd: Path) -> Path | None:
    root = Path(cwd) / "research"
    runs = [p for p in root.glob("*") if p.is_dir()] if root.is_dir() else []
    return max(runs, key=lambda p: p.stat().st_mtime, default=None)


def resolve_workspace(args) -> Path:
    if getattr(args, "workspace", None):
        return Path(args.workspace)
    found = latest_workspace(Path(args.cwd))
    if found is None:
        raise SystemExit(f"no run found under {Path(args.cwd) / 'research'}; "
                         f"pass --workspace")
    return found


def normalize_argv(argv: list[str]) -> list[str]:
    """`research_agent_batch "a question"` should not have to say `research`."""
    argv = list(argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "research")
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research_agent_batch",
        description="Cited proposal research on the Message Batches API: half price, "
                    "one batch per round, resumable across days.")
    sub = parser.add_subparsers(dest="command", required=True)

    def workspace_flags(p):
        p.add_argument("--cwd", default=".", help="project root; runs live in <cwd>/research")
        p.add_argument("--workspace", default=None,
                       help="run directory (default: most recent)")

    def wait_flag(p):
        p.add_argument("--wait", action="store_true",
                       help="poll until the run blocks or finishes instead of exiting "
                            "after submitting")

    run = sub.add_parser("research", help="start a run; stops at the human gate")
    run.add_argument("question")
    run.add_argument("--client", default="", help="who the proposal is for")
    run.add_argument("--audience", default="",
                     help="technical buyer, procurement, C-level, regulator")
    run.add_argument("--constraints", default="",
                     help="budget ceiling, timeline, incumbent tech, mandated platform")
    run.add_argument("--context", action="append", default=[], metavar="PATH",
                     help="local folder of notes to ingest (repeatable)")
    run.add_argument("--prior", action="append", default=[], metavar="PATH",
                     help="a previous run or vault to carry claims from (repeatable)")
    run.add_argument("--gap-rounds", type=int, default=2)
    run.add_argument("--cwd", default=".", help="project root; runs live in <cwd>/research")
    wait_flag(run)

    cont = sub.add_parser("resume", help="advance a run: collect, submit the next round")
    workspace_flags(cont)
    wait_flag(cont)

    show = sub.add_parser("status", help="what phase the run is in and what it is waiting on")
    workspace_flags(show)

    write = sub.add_parser("draft", help="phase 7; requires an approved, passing pack")
    workspace_flags(write)
    wait_flag(write)

    check = sub.add_parser("verify", help="re-run the gate over a pack or a proposal")
    check.add_argument("--pack", default="evidence-pack.md")
    workspace_flags(check)
    return parser


# --- driving the run ------------------------------------------------------

def drive(client, run: st.RunState, wait: bool) -> str:
    """Tick until the run blocks or finishes; with --wait, sleep through batches."""
    while True:
        try:
            outcome = tick(client, run, report=report)
        except GateFailed as exc:
            print(f"\nGATE: FAIL — {len(exc.failures)} failure(s). "
                  f"Report: {exc.report_path}", file=sys.stderr)
            for finding in exc.failures[:10]:
                print(f"  [{finding.check}] {finding.message}", file=sys.stderr)
            print("\nThe pack is not trustworthy and no vault was built.", file=sys.stderr)
            run.save()
            return BLOCKED

        if outcome is FINISHED:
            return FINISHED
        if not wait:
            return outcome
        time.sleep(poll_seconds())


def summarise(run: st.RunState) -> None:
    workspace = Path(run.workspace)
    if run.phase == st.AWAITING_APPROVAL:
        print(f"\nEvidence pack: {workspace / 'evidence-pack.md'}")
        print(f"Verify report: {workspace / 'verify-report.md'}")
        print(f"Vault:         {workspace / 'vault'}")
        print(f"Batches:       {len(run.history)} — ${run.cost_usd:.4f} at batch rates")
        print("\nHUMAN GATE — read the pack and the report before drafting anything.")
        print(f"When you have approved it:  python -m research_agent_batch draft "
              f"--workspace {workspace}")
    elif run.phase == st.DONE:
        print(f"\nProposal: {workspace / 'proposal.md'}")
        print(f"Report:   {workspace / 'verify-report-proposal.md'}")
        print(f"Vault:    {workspace / 'vault'}")
        print(f"Batches:  {len(run.history)} — ${run.cost_usd:.4f} at batch rates")
    else:
        print(f"\nWaiting on batch {run.batch_id} ({run.phase}).")
        print(f"Check in with:  python -m research_agent_batch status "
              f"--workspace {workspace}")
        print(f"Continue with:  python -m research_agent_batch resume "
              f"--workspace {workspace}")


def show_status(run: st.RunState) -> int:
    print(f"run       {run.slug}")
    print(f"phase     {run.phase}")
    print(f"batches   {len(run.history)} submitted")
    if run.batch_id:
        try:
            batch = batching.status(make_client(), run.batch_id)
            counts = batching.counts(batch)
            total = sum(counts.values()) or 0
            print(f"waiting   {run.batch_id}  {batch.processing_status}  "
                  f"{counts.get('succeeded', 0)}/{total} done"
                  + (f", {counts['errored']} errored" if counts.get("errored") else ""))
        except Exception as exc:  # noqa: BLE001 — status must work offline
            print(f"waiting   {run.batch_id}  (could not reach the API: {exc})")
    for submission in run.history[-5:]:
        print(f"  {submission.phase:12} {submission.batch_id}  "
              f"{submission.requests:>3} req  "
              f"{'ended ' + submission.ended_at if submission.ended_at else 'in flight'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if args.command == "verify":
        workspace = resolve_workspace(args)
        passed, path, failures = run_gate(workspace, args.pack)
        for finding in failures:
            print(f"FAIL [{finding.check}] {finding.message}", file=sys.stderr)
        print(f"GATE: {'PASS' if passed else 'FAIL'} — report at {path}")
        return 0 if passed else 1

    if args.command == "status":
        return show_status(st.RunState.load(resolve_workspace(args)))

    if args.command == "research":
        intake = st.Intake(
            question=args.question, client=args.client, audience=args.audience,
            constraints=args.constraints, context_paths=list(args.context),
            prior_paths=list(args.prior))
        run = start(intake, Path(args.cwd), max_gap_rounds=args.gap_rounds)
        report(f"workspace {run.workspace}")
    else:
        run = st.RunState.load(resolve_workspace(args))
        if args.command == "draft":
            if run.phase != st.AWAITING_APPROVAL:
                raise SystemExit(
                    f"this run is in phase {run.phase!r}, not {st.AWAITING_APPROVAL!r}. "
                    f"The proposal is only drafted from a pack that passed its gate and "
                    f"that you have approved.")
            run.phase = st.DRAFT
            run.save()

    outcome = drive(make_client(), run, wait=getattr(args, "wait", False))
    if outcome is BLOCKED:
        return 1
    summarise(run)
    return 0
