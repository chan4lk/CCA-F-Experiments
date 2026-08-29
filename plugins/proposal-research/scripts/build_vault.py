#!/usr/bin/env python3
"""Phase 5b/7b — file the evidence pack into a self-contained Obsidian vault.

Deterministic on purpose. Fable writes the prose; this script does the filing,
wikilinking and anchor generation. A model that files its own citations can
misfile them, and that would put a hole in the provenance guarantee at the very
last step.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from workspace import read_jsonl  # noqa: E402

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
    in_fence = False
    for line in (text or "").splitlines():
        # Track fence state
        if line.strip().startswith("```"):
            in_fence = not in_fence

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
    in_fence = False

    for line in (text or "").splitlines():
        # Track fence state
        if line.strip().startswith("```"):
            in_fence = not in_fence

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
    """Check if a note has the 'generated: true' marker in frontmatter."""
    try:
        content = note_path.read_text(encoding="utf-8")
        if content.startswith("---"):
            lines = content.split("\n")
            for line in lines[1:]:
                if line.startswith("---"):
                    # End of frontmatter
                    break
                if line.strip() == "generated: true":
                    return True
        return False
    except Exception:
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

            # Check for empty filename
            if not preamble_filename.rstrip(".md"):
                raise ValueError(f"Title '{preamble_title}' sanitizes to an empty filename")

            # Check for collision
            if preamble_filename in written_filenames:
                raise ValueError(
                    f"Filename collision in {folder}: '{preamble_title}' and "
                    f"'{written_filenames[preamble_filename]}' both map to '{preamble_filename}'"
                )

            written_filenames[preamble_filename] = preamble_title
            (vault / folder / preamble_filename).write_text(
                render_note(preamble_title, [tag, "proposal-research"], preamble),
                encoding="utf-8",
            )
            titles.append(preamble_title)

        # Write subsection notes
        for title, body in subsections:
            filename = note_filename(title)

            # Check for empty filename
            if not filename.rstrip(".md"):
                raise ValueError(f"Title '{title}' sanitizes to an empty filename")

            # Check for collision
            if filename in written_filenames:
                raise ValueError(
                    f"Filename collision in {folder}: '{title}' and "
                    f"'{written_filenames[filename]}' both map to '{filename}'"
                )

            written_filenames[filename] = title
            (vault / folder / filename).write_text(
                render_note(title, [tag, "proposal-research"], body),
                encoding="utf-8",
            )
            titles.append(title)

        linked_titles[heading] = titles

    # 00-MOC
    (vault / "00-MOC" / "Decision Cheatsheet.md").write_text(
        render_note("Decision Cheatsheet", ["moc", "recommendation", "proposal-research"],
                    sections["Recommendation"]),
        encoding="utf-8",
    )
    (vault / "00-MOC" / "Proposal Brief.md").write_text(
        _render_brief(sections, linked_titles, claims, include_proposal),
        encoding="utf-8",
    )

    # 04-Risks-and-Gaps
    (vault / "04-Risks-and-Gaps" / "Open Questions.md").write_text(
        render_note("Open Questions", ["gap", "proposal-research"],
                    sections.get("Open Questions", "_None recorded._")),
        encoding="utf-8",
    )
    (vault / "04-Risks-and-Gaps" / "Unverified Claims.md").write_text(
        render_note("Unverified Claims", ["unverified", "proposal-research"],
                    sections.get("Unverified & excluded", "_Nothing was excluded._")),
        encoding="utf-8",
    )

    return vault


def _render_brief(sections: dict, linked_titles: dict, claims: dict,
                  include_proposal: bool) -> str:
    lines = [sections["Summary"], "", "## Contents", ""]
    lines.append("- [[Decision Cheatsheet]]")
    for heading, (_folder, _tag) in SECTION_MAP.items():
        for title in linked_titles.get(heading, []):
            lines.append(f"- [[{title}]]")
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
