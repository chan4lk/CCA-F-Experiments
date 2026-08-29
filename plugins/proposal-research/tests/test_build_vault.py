import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_vault  # noqa: E402
from fixtures import build as fx  # noqa: E402

FULL_PACK = """# Evidence Pack: ServiceNow Agent Platform

## Summary

Two candidate architectures were assessed against the client's Microsoft estate [C001].

## Recommendation

Copilot Studio with an MCP server is the stronger fit given the tool cap [C001].

## Findings

### MCP tool limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

### Native agent positioning

ServiceNow positions AI Agent Studio for platform-native agents [C002].

## Options

### Copilot Studio with MCP

Strong Microsoft alignment [C001].

### ServiceNow native AI Agent Studio

Platform-native but a separate licence [C002].

## Constraints

### Licensing

Tool caps constrain the design [C001].

## Open Questions

- Regional GA status for the MCP connector

## Unverified & excluded

Nothing was excluded in this run.
"""


def make_ws(tmp_path, pack=FULL_PACK):
    return fx.make_workspace(tmp_path, pack=pack)


# --- parsing ------------------------------------------------------------

def test_parse_sections_finds_every_h2():
    sections = build_vault.parse_sections(FULL_PACK)
    assert set(sections) >= {
        "Summary", "Recommendation", "Findings", "Options",
        "Constraints", "Open Questions", "Unverified & excluded",
    }


def test_parse_sections_captures_body_text():
    assert "[C001]" in build_vault.parse_sections(FULL_PACK)["Summary"]


def test_split_subsections_splits_on_h3():
    findings = build_vault.parse_sections(FULL_PACK)["Findings"]
    preamble, subs = build_vault.split_subsections(findings)
    assert [t for t, _ in subs] == ["MCP tool limits", "Native agent positioning"]


def test_split_subsections_with_no_h3_returns_empty():
    preamble, subs = build_vault.split_subsections("Just prose, no headings.\n")
    assert subs == []


def test_split_subsections_preserves_preamble():
    text = """General intro about findings.

### Finding 1

Body of finding 1.

### Finding 2

Body of finding 2."""
    preamble, subs = build_vault.split_subsections(text)
    assert "General intro about findings" in preamble
    assert len(subs) == 2
    assert [t for t, _ in subs] == ["Finding 1", "Finding 2"]


def test_note_filename_is_filesystem_safe():
    assert build_vault.note_filename("MCP tool limits") == "MCP tool limits.md"
    assert "/" not in build_vault.note_filename("A/B: limits?")


def test_render_note_emits_frontmatter_and_title():
    out = build_vault.render_note("My Note", ["finding", "proposal-research"], "Body [C001].")
    assert out.startswith("---\n")
    assert "tags: [finding, proposal-research]" in out
    assert "generated: true" in out
    assert "# My Note" in out
    assert "Body [C001]." in out


def test_render_note_marks_generated_by_default():
    out = build_vault.render_note("Note", [], "Body")
    assert "generated: true" in out


def test_render_note_respects_generated_false():
    out = build_vault.render_note("Note", [], "Body", generated=False)
    assert "generated: true" not in out


# --- build --------------------------------------------------------------

