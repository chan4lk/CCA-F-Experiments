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
    subs = build_vault.split_subsections(findings)
    assert [t for t, _ in subs] == ["MCP tool limits", "Native agent positioning"]


def test_split_subsections_with_no_h3_returns_empty():
    assert build_vault.split_subsections("Just prose, no headings.\n") == []


def test_note_filename_is_filesystem_safe():
    assert build_vault.note_filename("MCP tool limits") == "MCP tool limits.md"
    assert "/" not in build_vault.note_filename("A/B: limits?")


def test_render_note_emits_frontmatter_and_title():
    out = build_vault.render_note("My Note", ["finding", "proposal-research"], "Body [C001].")
    assert out.startswith("---\n")
    assert "tags: [finding, proposal-research]" in out
    assert "# My Note" in out
    assert "Body [C001]." in out


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
