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


import json  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ingest_context  # noqa: E402


# --- Sources.md ---------------------------------------------------------

def test_sources_note_is_written(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / "06-Sources" / "Sources.md").is_file()


def test_sources_groups_by_source_type(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert "## Vendor documentation" in text


def test_sources_has_an_anchor_per_claim(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert "### C001" in text
    assert "### C002" in text


def test_sources_shows_url_and_quote(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Sources.md").read_text()
    assert fx.URL_A in text
    assert "A maximum of 10 tools" in text


# --- reliability notes --------------------------------------------------

def test_reliability_section_is_present_even_when_clean(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "Notes on source reliability" in (vault / "06-Sources" / "Sources.md").read_text()


def test_contradicted_claim_appears_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[2].update(verdict="CONTRADICTED")
    verdicts[2].pop("quote", None)
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    assert "C002" in text.split("Notes on source reliability")[1]


def test_misleading_caveat_appears_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    assert "Public preview only, not GA." in text


def test_disagreeing_validators_appear_in_reliability_notes(tmp_path):
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    verdicts[1].update(verdict="MISLEADING", caveat="Preview in some regions.")
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)
    text = (build_vault.build(ws) / "06-Sources" / "Sources.md").read_text()
    section = text.split("Notes on source reliability")[1]
    assert "C001" in section and "disagree" in section.lower()


# --- Research Log -------------------------------------------------------

def test_research_log_reports_verdict_counts(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "06-Sources" / "Research Log.md").read_text()
    assert "CONFIRMED" in text and "3" in text


def test_research_log_reports_fetch_total(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert "Fetches recorded" in (vault / "06-Sources" / "Research Log.md").read_text()


# --- ledger export ------------------------------------------------------

def test_ledger_export_is_written(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert (vault / "06-Sources" / "ledger-export.jsonl").is_file()


def test_ledger_export_merges_verdicts_into_claim_rows(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    rows = [json.loads(l) for l in
            (vault / "06-Sources" / "ledger-export.jsonl").read_text().splitlines() if l.strip()]
    by_id = {r["id"]: r for r in rows}
    assert len(by_id["C001"]["verdicts"]) == 2


def test_exported_vault_round_trips_as_a_lane_one_source(tmp_path):
    """A copied-out vault must be ingestable by a future run."""
    vault = build_vault.build(make_ws(tmp_path))
    rows = ingest_context.load_prior_ledger(vault)
    assert {r["id"] for r in rows} == {"C001", "C002"}
    from datetime import datetime, timezone
    carried = ingest_context.carry_forward(rows, datetime.now(timezone.utc))
    assert [c["origin"]["claim_id"] for c in carried] == ["C001", "C002"]


# --- Review fixes: verdict rows missing claim_id, deterministic verdict order ---

def test_verdict_row_with_no_claim_id_does_not_crash_the_build(tmp_path):
    """FINDING 1 (review): a malformed verdicts.jsonl row must not take down the build."""
    verdicts = [dict(v) for v in fx.VERDICTS_OK]
    orphan = {"verdict": "CONFIRMED", "validator_agent_id": "orphan-validator",
              "validator_model": "haiku", "quote": "Orphan quote, no claim_id.",
              "ruled_at": "2026-08-29T09:53:00Z"}
    verdicts.append(orphan)
    ws = fx.make_workspace(tmp_path, verdicts=verdicts, pack=FULL_PACK)

    vault = build_vault.build(ws)  # must not raise

    sources_text = (vault / "06-Sources" / "Sources.md").read_text()
    log_text = (vault / "06-Sources" / "Research Log.md").read_text()
    export_text = (vault / "06-Sources" / "ledger-export.jsonl").read_text()
    assert "orphan-validator" not in sources_text
    assert "orphan-validator" not in log_text
    assert "orphan-validator" not in export_text


def test_verdict_order_in_sources_is_deterministic_regardless_of_input_order(tmp_path):
    """FINDING 2 (review): verdict display order must not depend on validator dispatch order."""
    v_a = {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
           "validator_model": "haiku",
           "quote": "A maximum of 10 tools per MCP server connection is supported.",
           "ruled_at": "2026-08-29T09:50:00Z"}
    v_b = {"claim_id": "C001", "verdict": "MISLEADING", "validator_agent_id": "val-s1",
           "validator_model": "sonnet",
           "quote": "A maximum of 10 tools per MCP server connection is supported.",
           "caveat": "Only true for the default connector.",
           "ruled_at": "2026-08-29T09:51:00Z"}
    v_c002 = dict(fx.VERDICTS_OK[2])

    forward = [v_a, v_b, v_c002]
    reversed_order = [v_b, v_a, v_c002]

    ws_forward = fx.make_workspace(tmp_path / "forward", verdicts=forward, pack=FULL_PACK)
    ws_reversed = fx.make_workspace(tmp_path / "reversed", verdicts=reversed_order, pack=FULL_PACK)

    text_forward = (build_vault.build(ws_forward) / "06-Sources" / "Sources.md").read_text()
    text_reversed = (build_vault.build(ws_reversed) / "06-Sources" / "Sources.md").read_text()

    assert text_forward == text_reversed
    assert "CONFIRMED, MISLEADING" in text_forward


# --- citation links -----------------------------------------------------

def test_linkify_turns_citations_into_relative_links():
    out = build_vault.linkify_citations("A claim [C001].", depth=1)
    assert out == "A claim [C001](../06-Sources/Sources.md#C001)."


def test_linkify_preserves_the_bracketed_id_for_the_gate():
    assert "[C001]" in build_vault.linkify_citations("x [C001]", depth=1)


def test_linkify_handles_multiple_citations():
    out = build_vault.linkify_citations("[C001] and [C002]", depth=1)
    assert out.count("06-Sources/Sources.md#") == 2


def test_linkify_at_depth_zero_uses_local_path():
    assert "(06-Sources/Sources.md#C001)" in build_vault.linkify_citations("[C001]", depth=0)


def test_linkify_does_not_double_link(tmp_path):
    once = build_vault.linkify_citations("[C001]", depth=1)
    assert build_vault.linkify_citations(once, depth=1) == once


def test_finding_notes_have_linked_citations(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    text = (vault / "01-Findings" / "MCP tool limits.md").read_text()
    assert "../06-Sources/Sources.md#C001" in text


# --- link integrity -----------------------------------------------------

def test_clean_vault_has_no_broken_links(tmp_path):
    assert build_vault.check_links(build_vault.build(make_ws(tmp_path))) == []


def test_broken_wikilink_is_reported(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    (vault / "01-Findings" / "MCP tool limits.md").write_text("# X\n\nSee [[Nonexistent Note]].\n")
    problems = build_vault.check_links(vault)
    assert any("Nonexistent Note" in p for p in problems)


def test_citation_without_a_sources_anchor_is_reported(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    (vault / "01-Findings" / "MCP tool limits.md").write_text("# X\n\nOrphan [C999].\n")
    assert any("C999" in p for p in build_vault.check_links(vault))


# --- unsafe titles ------------------------------------------------------

def test_wikilink_uses_the_raw_title_when_it_is_already_safe():
    assert build_vault.wikilink("MCP tool limits") == "[[MCP tool limits]]"


def test_wikilink_targets_the_sanitised_filename_and_shows_the_original():
    assert build_vault.wikilink("Licensing: seat costs") == \
        "[[Licensing- seat costs|Licensing: seat costs]]"


def test_an_h3_title_with_a_colon_builds_and_links(tmp_path):
    """I4: note_filename rewrites `:` but the brief linked the RAW title.

    `### Licensing: seat costs` produced
    `BROKEN LINK: 00-MOC/Proposal Brief.md: unresolved wikilink
    [[Licensing: seat costs]]`, VAULT: FAIL, exit 1 — on the most common
    punctuation an LLM will put in a section heading.
    """
    pack = FULL_PACK.replace("### Licensing", "### Licensing: seat costs")
    ws = make_ws(tmp_path, pack=pack)
    vault = build_vault.build(ws)
    assert (vault / "03-Constraints" / "Licensing- seat costs.md").is_file()
    assert build_vault.check_links(vault) == []
    brief = (vault / "00-MOC" / "Proposal Brief.md").read_text()
    assert "[[Licensing- seat costs|Licensing: seat costs]]" in brief


def test_every_unsafe_character_in_a_title_builds_and_links(tmp_path):
    pack = FULL_PACK.replace("### Licensing", '### A/B\\C:D*E?F"G<H>I|J')
    vault = build_vault.build(make_ws(tmp_path, pack=pack))
    assert build_vault.check_links(vault) == []


def test_main_exits_zero_for_an_unsafe_title(tmp_path):
    """End to end through the CLI, which is where I4 was reproduced."""
    pack = FULL_PACK.replace("### Licensing", "### Licensing: seat costs")
    ws = make_ws(tmp_path, pack=pack)
    assert build_vault.main(["--workspace", str(ws)]) == 0


# --- proposal phase -----------------------------------------------------

def test_proposal_note_is_absent_by_default(tmp_path):
    vault = build_vault.build(make_ws(tmp_path))
    assert not (vault / "05-Proposal" / "Draft Proposal.md").exists()


def test_proposal_note_is_written_when_requested(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "proposal.md").write_text("# Proposal\n\nWe recommend Copilot Studio [C001].\n")
    vault = build_vault.build(ws, include_proposal=True)
    text = (vault / "05-Proposal" / "Draft Proposal.md").read_text()
    assert "We recommend Copilot Studio" in text
    assert "../06-Sources/Sources.md#C001" in text


def test_brief_links_the_proposal_when_present(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "proposal.md").write_text("# Proposal\n\nText [C001].\n")
    vault = build_vault.build(ws, include_proposal=True)
    assert "[[Draft Proposal]]" in (vault / "00-MOC" / "Proposal Brief.md").read_text()


def test_include_proposal_without_the_file_raises(tmp_path):
    try:
        build_vault.build(make_ws(tmp_path), include_proposal=True)
    except FileNotFoundError as exc:
        assert "proposal.md" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


# --- CLI ----------------------------------------------------------------

def test_main_builds_and_reports_success(tmp_path, capsys):
    ws = make_ws(tmp_path)
    assert build_vault.main(["--workspace", str(ws)]) == 0
    assert "vault" in capsys.readouterr().out


def test_main_fails_on_broken_links(tmp_path):
    ws = make_ws(tmp_path)
    build_vault.build(ws)
    (ws / "vault" / "01-Findings" / "MCP tool limits.md").write_text("# X\n\n[[Ghost]]\n")
    # rebuild would overwrite, so verify check_links directly drives the exit code
    assert build_vault.main(["--workspace", str(ws), "--check-only"]) == 1


def test_main_copies_the_vault_when_asked(tmp_path):
    ws = make_ws(tmp_path)
    dest = tmp_path / "exported"
    assert build_vault.main(["--workspace", str(ws), "--copy-to", str(dest)]) == 0
    assert (dest / "00-MOC" / "Proposal Brief.md").is_file()
    assert (dest / ".obsidian" / "core-plugins.json").is_file()


def test_main_refuses_copy_to_that_targets_the_source_vault(tmp_path):
    """--copy-to rmtrees its destination first; it must never be pointed at the vault itself."""
    ws = make_ws(tmp_path)
    vault = ws / "vault"
    assert build_vault.main(["--workspace", str(ws), "--copy-to", str(vault)]) == 1
    # The vault must survive the refused copy.
    assert (vault / "00-MOC" / "Proposal Brief.md").is_file()


def test_main_refuses_copy_to_that_is_an_ancestor_of_the_vault(tmp_path):
    """--copy-to naming the workspace root (or any ancestor of the vault) must be refused —
    rmtree-ing it would destroy the vault and the rest of the workspace before copytree runs."""
    ws = make_ws(tmp_path)
    assert build_vault.main(["--workspace", str(ws), "--copy-to", str(ws)]) == 1
    # Nothing in the workspace may be deleted by the refused copy.
    assert (ws / "vault" / "00-MOC" / "Proposal Brief.md").is_file()
    assert (ws / "claims.jsonl").is_file()
    assert (ws / "verdicts.jsonl").is_file()
    assert (ws / "fetch-log.jsonl").is_file()
    assert (ws / "evidence-pack.md").is_file()


def test_main_refuses_copy_to_inside_the_vault(tmp_path):
    """--copy-to naming a path inside the vault must also be refused."""
    ws = make_ws(tmp_path)
    vault = ws / "vault"
    dest = vault / "nested" / "export"
    assert build_vault.main(["--workspace", str(ws), "--copy-to", str(dest)]) == 1
    assert (vault / "00-MOC" / "Proposal Brief.md").is_file()
    assert not dest.exists()
