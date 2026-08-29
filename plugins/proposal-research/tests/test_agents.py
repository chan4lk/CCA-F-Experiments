from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "agents"

EXPECTED_TOOLS = {
    "planner": {"Read", "Write"},
    "researcher": {"WebSearch", "WebFetch", "Bash",
                   "mcp__microsoft_docs_mcp__microsoft_docs_search",
                   "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
                   "mcp__headroom__headroom_compress"},
    "validator": {"WebFetch", "mcp__microsoft_docs_mcp__microsoft_docs_fetch"},
    "gap-hunter": {"Read", "WebSearch", "Write"},
    "synthesizer": {"Read", "Write"},
    "proposal-writer": {"Read", "Write"},
}


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path.name} has no frontmatter"
    block = text.split("\n---", 1)[0].lstrip("-\n")
    meta = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def tools_of(name: str) -> set[str]:
    raw = parse_frontmatter(AGENTS / f"{name}.md").get("tools", "")
    return {t.strip() for t in raw.split(",") if t.strip()}


def test_every_agent_file_exists():
    for name in EXPECTED_TOOLS:
        assert (AGENTS / f"{name}.md").is_file(), name


def test_every_agent_declares_name_and_description():
    for name in EXPECTED_TOOLS:
        meta = parse_frontmatter(AGENTS / f"{name}.md")
        assert meta.get("name") == name
        assert meta.get("description")


def test_tool_sets_match_the_design():
    for name, expected in EXPECTED_TOOLS.items():
        assert tools_of(name) == expected, name


def test_validator_cannot_read_the_ledger():
    """Blindness is enforced by tool restriction, not by instruction."""
    tools = tools_of("validator")
    assert "Read" not in tools
    assert "Bash" not in tools
    assert "Grep" not in tools


def test_validator_cannot_search():
    assert "WebSearch" not in tools_of("validator")


def test_synthesizer_has_no_web_tools():
    tools = tools_of("synthesizer")
    assert not any(t.startswith("Web") or "docs_fetch" in t or "docs_search" in t for t in tools)


def test_proposal_writer_has_no_web_tools():
    tools = tools_of("proposal-writer")
    assert not any(t.startswith("Web") for t in tools)


def test_planner_cannot_search():
    assert "WebSearch" not in tools_of("planner")


def test_no_agent_declares_a_model_in_frontmatter():
    """Models are passed at dispatch time; fable is not verified in frontmatter."""
    for name in EXPECTED_TOOLS:
        assert "model" not in parse_frontmatter(AGENTS / f"{name}.md")


# --- the no-citation escape hatch ---------------------------------------

def test_both_pack_writers_document_the_no_citation_marker():
    """I6: only the synthesizer knew about it.

    proposal-writer's mandated structure includes "Effort and phasing"
    (explicitly "estimates, not findings") and "What we need from you" — long
    uncited prose that check_uncited_prose fails when Phase 7 re-runs the gate
    over proposal.md. Without the marker documented, the writer cannot pass a
    gate its own required structure guarantees it will hit.
    """
    for name in ("synthesizer", "proposal-writer"):
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
        assert "<!-- no-citation:" in text, name


def test_proposal_writer_is_told_which_sections_need_the_marker():
    text = (AGENTS / "proposal-writer.md").read_text(encoding="utf-8")
    assert "Effort and phasing" in text
    assert "What we need from you" in text


def test_both_pack_writers_are_told_bullets_and_tables_are_checked():
    """CRITICAL 1 changed what the gate demands of markdown shape."""
    for name in ("synthesizer", "proposal-writer"):
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8").lower()
        assert "bullets and table rows" in text, name


# --- marker guidance -----------------------------------------------------

MARKER_SECTIONS = [
    "The problem we are solving",
    "What we need from you",
    "Effort and phasing",
    "Open questions",
]


def test_proposal_writer_names_every_section_that_needs_a_marker():
    """A proposal written to this agent's own structure must pass the gate.

    The final review wrote one to the mandated structure, marked exactly the
    sections the file named, and got six FAILs: two mandated sections were
    never named, and the marker was applied per section when it is per block.
    """
    text = (AGENTS / "proposal-writer.md").read_text(encoding="utf-8")
    # Scoped to the Citation rules section: every section name also appears in
    # the mandated-structure block above it, so a whole-file search would pass
    # trivially and could never fail.
    rules = text.split("## Citation rules", 1)[1]
    missing = [s for s in MARKER_SECTIONS if s not in rules]
    assert missing == [], f"sections that need a marker but are not named in Citation rules: {missing}"


def test_proposal_writer_states_the_marker_is_per_block():
    """One marker per section is the mistake the guidance must prevent."""
    text = (AGENTS / "proposal-writer.md").read_text(encoding="utf-8").lower()
    assert "one marker per block" in text
    assert "not one per section" in text


def test_synthesizer_marker_guidance_agrees_with_the_writer():
    """Both agents write packs the same gate reads; the rule cannot differ."""
    text = (AGENTS / "synthesizer.md").read_text(encoding="utf-8").lower()
    assert "one marker per block" in text