def test_build_creates_the_folder_skeleton(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    for name in build_vault.VAULT_DIRS:
        assert (vault / name).is_dir(), name


def test_build_copies_obsidian_config(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / ".obsidian" / "core-plugins.json").is_file()
    assert (vault / ".obsidian" / "graph.json").is_file()


def test_build_writes_proposal_brief_with_wikilinks(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    brief = (vault / "00-MOC" / "Proposal Brief.md").read_text()
    assert "[[MCP tool limits]]" in brief
    assert "[[Sources]]" in brief


def test_build_writes_decision_cheatsheet(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "00-MOC" / "Decision Cheatsheet.md").read_text()
    assert "Copilot Studio with an MCP server" in text


def test_build_writes_one_note_per_finding(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    names = sorted(p.name for p in (vault / "01-Findings").glob("*.md"))
    assert names == ["MCP tool limits.md", "Native agent positioning.md"]


def test_finding_notes_carry_their_citations(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "[C001]" in (vault / "01-Findings" / "MCP tool limits.md").read_text()


def test_build_is_idempotent(tmp_path):
    ws = make_ws(tmp_path)
    build_vault.build(ws)
    vault = build_vault.build(ws)
    assert len(list((vault / "01-Findings").glob("*.md"))) == 2


def test_build_rejects_a_pack_missing_required_sections(tmp_path):
    ws = make_ws(tmp_path, pack="# Evidence Pack\n\n## Summary\n\nOnly a summary.\n")
    try:
        build_vault.build(ws)
    except ValueError as exc:
        assert "Findings" in str(exc)
    else:
        raise AssertionError("expected ValueError for incomplete pack")


# --- Finding 1: Filename collisions ---

def test_build_raises_on_filename_collision(tmp_path):
    """FINDING 1: Colliding sanitized titles must raise, not silently overwrite."""
    pack = """# Evidence Pack

## Summary

Test.

## Recommendation

Test.

## Findings

### A/B: limits

First finding.

### A:B/ limits

Second finding (same sanitized filename as first).

## Options

### Option

Test.

## Constraints

### Constraint

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    ws = make_ws(tmp_path, pack=pack)
    try:
        build_vault.build(ws)
    except ValueError as exc:
        exc_str = str(exc)
        assert "collision" in exc_str.lower()
        assert "01-Findings" in exc_str or "Findings" in exc_str
    else:
        raise AssertionError("expected ValueError for filename collision")


def test_build_raises_when_preamble_conflicts_with_h3_title(tmp_path):
    """FINDING 1: Preamble creates 'Findings overview' which must not collide."""
    # If we have a preamble AND an H3 titled "Findings overview", that's a collision
    pack = """# Evidence Pack

## Summary

Test.

## Recommendation

Test.

## Findings

General intro that becomes Findings overview.

### Findings overview

But we also have an H3 with the same name!

## Options

### Option

Test.

## Constraints

### Constraint

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    ws = make_ws(tmp_path, pack=pack)
    try:
        build_vault.build(ws)
    except ValueError as exc:
        exc_str = str(exc)
        assert "collision" in exc_str.lower()
    else:
        raise AssertionError("expected ValueError for preamble/H3 collision")


# --- Finding 2: Code fence tracking ---

def test_parse_sections_ignores_h2_in_code_fence():
    """FINDING 2: H2 headings inside code fences must not create sections."""
    pack = """# Evidence Pack

## Summary

This section has a code fence:
```python
## This is not a heading
## Neither is this
```

Real summary text after fence.

## Recommendation

Test.

## Findings

### Finding

Test.

## Options

### Option

Test.

## Constraints

### Constraint

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    sections = build_vault.parse_sections(pack)
    assert "This is not a heading" not in sections
    assert "Neither is this" not in sections
    assert "Summary" in sections
    assert "```python" in sections["Summary"]
    assert "Real summary text after fence" in sections["Summary"]


def test_split_subsections_ignores_h3_in_code_fence():
    """FINDING 2: H3 headings inside code fences must not create subsections."""
    text = """Intro text with a fence:
```
### fake heading in fence
```
More text after fence.

### Real heading

Real body."""
    preamble, subs = build_vault.split_subsections(text)
    assert len(subs) == 1
    assert subs[0][0] == "Real heading"
    assert "### fake heading in fence" in preamble


# --- Finding 3: Preamble preservation ---

def test_build_writes_preamble_as_overview_note(tmp_path):
    """FINDING 3: Section preamble must be preserved as a <Section> overview note."""
    pack = """# Evidence Pack

## Summary

Summary text.

## Recommendation

Recommendation text.

## Findings

General intro about findings. This paragraph should be preserved.

### Finding 1

Body of finding 1.

### Finding 2

Body of finding 2.

## Options

### Option 1

Test.

## Constraints

### Constraint 1

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    ws = make_ws(tmp_path, pack=pack)
    vault = build_vault.build(ws)

    # Check that Findings overview note exists
    overview_path = vault / "01-Findings" / "Findings overview.md"
    assert overview_path.is_file()
    overview_text = overview_path.read_text()
    assert "General intro about findings" in overview_text

    # Check that the brief links to the overview
    brief = (vault / "00-MOC" / "Proposal Brief.md").read_text()
    assert "[[Findings overview]]" in brief


# --- Finding 4: User-authored notes survive ---

def test_build_preserves_user_authored_notes(tmp_path):
    """FINDING 4: Notes without 'generated: true' must survive rebuilds."""
    ws = make_ws(tmp_path)

    # First build
    vault = build_vault.build(ws)

    # User adds a note to the vault (without the generated marker)
    user_note_path = vault / "01-Findings" / "My Custom Finding.md"
    user_note_path.write_text(
        "---\ntags: [custom]\n---\n\n# My Custom Finding\n\nThis is a user note.\n",
        encoding="utf-8"
    )

    # Second build
    vault = build_vault.build(ws)

    # User note should still exist
    assert user_note_path.is_file()
    assert "This is a user note" in user_note_path.read_text()

    # Generated notes should still be there too
    assert (vault / "01-Findings" / "MCP tool limits.md").is_file()


def test_generated_notes_are_marked(tmp_path):
    """Generated notes must have the 'generated: true' marker."""
    vault = build_vault.build(make_ws(tmp_path))
    finding_note = (vault / "01-Findings" / "MCP tool limits.md").read_text()
    assert "generated: true" in finding_note


# --- Round 2 fixes ---

def test_unterminated_frontmatter_with_generated_marker_survives(tmp_path):
    """ISSUE 1 (Round 2): A note with unterminated --- and 'generated: true' in body must survive.

    If a user note starts with --- (as a horizontal rule) and contains the text
    'generated: true' anywhere in the body (not in frontmatter), it should NOT be
    deleted because it doesn't have proper frontmatter structure.
    """
    ws = make_ws(tmp_path)

    # First build
    vault = build_vault.build(ws)

    # User adds a note with unterminated --- and 'generated: true' in the body
    # This is NOT a generated note; it's a user note that happens to contain that text
    malformed_note_path = vault / "01-Findings" / "User Notes.md"
    malformed_note_path.write_text(
        "---\nThis is a horizontal rule separator.\n\ngenerated: true\n\nBut there's no closing --- so it's not real frontmatter!\n",
        encoding="utf-8"
    )

    # Second build
    vault = build_vault.build(ws)

    # The malformed note should survive because the frontmatter is unterminated
    assert malformed_note_path.is_file()
    assert "This is a horizontal rule separator" in malformed_note_path.read_text()


def test_title_d_builds_successfully(tmp_path):
    """ISSUE 2 (Round 2): A title of 'd' should be accepted, not rejected as empty.

    The original code used rstrip(".md") which is a character set, not a suffix.
    This caused "d.md".rstrip(".md") to return "" incorrectly. The fix uses
    removesuffix(".md") which properly removes only the suffix.
    """
    # Test the filename generation directly
    filename = build_vault.note_filename("d")
    assert filename == "d.md"
    assert filename.removesuffix(".md") == "d"  # Proper suffix removal

    # Test a pack with a title of "d"
    pack = """# Evidence Pack

## Summary

Test.

## Recommendation

Test.

## Findings

### d

Single letter title 'd' should be accepted.

## Options

### Option

Test.

## Constraints

### Constraint

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    ws = make_ws(tmp_path, pack=pack)
    vault = build_vault.build(ws)

    # The note should be created successfully
    note_path = vault / "01-Findings" / "d.md"
    assert note_path.is_file()
    assert "Single letter title" in note_path.read_text()


def test_title_md_builds_successfully(tmp_path):
    """Test that 'md' is also accepted as a valid title."""
    filename = build_vault.note_filename("md")
    assert filename == "md.md"
    assert filename.removesuffix(".md") == "md"  # Proper suffix removal

    pack = """# Evidence Pack

## Summary

Test.

## Recommendation

Test.

## Findings

### md

Markdown file format abbreviation should be accepted.

## Options

### Option

Test.

## Constraints

### Constraint

Test.

## Open Questions

None.

## Unverified & excluded

None.
"""
    ws = make_ws(tmp_path, pack=pack)
    vault = build_vault.build(ws)

    note_path = vault / "01-Findings" / "md.md"
    assert note_path.is_file()
    assert "Markdown file format" in note_path.read_text()
