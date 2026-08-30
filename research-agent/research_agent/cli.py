"""Command line entry point: research, draft, verify.

The plugin's three slash commands, as three subcommands. The split is the same
one and it is the important part: `research` stops at the human gate, and
`draft` is a separate invocation, so the proposal cannot inherit claims nobody
looked at.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .orchestrator import GateFailed, Intake, draft, research, run_gate

SUBCOMMANDS = ("research", "draft", "verify")


def latest_workspace(cwd: Path) -> Path | None:
    """The most recently modified run under ``research/``."""
    root = Path(cwd) / "research"
    runs = [p for p in root.glob("*") if p.is_dir()] if root.is_dir() else []
    return max(runs, key=lambda p: p.stat().st_mtime, default=None)


def resolve_workspace(args) -> Path:
    if args.workspace:
        return Path(args.workspace)
    found = latest_workspace(Path(args.cwd))
    if found is None:
        raise SystemExit(f"no run found under {Path(args.cwd) / 'research'}; "
                         f"pass --workspace")
    return found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research_agent",
        description="Cited proposal research: evidence pack, verification gate, "
                    "and an Obsidian vault.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--cwd", default=".", help="project root; runs live in <cwd>/research")
        p.add_argument("--workspace", default=None, help="run directory (default: most recent)")

    run = sub.add_parser("research", help="phases 0-6b; stops at the human gate")
    run.add_argument("question", help="the proposal research question")
    run.add_argument("--client", default="", help="who the proposal is for")
    run.add_argument("--audience", default="",
                     help="technical buyer, procurement, C-level, regulator")
    run.add_argument("--constraints", default="",
                     help="budget ceiling, timeline, incumbent tech, mandated platform")
    run.add_argument("--context", action="append", default=[], metavar="PATH",
                     help="local folder of notes to ingest (repeatable)")
    run.add_argument("--prior", action="append", default=[], metavar="PATH",
                     help="a previous run or vault to carry claims from (repeatable)")
    run.add_argument("--gap-rounds", type=int, default=2,
                     help="how many research/validate rounds to run (default 2)")
    run.add_argument("--cwd", default=".", help="project root; runs live in <cwd>/research")

    write = sub.add_parser("draft", help="phase 7; requires an approved, passing pack")
    write.add_argument("--client", default="")
    write.add_argument("--audience", default="")
    write.add_argument("--constraints", default="")
    common(write)

    check = sub.add_parser("verify", help="re-run the gate over a pack or a proposal")
    check.add_argument("--pack", default="evidence-pack.md", help="filename to verify")
    common(check)
    return parser


def report(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _question_of(workspace: Path) -> str:
    """Recover the run's question from its plan, for a draft in a later session."""
    plan = Path(workspace) / "plan.md"
    if plan.is_file():
        for line in plan.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    return workspace.name.replace("-", " ")


def normalize_argv(argv: list[str]) -> list[str]:
    """`research_agent "a question"` is the common case; don't make it say so twice."""
    argv = list(argv)
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "research")
    return argv


def main(argv: list[str] | None = None) -> int:
    argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    cwd = Path(args.cwd)

    if args.command == "verify":
        workspace = resolve_workspace(args)
        passed, path, failures = run_gate(workspace, args.pack)
        for finding in failures:
            print(f"FAIL [{finding.check}] {finding.message}", file=sys.stderr)
        print(f"GATE: {'PASS' if passed else 'FAIL'} — report at {path}")
        return 0 if passed else 1

    if args.command == "draft":
        workspace = resolve_workspace(args)
        intake = Intake(question=_question_of(workspace), client=args.client,
                        audience=args.audience, constraints=args.constraints)
        try:
            result = asyncio.run(draft(workspace, intake, cwd, report=report))
        except GateFailed as exc:
            print(f"GATE: FAIL — {exc}", file=sys.stderr)
            return 1
        print(f"\nProposal: {result.pack_path}")
        print(f"Report:   {result.report_path}")
        print(f"Vault:    {result.vault_path}")
        print(f"Cost:     ${result.cost_usd:.4f}")
        return 0

    intake = Intake(
        question=args.question, client=args.client, audience=args.audience,
        constraints=args.constraints,
        context_paths=[Path(p) for p in args.context],
        prior_paths=[Path(p) for p in args.prior],
    )
    try:
        result = asyncio.run(
            research(intake, cwd, report=report, max_gap_rounds=args.gap_rounds))
    except GateFailed as exc:
        print(f"\nGATE: FAIL — {len(exc.failures)} failure(s). Report: {exc.report_path}",
              file=sys.stderr)
        for finding in exc.failures[:10]:
            print(f"  [{finding.check}] {finding.message}", file=sys.stderr)
        print("\nThe pack is not trustworthy and no vault was built.", file=sys.stderr)
        return 1

    print(f"\nEvidence pack: {result.pack_path}")
    print(f"Verify report: {result.report_path}")
    print(f"Vault:         {result.vault_path}")
    print(f"Cost:          ${result.cost_usd:.4f} over {len(result.runs)} agent dispatches")
    print("\nHUMAN GATE — read the pack and the report before drafting anything.")
    print(f"When you have approved it:  python -m research_agent draft "
          f"--workspace {result.workspace}")
    return 0
