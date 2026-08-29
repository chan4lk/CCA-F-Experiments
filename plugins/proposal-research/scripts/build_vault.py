#!/usr/bin/env python3
"""Phase 5b/7b — file the evidence pack into a self-contained Obsidian vault.

Deterministic on purpose. Fable writes the prose; this script does the filing,
wikilinking and anchor generation. A model that files its own citations can
misfile them, and that would put a hole in the provenance guarantee at the very
last step.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import iter_fence_state, read_jsonl  # noqa: E402

TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "vault"

VAULT_DIRS = [
    "00-MOC",
    "01-Findings",
    "02-Options",
    "03-Constraints",
    "04-Risks-and-Gaps",
    "05-Proposal",
    "06-Sources",
]

REQUIRED_SECTIONS = ["Summary", "Recommendation", "Findings", "Options", "Constraints"]

SECTION_MAP = {
    "Findings": ("01-Findings", "finding"),
    "Options": ("02-Options", "option"),
    "Constraints": ("03-Constraints", "constraint"),
}

_UNSAFE = re.compile(r"[/\\:*?\"<>|]")


def parse_sections(text: str) -> dict[str, str]:
    """Split markdown on H2 headings into {heading: body}."""
    sections: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line, in_fence in iter_fence_state(text):
        # Check for H2 heading (only if not in fence)
        if line.startswith("## ") and not in_fence:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[3:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def split_subsections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a section body on H3 headings into (preamble, [(title, body)])."""
    preamble_lines: list[str] = []
    subs: list[tuple[str, str]] = []
    current_title: str | None = None
    current_buffer: list[str] = []

    for line, in_fence in iter_fence_state(text):
        # Check for H3 heading (only if not in fence)
        if line.startswith("### ") and not in_fence:
            # Save the previous subsection if any
            if current_title is not None:
                subs.append((current_title, "\n".join(current_buffer).strip()))

            # Start a new subsection
            current_title = line[4:].strip()
            current_buffer = []
        elif current_title is not None:
            # We're inside a subsection
            current_buffer.append(line)
        else:
            # We're in the preamble (before the first H3)
            preamble_lines.append(line)

    # Save the last subsection if any
    if current_title is not None:
        subs.append((current_title, "\n".join(current_buffer).strip()))

    preamble = "\n".join(preamble_lines).strip()
    return preamble, subs


def note_filename(title: str) -> str:
    return f"{_UNSAFE.sub('-', title).strip()}.md"


def wikilink(title: str) -> str:
    """Link to a note by its FILENAME, showing its original title.

    note_filename rewrites `/\\:*?"<>|` out of a title, so a section called
    `### Licensing: seat costs` is filed as `Licensing- seat costs.md`. Linking
    to the raw title then resolves to nothing and fails the link check — a colon
    in a heading is the most common punctuation an LLM will emit, so this was a
    hard failure on ordinary input. The `[[target|display]]` form keeps the
    heading readable in the vault while pointing at the file that exists.
    """
    target = note_filename(title).removesuffix(".md")
    return f"[[{target}]]" if target == title else f"[[{target}|{title}]]"


def render_note(title: str, tags: list[str], body: str, meta: dict | None = None, generated: bool = True) -> str:
    lines = ["---", f"tags: [{', '.join(tags)}]"]
    if generated:
        lines.append("generated: true")
    for key, value in (meta or {}).items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", f"# {title}", "", body.strip(), ""]
    return "\n".join(lines)


def copy_obsidian_config(vault: Path) -> None:
    source = TEMPLATE_ROOT / ".obsidian"
    target = vault / ".obsidian"
    target.mkdir(parents=True, exist_ok=True)
    for item in source.glob("*.json"):
        shutil.copy2(item, target / item.name)


