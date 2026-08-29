#!/usr/bin/env python3
"""The gate. Proves an evidence pack's claims are backed by retrieved pages.

Seven checks. Non-zero exit blocks the pipeline. The gate is the last line of
defence and assumes nothing about what the writer validated: every field it
relies on — url, quote, caveat, claim_id — is checked here too.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import (  # noqa: E402
    MAX_QUOTE_WORDS,
    iter_fence_state,
    normalize_url,
    read_jsonl,
)

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
        claim_id = row.get("claim_id")
        if claim_id:
            verdicts.setdefault(claim_id, []).append(row)

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
            else:
                agent_ids = {r.get("validator_agent_id") for r in rulings
                             if r.get("validator_agent_id")}
                models = {r.get("validator_model") for r in rulings
                          if r.get("validator_model")}
                if len(agent_ids) < 2:
                    findings.append(Finding(
                        "verdict-admission", FAIL,
                        f"{claim_id} is material but all {len(rulings)} verdicts come from "
                        f"the same validator ({sorted(agent_ids) or ['none']}); the same "
                        f"validator ruling twice is not an escalation",
                    ))
                if len(models) < 2:
                    findings.append(Finding(
                        "verdict-admission", FAIL,
                        f"{claim_id} is material but every verdict was ruled by model "
                        f"{sorted(models) or ['none']}; the sonnet escalation pass is missing",
                    ))
                if any(v != "CONFIRMED" for v in verdicts):
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
        if not url:
            findings.append(Finding(
                "fetch-provenance", FAIL,
                f"{claim_id} is cited but its ledger row carries no url, so there is no "
                f"page whose retrieval could be proven",
            ))
        elif url not in all_fetched:
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
            findings.append(Finding(
                "validator-blindness", FAIL,
                f"{claim_id} is cited in the pack body but its ledger row carries no url, "
                f"so no validator's independence can be proven against it",
            ))
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
NO_CITATION_RE = re.compile(r"<!--\s*no-citation:\s*(.*?)\s*-->", re.DOTALL)
MIN_FACTUAL_WORDS = 12


LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
TABLE_DELIMITER_RE = re.compile(r"^\|?[\s:|-]+\|?$")


class Unit(NamedTuple):
    """One assertion-bearing chunk of the pack body."""
    kind: str
    text: str


def _split_block(block: str) -> list[Unit]:
    """Break one blank-line-delimited block into its assertion-bearing units.

    A bullet and a table row assert facts exactly as a sentence does — an LLM
    synthesizer emits caps, prices and availability in those shapes more often
    than in prose — so each is its own unit. Only genuine structure is dropped:
    headings, table delimiter rows, and blockquotes, which carry verbatim source
    text rather than the pack's own assertions.
    """
    units: list[Unit] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            units.append(Unit("paragraph", " ".join(paragraph)))
            paragraph.clear()

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("#") or stripped.startswith(">"):
            flush()
        elif stripped.startswith("|"):
            flush()
            if not TABLE_DELIMITER_RE.match(stripped):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                units.append(Unit("table row", " ".join(c for c in cells if c)))
        elif LIST_ITEM_RE.match(stripped):
            flush()
            units.append(Unit("list item", LIST_ITEM_RE.sub("", stripped)))
        elif units and units[-1].kind == "list item" and not paragraph:
            # A wrapped continuation line belongs to the item above it.
            units[-1] = Unit("list item", f"{units[-1].text} {stripped}")
        else:
            paragraph.append(stripped)
    flush()
    return units


def _body_units(body: str) -> list[Unit]:
    """Every unit of the pack body that must carry a citation.

    Fenced code is dropped whole; a block carrying the `<!-- no-citation: -->`
    marker is dropped whole, so one marker above a list or table exempts it.
    """
    units: list[Unit] = []
    outside_fences = "\n".join(
        line for line, in_fence in iter_fence_state(body) if not in_fence
    )
    for block in outside_fences.split("\n\n"):
        block = block.strip()
        if not block or NO_CITATION_MARKER in block:
            continue
        units.extend(_split_block(block))
    return units


def _no_citation_reasons(body: str) -> list[str]:
    """Every escape-hatch marker in the body, so the gate can report each one.

    Both pack writers are told the gate reports every marker. That is what makes
    the exemption auditable rather than a silent way to drop a section out of the
    check, so the gate has to actually do it.
    """
    outside_fences = "\n".join(
        line for line, in_fence in iter_fence_state(body) if not in_fence
    )
    return [" ".join(m.split()) for m in NO_CITATION_RE.findall(outside_fences)]


def check_uncited_prose(ctx: Context) -> list[Finding]:
    """Check 5: no factual body statement lacks a citation.

    Paragraphs, list items and table rows are all checked. Exempting bullets and
    tables was the single hole through which a pack with no citations at all
    could pass the gate: every other check keys off the citations that are
    present, so this check is the only one that requires a citation to exist.

    A block may opt out with an explicit `<!-- no-citation: reason -->` marker,
    which keeps the exemption visible and auditable rather than silent.
    """
    findings = []
    for reason in _no_citation_reasons(ctx.body):
        findings.append(Finding(
            "uncited-prose", WARN,
            f"a block is exempted from citation by an explicit marker: {reason!r}",
        ))
    for unit in _body_units(ctx.body):
        if len(unit.text.split()) < MIN_FACTUAL_WORDS:
            continue
        if CITATION_RE.search(unit.text):
            continue
        preview = " ".join(unit.text.split())[:90]
        findings.append(Finding(
            "uncited-prose", FAIL,
            f"factual {unit.kind} carries no citation: \"{preview}...\"",
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


def check_claim_quotes(ctx: Context) -> list[Finding]:
    """Check 7: every cited claim rests on a verbatim quote of workable length.

    Requirement (a) of the guarantee — a claim is backed by a verbatim quote —
    rested entirely on add_claim.py being the only writer of claims.jsonl. It is
    not: ledger_lint only guards Write and Edit, and the researcher agent carries
    Bash, so an append redirect reaches the ledger unvalidated. The gate is the
    last line of defence and must not assume the writer validated.
    """
    findings = []
    for claim_id in dict.fromkeys(ctx.all_citations):
        claim = ctx.claims.get(claim_id)
        if claim is None:
            continue
        quote = (claim.get("quote") or "").strip()
        if not quote:
            findings.append(Finding(
                "claim-quote", FAIL,
                f"{claim_id} is cited but its ledger row carries no verbatim quote, so "
                f"nothing on the page ties the claim to the source",
            ))
        elif len(quote.split()) > MAX_QUOTE_WORDS:
            findings.append(Finding(
                "claim-quote", FAIL,
                f"{claim_id} carries a {len(quote.split())}-word quote, over the "
                f"{MAX_QUOTE_WORDS}-word limit; that is a page dump, not the supporting "
                f"sentence",
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
    check_claim_quotes,
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
