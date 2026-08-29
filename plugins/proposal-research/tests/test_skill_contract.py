import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SKILL = PLUGIN / "skills" / "proposal-research" / "SKILL.md"
COMMANDS = PLUGIN / "commands"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} has no frontmatter"
    meta = {}
    for line in text.split("\n---", 1)[0].lstrip("-\n").splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta


def test_skill_file_exists_with_name_and_description():
    meta = frontmatter(SKILL)
    assert meta["name"] == "proposal-research"
    assert len(meta["description"]) > 40


def test_skill_documents_every_phase():
    text = SKILL.read_text()
    for phase in ["Phase 0", "Phase 0.5", "Phase 1", "Phase 2", "Phase 3",
                  "Phase 4", "Phase 5", "Phase 5b", "Phase 6", "Phase 7"]:
        assert phase in text, phase


# Each role is dispatched exactly once, in exactly one phase, so scoping the model-pairing
# check to that phase's own section (rather than searching the whole document with DOTALL)
# means a mis-pairing actually fails the test instead of being rescued by an unrelated
# mention of the same model name in a later phase.
PHASE_FOR_ROLE = {
    "planner": "Phase 1",
    "researcher": "Phase 2",
    "validator": "Phase 3",
    "gap-hunter": "Phase 4",
    "synthesizer": "Phase 5",
    "proposal-writer": "Phase 7",
}


def phase_section(text: str, heading: str) -> str:
    # \b after the heading stops "Phase 5" from swallowing "Phase 5b", and "Phase 7" from
    # swallowing "Phase 7b" — both are distinct headings in the document.
    pattern = re.compile(rf"^## {re.escape(heading)}\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    assert match, f"could not find a '## {heading}' section"
    return match.group(0)


def test_skill_pins_the_model_for_every_role():
    text = SKILL.read_text()
    for role, model in [("planner", "sonnet"), ("researcher", "sonnet"),
                        ("validator", "haiku"), ("gap-hunter", "opus"),
                        ("synthesizer", "fable"), ("proposal-writer", "fable")]:
        section = phase_section(text, PHASE_FOR_ROLE[role])
        pattern = rf"dispatch.*`{role}`.*model `{model}`"
        assert re.search(pattern, section, re.IGNORECASE | re.DOTALL), f"{role} -> {model}"


def test_skill_states_the_human_gate_is_blocking():
    text = SKILL.read_text().lower()
    assert "human gate" in text
    assert "do not proceed" in text or "must not proceed" in text


def test_skill_caps_the_gap_loop_at_two_rounds():
    assert "2 rounds" in SKILL.read_text() or "two rounds" in SKILL.read_text()


def test_all_three_commands_exist():
    for name in ["research", "draft", "verify"]:
        assert (COMMANDS / f"{name}.md").is_file(), name


def test_commands_have_descriptions():
    for name in ["research", "draft", "verify"]:
        assert frontmatter(COMMANDS / f"{name}.md").get("description")


def test_research_command_invokes_the_skill():
    assert "proposal-research" in (COMMANDS / "research.md").read_text()