def _is_generated_note(note_path: Path) -> bool:
    """Check if a note has the 'generated: true' marker in properly terminated frontmatter.

    Only deletes notes with a well-formed frontmatter block that explicitly contains
    the generated marker. If the frontmatter is malformed, unterminated, or absent,
    treat the note as NOT generated and leave it alone (fail toward preservation).
    """
    try:
        content = note_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Must start with --- on its own line
        if not lines or lines[0] != "---":
            return False

        # Find the closing --- line
        closing_fence_idx = None
        for i in range(1, len(lines)):
            if lines[i] == "---":
                closing_fence_idx = i
                break

        # If no closing fence found, treat as not generated
        if closing_fence_idx is None:
            return False

        # Only check lines strictly between the opening and closing ---
        for line in lines[1:closing_fence_idx]:
            if line.strip() == "generated: true":
                return True

        return False
    except Exception:
        # If we cannot parse the file, treat as NOT generated
        return False


def _clear_generated(vault: Path) -> None:
    """Idempotency: drop previously generated notes before rewriting."""
    for name in VAULT_DIRS:
        folder = vault / name
        if folder.is_dir():
            for note in folder.glob("*.md"):
                if _is_generated_note(note):
                    note.unlink()


def build(workspace: Path, include_proposal: bool = False) -> Path:
    workspace = Path(workspace)
    pack_text = (workspace / "evidence-pack.md").read_text(encoding="utf-8")
    sections = parse_sections(pack_text)

    missing = [s for s in REQUIRED_SECTIONS if s not in sections]
    if missing:
        raise ValueError(
            f"evidence-pack.md is missing required section(s): {', '.join(missing)}. "
            f"The synthesizer must emit the fixed H2 contract."
        )

    vault = workspace / "vault"
    for name in VAULT_DIRS:
        (vault / name).mkdir(parents=True, exist_ok=True)
    copy_obsidian_config(vault)
    _clear_generated(vault)

    claims = {r["id"]: r for r in read_jsonl(workspace / "claims.jsonl") if "id" in r}

    # Sectioned notes with collision detection
    linked_titles: dict[str, list[str]] = {}
    for heading, (folder, tag) in SECTION_MAP.items():
        titles = []
        written_filenames: dict[str, str] = {}  # filename -> title for collision detection

        preamble, subsections = split_subsections(sections.get(heading, ""))

        # Write preamble note if it exists
        if preamble:
            preamble_title = f"{heading} overview"
            preamble_filename = note_filename(preamble_title)

            # Check for empty filename (must have content before the .md extension)
            if not preamble_filename.removesuffix(".md"):
                raise ValueError(f"Title '{preamble_title}' sanitizes to an empty filename")

            # Check for collision
            if preamble_filename in written_filenames:
                raise ValueError(
                    f"Filename collision in {folder}: '{preamble_title}' and "
                    f"'{written_filenames[preamble_filename]}' both map to '{preamble_filename}'"
                )

            written_filenames[preamble_filename] = preamble_title
            (vault / folder / preamble_filename).write_text(
                render_note(preamble_title, [tag, "proposal-research"], linkify_citations(preamble)),
                encoding="utf-8",
            )
            titles.append(preamble_title)

        # Write subsection notes
        for title, body in subsections:
            filename = note_filename(title)

            # Check for empty filename (must have content before the .md extension)
            if not filename.removesuffix(".md"):
                raise ValueError(f"Title '{title}' sanitizes to an empty filename")

            # Check for collision
            if filename in written_filenames:
                raise ValueError(
                    f"Filename collision in {folder}: '{title}' and "
                    f"'{written_filenames[filename]}' both map to '{filename}'"
                )

            written_filenames[filename] = title
            (vault / folder / filename).write_text(
                render_note(title, [tag, "proposal-research"], linkify_citations(body)),
                encoding="utf-8",
            )
            titles.append(title)

        linked_titles[heading] = titles

    # 00-MOC
    (vault / "00-MOC" / "Decision Cheatsheet.md").write_text(
        render_note("Decision Cheatsheet", ["moc", "recommendation", "proposal-research"],
                    linkify_citations(sections["Recommendation"])),
        encoding="utf-8",
    )
    (vault / "00-MOC" / "Proposal Brief.md").write_text(
        _render_brief(sections, linked_titles, claims, include_proposal),
        encoding="utf-8",
    )

    # 04-Risks-and-Gaps
    (vault / "04-Risks-and-Gaps" / "Open Questions.md").write_text(
        render_note("Open Questions", ["gap", "proposal-research"],
                    linkify_citations(sections.get("Open Questions", "_None recorded._"))),
        encoding="utf-8",
    )
    (vault / "04-Risks-and-Gaps" / "Unverified Claims.md").write_text(
        render_note("Unverified Claims", ["unverified", "proposal-research"],
                    linkify_citations(sections.get("Unverified & excluded", "_Nothing was excluded._"))),
        encoding="utf-8",
    )

    # 06-Sources
    verdicts: dict[str, list[dict]] = {}
    for row in read_jsonl(workspace / "verdicts.jsonl"):
        claim_id = row.get("claim_id")
        if claim_id:
            verdicts.setdefault(claim_id, []).append(row)
    fetches = read_jsonl(workspace / "fetch-log.jsonl")
    gaps_path = workspace / "gaps.md"
    gaps = gaps_path.read_text(encoding="utf-8") if gaps_path.is_file() else ""

    (vault / "06-Sources" / "Sources.md").write_text(
        render_note("Sources", ["sources", "proposal-research"],
                    render_sources(claims, verdicts)),
        encoding="utf-8",
    )
    (vault / "06-Sources" / "Research Log.md").write_text(
        render_note("Research Log", ["log", "proposal-research"],
                    render_research_log(claims, verdicts, fetches, gaps)),
        encoding="utf-8",
    )
    write_ledger_export(vault, claims, verdicts)

    if include_proposal:
        proposal_path = workspace / "proposal.md"
        if not proposal_path.is_file():
            raise FileNotFoundError(
                f"include_proposal was requested but {proposal_path} does not exist; "
                f"run the proposal-writer phase first"
            )
        (vault / "05-Proposal" / "Draft Proposal.md").write_text(
            render_note("Draft Proposal", ["proposal", "proposal-research"],
                        linkify_citations(proposal_path.read_text(encoding="utf-8"))),
            encoding="utf-8",
        )

    return vault


