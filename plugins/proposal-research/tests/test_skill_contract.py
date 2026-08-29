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


def test_skill_pins_the_model_for_every_role():
    text = SKILL.read_text()
    for role, model in [("planner", "sonnet"), ("researcher", "sonnet"),
                        ("validator", "haiku"), ("gap-hunter", "opus"),
                        ("synthesizer", "fable"), ("proposal-writer", "fable")]:
        pattern = rf"{role}.*{model}"
        assert re.search(pattern, text, re.IGNORECASE | re.DOTALL), f"{role} -> {model}"


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
