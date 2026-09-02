import prompts
from conftest import finding
from criteria import REPORT, SKIP


def test_system_prompt_names_reportable_and_skippable_categories():
    for name in REPORT:
        assert name in prompts.SYSTEM
    for name in SKIP:
        assert name in prompts.SYSTEM


def test_system_prompt_avoids_confidence_filtering_language():
    lowered = prompts.SYSTEM.lower()
    assert "be conservative" not in lowered
    assert "high-confidence" not in lowered
    assert "only report findings you are sure" not in lowered


def test_system_prompt_carries_both_sides_of_the_boundary():
    assert "cursor.execute(f" in prompts.SYSTEM
    assert "%s" in prompts.SYSTEM


def test_system_prompt_states_the_reviewer_did_not_write_the_code():
    assert "did not write this code" in prompts.SYSTEM


def test_file_pass_scopes_the_reviewer_to_one_file():
    prompt = prompts.file_pass("src/orders.py", "diff text", "source text")
    assert "src/orders.py" in prompt
    assert "diff text" in prompt and "source text" in prompt
    assert "separate pass" in prompt


def test_integration_pass_asks_only_for_cross_file_defects():
    prompt = prompts.integration_pass("full diff")
    assert "ACROSS files" in prompt
    assert "callers were not updated" in prompt
    assert "do not repeat single-file issues" in prompt.lower()


def test_prior_findings_are_scoped_to_the_file_under_review():
    prior = [finding(file="src/orders.py"), finding(file="src/billing.py", detected_pattern="other")]
    prompt = prompts.file_pass("src/orders.py", "d", "s", prior)

    assert "fstring-in-execute" in prompt
    assert "src/billing.py" not in prompt


def test_prior_findings_instruct_against_reposting():
    prompt = prompts.file_pass("src/orders.py", "d", "s", [finding()])
    assert "Do not report any of the above again" in prompt


def test_integration_pass_sees_every_prior_finding():
    prior = [finding(file="a.py"), finding(file="b.py")]
    prompt = prompts.integration_pass("d", prior)
    assert "a.py" in prompt and "b.py" in prompt


def test_test_pass_includes_the_existing_suite():
    prompt = prompts.test_pass("src/orders.py", "source", "def test_existing(): ...")
    assert "test_existing" in prompt
    assert "do not propose it again" in prompt.lower()


def test_test_pass_handles_a_file_with_no_tests_yet():
    assert "(none)" in prompts.test_pass("src/orders.py", "source", "")