def _render_brief(sections: dict, linked_titles: dict, claims: dict,
                  include_proposal: bool) -> str:
    lines = [linkify_citations(sections["Summary"]), "", "## Contents", ""]
    lines.append("- [[Decision Cheatsheet]]")
    for heading, (_folder, _tag) in SECTION_MAP.items():
        for title in linked_titles.get(heading, []):
            lines.append(f"- {wikilink(title)}")
    lines += [
        "- [[Open Questions]]",
        "- [[Unverified Claims]]",
        "- [[Sources]]",
        "- [[Research Log]]",
    ]
    if include_proposal:
        lines.append("- [[Draft Proposal]]")
    lines += ["", "## Quick facts", "", "| Item | Value |", "|---|---|",
              f"| Claims in ledger | {len(claims)} |"]
    return render_note("Proposal Brief", ["moc", "proposal-research"], "\n".join(lines))


SOURCE_GROUPS = [
    ("vendor_doc", "Vendor documentation"),
    ("regulator", "Regulator and official guidance"),
    ("analyst", "Analyst and research firms"),
    ("blog", "Blogs and articles"),
    ("forum", "Forums and community"),
    ("internal", "Internal notes (unverified)"),
]


def _sorted_rulings(rulings: list[dict]) -> list[dict]:
    """Stable per-claim ordering, independent of validator dispatch order.

    Validator agents are dispatched independently, so the append order of rows
    in verdicts.jsonl is not stable across two logically identical runs.
    Sorting on (ruled_at, validator_agent_id) gives deterministic output.
    """
    return sorted(rulings, key=lambda r: (r.get("ruled_at") or "", r.get("validator_agent_id") or ""))


