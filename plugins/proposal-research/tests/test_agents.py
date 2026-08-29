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
