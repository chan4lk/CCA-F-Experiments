#!/usr/bin/env python3
"""The gate. Proves an evidence pack's claims are backed by retrieved pages.

Six checks, added across three tasks. Non-zero exit blocks the pipeline.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import read_jsonl  # noqa: E402

FAIL = "FAIL"
WARN = "WARN"

APPENDIX_HEADING = "## Unverified & excluded"
CITATION_RE = re.compile(r"\[(C\d{3,})\]")


class Finding(NamedTuple):
    check: str
    severity: str
    message: str


@dataclass
class Context:
    workspace: Path
    pack_text: str
    body: str
    appendix: str
    claims: dict[str, dict]
    verdicts: dict[str, list[dict]]
    fetches: list[dict] = field(default_factory=list)

    @property
    def body_citations(self) -> list[str]:
        return extract_citations(self.body)

    @property
    def all_citations(self) -> list[str]:
        return extract_citations(self.pack_text)


def extract_citations(text: str) -> list[str]:
    return CITATION_RE.findall(text or "")


def split_pack(text: str) -> tuple[str, str]:
    """Return (body, appendix). Appendix is everything from the heading on."""
    idx = (text or "").find(APPENDIX_HEADING)
    if idx == -1:
        return text or "", ""
    return text[:idx], text[idx:]


def load_context(workspace: Path, pack_name: str = "evidence-pack.md") -> Context:
    workspace = Path(workspace)
    pack_text = (workspace / pack_name).read_text(encoding="utf-8")
    body, appendix = split_pack(pack_text)

    claims = {r["id"]: r for r in read_jsonl(workspace / "claims.jsonl") if "id" in r}

    verdicts: dict[str, list[dict]] = {}
    for row in read_jsonl(workspace / "verdicts.jsonl"):
        verdicts.setdefault(row.get("claim_id"), []).append(row)

    return Context(
        workspace=workspace,
        pack_text=pack_text,
        body=body,
        appendix=appendix,
        claims=claims,
        verdicts=verdicts,
        fetches=read_jsonl(workspace / "fetch-log.jsonl"),
    )


def check_citations_resolve(ctx: Context) -> list[Finding]:
    """Check 1: every [Cxxx] anywhere in the pack resolves to a ledger row."""
    findings = []
    for claim_id in dict.fromkeys(ctx.all_citations):
        if claim_id not in ctx.claims:
            findings.append(Finding(
                "citations-resolve", FAIL,
                f"{claim_id} is cited in the pack but has no row in claims.jsonl",
            ))
    return findings


def check_verdict_admission(ctx: Context) -> list[Finding]:
    """Check 2: body claims carry verdicts that admit them.

    material -> at least two verdicts (haiku plus sonnet escalation), all CONFIRMED
    context  -> CONTRADICTED is fatal; NOT_FOUND is allowed but warned
    MISLEADING -> admitted only if the validator's caveat text appears in the pack
    """
    findings = []
    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue  # already reported by check 1

        rulings = ctx.verdicts.get(claim_id, [])
        if not rulings:
            findings.append(Finding(
                "verdict-admission", FAIL,
                f"{claim_id} is cited in the pack body but has no verdict",
            ))
            continue

        verdicts = [r.get("verdict") for r in rulings]
        tier = claim.get("tier")

        if "CONTRADICTED" in verdicts:
            findings.append(Finding(
                "verdict-admission", FAIL,
                f"{claim_id} was ruled CONTRADICTED and must not appear in the pack body",
            ))
            continue

        for ruling in rulings:
            if ruling.get("verdict") != "MISLEADING":
                continue
            caveat = (ruling.get("caveat") or "").strip()
            if not caveat:
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} was ruled MISLEADING but its caveat is absent",
                ))
            elif caveat not in ctx.pack_text:
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} was ruled MISLEADING but its caveat is absent from the "
                    f"pack: {caveat!r}",
                ))

        if tier == "material":
            if len(rulings) < 2:
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} is material but carries {len(rulings)} verdict(s); the "
                    f"sonnet escalation pass is missing",
                ))
            elif any(v != "CONFIRMED" for v in verdicts):
                findings.append(Finding(
                    "verdict-admission", FAIL,
                    f"{claim_id} is material and must be CONFIRMED by every validator; "
                    f"got {verdicts}",
                ))
        elif "NOT_FOUND" in verdicts:
            findings.append(Finding(
                "verdict-admission", WARN,
                f"{claim_id} is context-tier and NOT_FOUND; admitted as low confidence",
            ))

    return findings


def normalize_url(url: str | None) -> str:
    """Compare URLs ignoring fragment and trailing slash."""
    if not url:
        return ""
    return url.split("#", 1)[0].rstrip("/")


def _fetched_urls_by_agent(ctx: Context) -> dict[str, set[str]]:
    by_agent: dict[str, set[str]] = {}
    for row in ctx.fetches:
        url = normalize_url(row.get("url"))
        if not url:
            continue
        by_agent.setdefault(row.get("agent_id"), set()).add(url)
    return by_agent


def check_fetch_provenance(ctx: Context) -> list[Finding]:
    """Check 3: every cited claim's URL was actually retrieved this session.

    A URL in the pack that never appears in fetch-log.jsonl is the signature of
    a hallucinated citation.
    """
    findings = []
    all_fetched = {
        normalize_url(r.get("url")) for r in ctx.fetches if normalize_url(r.get("url"))
    }
    for claim_id in dict.fromkeys(ctx.all_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        url = normalize_url(claim.get("url"))
        if url and url not in all_fetched:
            findings.append(Finding(
                "fetch-provenance", FAIL,
                f"{claim_id} cites {claim.get('url')} but that page was never retrieved "
                f"during this run",
            ))
    return findings


def check_validator_blindness(ctx: Context) -> list[Finding]:
    """Check 4: each validator that ruled on a body claim fetched that URL itself.

    This is what makes blindness provable. A validator ruling on a page it never
    opened is either echoing the researcher or inventing a verdict.
    """
    findings = []
    by_agent = _fetched_urls_by_agent(ctx)

    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        url = normalize_url(claim.get("url"))
        if not url:
            continue

        for ruling in ctx.verdicts.get(claim_id, []):
            agent_id = ruling.get("validator_agent_id")
            if not agent_id:
                findings.append(Finding(
                    "validator-blindness", FAIL,
                    f"a verdict on {claim_id} carries no validator_agent_id, so its "
                    f"independence cannot be proven",
                ))
                continue
            if url not in by_agent.get(agent_id, set()):
                findings.append(Finding(
                    "validator-blindness", FAIL,
                    f"validator {agent_id} ruled {ruling.get('verdict')} on {claim_id} "
                    f"but never retrieved {claim.get('url')} itself",
                ))
    return findings


def check_validator_tool_restrictions(ctx: Context) -> list[Finding]:
    """Validators must not search. Searching means shopping for a friendlier source."""
    findings = []
    for row in ctx.fetches:
        if row.get("agent_type") == "validator" and row.get("tool") == "WebSearch":
            findings.append(Finding(
                "validator-tool-restrictions", FAIL,
                f"validator {row.get('agent_id')} called WebSearch "
                f"(query={row.get('query')!r}); validators must only fetch the cited URL",
            ))
    return findings


NO_CITATION_MARKER = "<!-- no-citation:"
MIN_FACTUAL_WORDS = 12


def _body_paragraphs(body: str) -> list[str]:
    """Prose paragraphs only: no headings, tables, list items, or code blocks."""
    paragraphs = []
    in_code = False
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("```"):
            in_code = not block.endswith("```") or block.count("```") % 2 == 1
            continue
        if in_code:
            if "```" in block:
                in_code = False
            continue
        first = block.splitlines()[0].lstrip()
        if first.startswith(("#", "|", ">", "-", "*", "+")):
            continue
        paragraphs.append(block)
    return paragraphs


def check_uncited_prose(ctx: Context) -> list[Finding]:
    """Check 5: no factual body paragraph lacks a citation.

    A paragraph may opt out with an explicit `<!-- no-citation: reason -->`
    marker, which keeps the exemption visible and auditable rather than silent.
    """
    findings = []
    for para in _body_paragraphs(ctx.body):
        if NO_CITATION_MARKER in para:
            continue
        if len(para.split()) < MIN_FACTUAL_WORDS:
            continue
        if CITATION_RE.search(para):
            continue
        preview = " ".join(para.split())[:90]
        findings.append(Finding(
            "uncited-prose", FAIL,
            f"factual paragraph carries no citation: \"{preview}...\"",
        ))
    return findings


def check_source_mix(ctx: Context) -> list[Finding]:
    """Check 6: surface material claims resting on weak source types."""
    findings = []
    weak = {"blog", "forum"}
    for claim_id in dict.fromkeys(ctx.body_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        if claim.get("tier") == "material" and claim.get("source_type") in weak:
            findings.append(Finding(
                "source-mix", WARN,
                f"{claim_id} is material but rests on a {claim.get('source_type')} source; "
                f"prefer a first-party page for claims that move the proposal",
            ))
    return findings


def collect_stats(ctx: Context) -> dict:
    source_mix: dict[str, int] = {}
    for claim in ctx.claims.values():
        key = claim.get("source_type", "unknown")
        source_mix[key] = source_mix.get(key, 0) + 1

    verdict_counts: dict[str, int] = {}
    for rulings in ctx.verdicts.values():
        for ruling in rulings:
            key = ruling.get("verdict", "unknown")
            verdict_counts[key] = verdict_counts.get(key, 0) + 1

    return {
        "claims_total": len(ctx.claims),
        "claims_cited": len(set(ctx.all_citations)),
        "source_mix": source_mix,
        "verdict_counts": verdict_counts,
        "fetches_total": len(ctx.fetches),
    }


ALL_CHECKS = [
    check_citations_resolve,
    check_verdict_admission,
    check_fetch_provenance,
    check_validator_blindness,
    check_validator_tool_restrictions,
    check_uncited_prose,
    check_source_mix,
]


def run_checks(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(ctx))
    return findings


def render_report(findings: list[Finding], stats: dict, passed: bool) -> str:
    lines = [
        "# Verify Report",
        "",
        f"**GATE: {'PASS' if passed else 'FAIL'}**",
        "",
        "## Totals",
        "",
        f"- Claims in ledger: {stats.get('claims_total', 0)}",
        f"- Claims cited in pack: {stats.get('claims_cited', 0)}",
        f"- Fetches recorded: {stats.get('fetches_total', 0)}",
        "",
        "## Verdicts",
        "",
    ]
    verdict_counts = stats.get("verdict_counts") or {}
    lines += [f"- {k}: {v}" for k, v in sorted(verdict_counts.items())] or ["- none"]
    lines += ["", "## Source mix", ""]
    source_mix = stats.get("source_mix") or {}
    if source_mix:
        total = sum(source_mix.values()) or 1
        lines.append("| Source type | Claims | Share |")
        lines.append("|---|---|---|")
        for key, count in sorted(source_mix.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {key} | {count} | {round(100 * count / total)}% |")
    else:
        lines.append("- none")

    failures = [f for f in findings if f.severity == FAIL]
    warnings = [f for f in findings if f.severity == WARN]

    lines += ["", "## Failures", ""]
    lines += [f"- **[{f.check}]** {f.message}" for f in failures] or ["- none"]
    lines += ["", "## Warnings", ""]
    lines += [f"- [{f.check}] {f.message}" for f in warnings] or ["- none"]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify an evidence pack against its ledgers")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--pack", default="evidence-pack.md", help="pack filename to verify")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)
    ctx = load_context(workspace, args.pack)
    findings = run_checks(ctx)
    stats = collect_stats(ctx)
    passed = not any(f.severity == FAIL for f in findings)

    stem = "verify-report.md" if args.pack == "evidence-pack.md" else \
        f"verify-report-{Path(args.pack).stem}.md"
    (workspace / stem).write_text(render_report(findings, stats, passed), encoding="utf-8")

    for finding in findings:
        stream = sys.stderr if finding.severity == FAIL else sys.stdout
        print(f"{finding.severity} [{finding.check}] {finding.message}", file=stream)

    print(f"GATE: {'PASS' if passed else 'FAIL'} — report at {workspace / stem}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