def render_sources(claims: dict, verdicts: dict) -> str:
    lines: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for claim in claims.values():
        grouped.setdefault(claim.get("source_type", "unknown"), []).append(claim)

    for source_type, label in SOURCE_GROUPS:
        rows = sorted(grouped.get(source_type, []), key=lambda c: c["id"])
        if not rows:
            continue
        lines += [f"## {label}", ""]
        for claim in rows:
            rulings = _sorted_rulings(verdicts.get(claim["id"], []))
            verdict_summary = ", ".join(r.get("verdict", "?") for r in rulings) or "no verdict"
            lines += [
                f"### {claim['id']}",
                "",
                f"**Claim.** {claim.get('claim', '')}",
                "",
                f"**Source.** {claim.get('url') or '_internal note, no URL_'}",
                "",
                f"> {claim.get('quote', '')}",
                "",
                f"*Verdict:* {verdict_summary} · *Retrieved:* {claim.get('fetched_at', 'unknown')}",
                "",
            ]

    lines += render_reliability_notes(claims, verdicts).splitlines()
    return "\n".join(lines)


def render_reliability_notes(claims: dict, verdicts: dict) -> str:
    """Derived from the verdicts, not noticed by hand.

    The pipeline had to record each disagreement in order to rule on a claim, so
    the conflicts fall out for free.
    """
    lines = ["## Notes on source reliability", ""]
    entries: list[str] = []

    for claim_id, rulings in sorted(verdicts.items()):
        claim = claims.get(claim_id)
        if claim is None:
            continue
        rulings = _sorted_rulings(rulings)
        seen = {r.get("verdict") for r in rulings}
        url = claim.get("url") or "internal note"

        if "CONTRADICTED" in seen:
            entries.append(
                f"- **{claim_id} — contradicted.** The cited page does not support this "
                f"claim: {url}. Excluded from the pack body."
            )
        for ruling in rulings:
            if ruling.get("verdict") == "MISLEADING" and ruling.get("caveat"):
                entries.append(
                    f"- **{claim_id} — misleading without its caveat.** {ruling['caveat']} "
                    f"Source: {url}"
                )
        if len(seen) > 1:
            entries.append(
                f"- **{claim_id} — validators disagree.** Rulings were "
                f"{', '.join(sorted(v for v in seen if v))}. Treat with care and re-check "
                f"before quoting to a client."
            )

    if entries:
        lines += entries
    else:
        lines.append("- No contradictions, caveats, or validator disagreements were recorded.")
    lines.append("")
    return "\n".join(lines)


def render_research_log(claims: dict, verdicts: dict, fetches: list, gaps: str) -> str:
    verdict_counts: dict[str, int] = {}
    for rulings in verdicts.values():
        for ruling in rulings:
            key = ruling.get("verdict", "unknown")
            verdict_counts[key] = verdict_counts.get(key, 0) + 1

    agents = {f.get("agent_id") for f in fetches if f.get("agent_id")}

    lines = [
        "## Totals",
        "",
        f"- Claims in ledger: {len(claims)}",
        f"- Fetches recorded: {len(fetches)}",
        f"- Distinct agents that fetched: {len(agents)}",
        "",
        "## Verdicts",
        "",
    ]
    lines += [f"- {k}: {v}" for k, v in sorted(verdict_counts.items())] or ["- none"]
    lines += ["", "## Gap rounds", "", gaps.strip() or "_No gap rounds recorded._", ""]
    return "\n".join(lines)


def write_ledger_export(vault: Path, claims: dict, verdicts: dict) -> Path:
    """Self-sufficient export so a copied-out vault can seed a future run."""
    path = vault / "06-Sources" / "ledger-export.jsonl"
    path.write_text(
        "".join(
            json.dumps({**claim, "verdicts": verdicts.get(claim_id, [])}, ensure_ascii=False) + "\n"
            for claim_id, claim in sorted(claims.items())
        ),
        encoding="utf-8",
    )
    return path


