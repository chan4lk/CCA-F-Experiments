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
                  "Phase 4", "Phase 5", "Phase 6", "Phase 6b", "Phase 7"]:
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
    # \b after the heading stops "Phase 6" from swallowing "Phase 6b", and "Phase 7" from
    # swallowing "Phase 7b" — both are distinct headings in the document.
    pattern = re.compile(rf"^## {re.escape(heading)}\b.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(text)
    assert match, f"could not find a '## {heading}' section"
    return match.group(0)


def test_skill_pins_the_model_for_every_role():
    """Matched within ONE LINE, not across the phase with DOTALL.

    Phase 3 names both haiku and sonnet — the validator and its escalation — so a
    DOTALL match still succeeded with the two roles swapped. Every dispatch
    instruction states its role and its model on one line, so the line is the
    right scope and a swap now fails.
    """
    text = SKILL.read_text()
    for role, model in [("planner", "sonnet"), ("researcher", "sonnet"),
                        ("validator", "haiku"), ("gap-hunter", "opus"),
                        ("synthesizer", "fable"), ("proposal-writer", "fable")]:
        section = phase_section(text, PHASE_FOR_ROLE[role])
        pattern = rf"dispatch[^\n]*`{role}`[^\n]*model `{model}`"
        assert re.search(pattern, section, re.IGNORECASE), f"{role} -> {model}"


def test_swapping_the_phase_3_models_fails_the_pairing_check():
    """The check that the check works. This is the weakness M5 named."""
    section = phase_section(SKILL.read_text(), "Phase 3")
    swapped = (section.replace("`haiku`", "\x00").replace("`sonnet`", "`haiku`")
                      .replace("\x00", "`sonnet`"))
    assert not re.search(r"dispatch[^\n]*`validator`[^\n]*model `haiku`", swapped, re.I)


def test_skill_pins_the_escalation_model_to_sonnet():
    """Nothing pinned the escalation model at all; it is the whole point of the pass."""
    section = phase_section(SKILL.read_text(), "Phase 3")
    assert re.search(r"\*\*Escalation:\*\*[^\n]*", section)
    escalation = section[section.index("**Escalation:**"):]
    assert re.search(r"second\s+validator, \*\*model `sonnet`\*\*", escalation, re.S), \
        "Phase 3 must pin the escalation validator to sonnet"


def test_skill_requires_two_distinct_validators_for_a_material_claim():
    """CRITICAL 2: the same validator ruling twice satisfied the old rule."""
    section = phase_section(SKILL.read_text(), "Phase 3")
    assert "two different validators" in section
    assert "two\ndifferent models" in section or "two different models" in section


def test_skill_pins_validator_identity_without_relying_on_recording_order():
    """Replaces test_skill_requires_recording_each_verdict_before_the_next_dispatch.

    That ordering constraint existed only because --infer-agent-from reads a
    cumulative fetch log and cannot tell two validators of one page apart.
    Batching with the agentId the orchestrator already holds removes the
    constraint, so the SKILL no longer mandates the order — but it must still
    pin identity to a specific validator by some means.
    """
    section = phase_section(SKILL.read_text(), "Phase 3")
    assert "validator_agent_id" in section, "identity must still be pinned per verdict"
    assert "--infer-agent-from" in section, "the single-row fallback must still be documented"
    assert "two different validators" in section, "the escalation rule must survive"


def test_skill_builds_the_vault_only_after_the_gate():
    """I5: a vault built before the gate looks finished whether or not it passed."""
    text = SKILL.read_text()
    assert text.index("## Phase 6 — The gate") < text.index("## Phase 6b — Build the vault")
    assert "## Phase 5b" not in text
    vault_phase = phase_section(text, "Phase 6b")
    assert "after the gate passes" in vault_phase


def test_skill_derives_the_slug_with_the_plugin_slugifier():
    """M6: workspace.slugify exists; the orchestrator must not slugify by hand."""
    assert "workspace.slugify" in SKILL.read_text()


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


# --- shipped docs -------------------------------------------------------

README = PLUGIN / "README.md"
PLUGIN_JSON = PLUGIN / ".claude-plugin" / "plugin.json"


def test_readme_describes_the_mechanism_that_actually_exists():
    """I7: it claimed a hook rejects a claim row that has no quote.

    No hook validates quotes. ledger_lint denies Write/Edit on the ledgers
    unconditionally and the quote rule lives in add_claim.py, with the gate
    re-checking it. On a plugin selling structural enforcement, describing the
    wrong structure is the worst place for a doc bug.
    """
    text = README.read_text(encoding="utf-8")
    assert "rejected by a hook before it lands" not in text
    assert "add_claim.py" in text and "PreToolUse" in text


def test_readme_states_a_python_version_the_code_supports():
    assert "Python 3.12+" not in README.read_text(encoding="utf-8")


def test_readme_does_not_bake_in_an_authors_local_path():
    assert "~/repos/CCAF" not in README.read_text(encoding="utf-8")


def test_plugin_description_counts_the_hooks_correctly():
    """The description must count the hooks that actually exist.

    It once said "two PostToolUse hooks" when one was PreToolUse. The counts
    are now derived from hooks.json rather than hardcoded, so adding a hook
    fails this test until the description is updated with it.
    """
    import json
    cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    post = len(cfg["hooks"]["PostToolUse"])
    pre = len(cfg["hooks"]["PreToolUse"])
    description = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["description"]

    words = {1: "one", 2: "two", 3: "three", 4: "four"}
    assert f"{words[post]} PostToolUse hook" in description, (
        f"hooks.json has {post} PostToolUse hook(s); the description disagrees")
    assert f"{words[pre]} PreToolUse hook" in description, (
        f"hooks.json has {pre} PreToolUse hook(s); the description disagrees")


def test_skill_tells_the_orchestrator_to_batch_verdicts():
    """Batching is the single largest token lever; the SKILL must mandate it."""
    text = SKILL.read_text(encoding="utf-8")
    assert "--batch" in text
    assert "verdict-batch.jsonl" in text
    assert "not one at a time" in text.lower()


def test_skill_explains_why_batching_uses_explicit_agent_ids():
    """Inference cannot work in a batch — the reason must be stated, not assumed."""
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "agentid" in text
    assert "cumulative" in text


def test_skill_has_context_discipline_rules():
    text = SKILL.read_text(encoding="utf-8")
    assert "Keeping your own context small" in text
    assert "path" in text and "not a paste" in text


def test_skill_tells_the_orchestrator_its_own_prose_is_the_cost():
    """Measured: ~500K of the ~600K context growth was the orchestrator's own
    output, not tool results. The earlier guidance only addressed file dumps."""
    section = SKILL.read_text(encoding="utf-8")
    assert "your own prose" in section
    assert "once per wave, not once per agent" in section
    assert "Never restate an agent's output" in section


def test_the_two_manifests_declare_the_same_version():
    """plugin.json and marketplace.json each carry a version and can drift.

    A stale marketplace entry installs the wrong version silently.
    """
    import json
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    marketplace = json.loads(
        (PLUGIN.parents[1] / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    entry = next(p for p in marketplace["plugins"] if p["name"] == plugin["name"])
    assert entry["version"] == plugin["version"], (
        f"marketplace says {entry['version']}, plugin.json says {plugin['version']}")


def test_changelog_documents_the_current_version():
    changelog = (PLUGIN / "CHANGELOG.md").read_text(encoding="utf-8")
    import json
    version = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]
    assert f"## {version}" in changelog, f"CHANGELOG has no entry for {version}"
