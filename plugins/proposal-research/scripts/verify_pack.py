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