# --- citation links -------------------------------------------------------

CITATION_RE = re.compile(r"\[(C\d{3,})\](?!\()")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
ANCHOR_RE = re.compile(r"^### (C\d{3,})$", re.MULTILINE)


def linkify_citations(body: str, depth: int = 1) -> str:
    """Turn [C001] into a relative link to its Sources.md anchor.

    The bracketed id is preserved as the link text so the gate's citation regex
    still matches vault notes.
    """
    prefix = "../" * depth
    return CITATION_RE.sub(
        lambda m: f"[{m.group(1)}]({prefix}06-Sources/Sources.md#{m.group(1)})",
        body or "",
    )


def check_links(vault: Path) -> list[str]:
    """Unresolved wikilinks and citations with no anchor in Sources.md.

    Read-only: inspects an already-built vault, never modifies it.
    """
    vault = Path(vault)
    notes = [p for p in vault.rglob("*.md") if ".obsidian" not in p.parts]
    titles = {p.stem for p in notes}

    sources = vault / "06-Sources" / "Sources.md"
    anchors = set(ANCHOR_RE.findall(sources.read_text(encoding="utf-8"))) if sources.is_file() else set()

    problems: list[str] = []
    for note in sorted(notes):
        text = note.read_text(encoding="utf-8")
        rel = note.relative_to(vault)
        for target in WIKILINK_RE.findall(text):
            if target.strip() not in titles:
                problems.append(f"{rel}: unresolved wikilink [[{target.strip()}]]")
        for claim_id in re.findall(r"\[(C\d{3,})\]", text):
            if claim_id not in anchors:
                problems.append(f"{rel}: citation [{claim_id}] has no anchor in Sources.md")
    return problems


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build the Obsidian vault for a research run")
    parser.add_argument("--workspace", required=True, help="research/<slug> directory")
    parser.add_argument("--with-proposal", action="store_true",
                        help="include 05-Proposal/Draft Proposal.md (phase 7b)")
    parser.add_argument("--check-only", action="store_true",
                        help="verify links in an already-built vault without rebuilding")
    parser.add_argument("--copy-to", default=None, help="also copy the finished vault here")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace)

    if args.check_only:
        problems = check_links(workspace / "vault")
    else:
        vault = build(workspace, include_proposal=args.with_proposal)
        problems = check_links(vault)

    if problems:
        for problem in problems:
            print(f"BROKEN LINK: {problem}", file=sys.stderr)
        print(f"VAULT: FAIL — {len(problems)} broken link(s)", file=sys.stderr)
        return 1

    vault = workspace / "vault"
    if args.copy_to:
        destination = Path(args.copy_to)
        dest_resolved = destination.resolve()
        vault_resolved = vault.resolve()
        if dest_resolved == vault_resolved:
            print(
                f"VAULT: FAIL — --copy-to ({destination}) must not point at the source vault "
                f"itself ({vault}). Nothing was deleted.",
                file=sys.stderr,
            )
            return 1
        if dest_resolved in vault_resolved.parents:
            print(
                f"VAULT: FAIL — --copy-to ({destination}) is an ancestor of the source vault "
                f"({vault}); deleting it would destroy the vault and the rest of the workspace. "
                f"Nothing was deleted.",
                file=sys.stderr,
            )
            return 1
        if vault_resolved in dest_resolved.parents:
            print(
                f"VAULT: FAIL — --copy-to ({destination}) is inside the source vault ({vault}); "
                f"copying a tree into itself is not meaningful. Nothing was deleted.",
                file=sys.stderr,
            )
            return 1
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(vault, destination)
        print(f"Copied vault to {destination}")

    print(f"VAULT: OK — {vault}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
