import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify_pack  # noqa: E402
from fixtures import build  # noqa: E402


def fails(findings):
    return [f for f in findings if f.severity == verify_pack.FAIL]


# --- parsing ------------------------------------------------------------

def test_extract_citations_finds_ids_in_order():
    assert verify_pack.extract_citations("a [C002] b [C001] c") == ["C002", "C001"]


def test_extract_citations_ignores_malformed_ids():
    assert verify_pack.extract_citations("[C1] [X001] [C012]") == ["C012"]


def test_split_pack_separates_appendix():
    body, appendix = verify_pack.split_pack(build.PACK_OK)
    assert "[C001]" in body
    assert "Nothing was excluded" in appendix
    assert "[C001]" not in appendix


def test_split_pack_with_no_appendix_returns_empty_appendix():
    body, appendix = verify_pack.split_pack("# Pack\n\nA claim [C001].\n")
    assert appendix == ""


# --- check 1: citations resolve ----------------------------------------

def test_clean_workspace_passes_check_one(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_citations_resolve(ctx)) == []


def test_orphan_citation_fails(tmp_path):
    pack = build.PACK_OK.replace("[C002]", "[C999]")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    findings = fails(verify_pack.check_citations_resolve(ctx))
    assert len(findings) == 1
    assert "C999" in findings[0].message


# --- check 2: verdict admission ----------------------------------------

def test_clean_workspace_passes_check_two(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []


def test_cited_claim_with_no_verdict_fails(tmp_path):
    verdicts = [v for v in build.VERDICTS_OK if v["claim_id"] != "C002"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C002" in f.message and "no verdict" in f.message for f in findings)


def test_material_claim_with_single_verdict_fails_escalation_rule(tmp_path):
    verdicts = [v for v in build.VERDICTS_OK if v["validator_model"] != "sonnet"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("escalation" in f.message for f in findings)


def test_material_claim_not_confirmed_by_all_validators_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1]["verdict"] = "MISLEADING"
    verdicts[1]["caveat"] = "Preview only."
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C001" in f.message for f in findings)


def test_contradicted_claim_in_body_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2]["verdict"] = "CONTRADICTED"
    verdicts[2].pop("quote", None)
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("CONTRADICTED" in f.message for f in findings)


def test_context_claim_not_found_warns_but_does_not_fail(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2]["verdict"] = "NOT_FOUND"
    verdicts[2].pop("quote", None)
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = verify_pack.check_verdict_admission(ctx)
    assert fails(findings) == []
    assert any(f.severity == verify_pack.WARN and "C002" in f.message for f in findings)


def test_misleading_claim_without_its_caveat_in_pack_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("caveat" in f.message for f in findings)


def test_misleading_claim_with_caveat_present_passes(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="Public preview only, not GA.")
    pack = build.PACK_OK.replace(
        "[C002].", "[C002]. Public preview only, not GA.")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts, pack=pack))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []


def test_misleading_claim_with_missing_caveat_field_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING")
    verdicts[2].pop("caveat", None)
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C002" in f.message and "caveat is absent" in f.message for f in findings)


def test_misleading_claim_with_blank_caveat_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[2].update(verdict="MISLEADING", caveat="  ")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("C002" in f.message and "caveat is absent" in f.message for f in findings)


def test_claims_cited_only_in_appendix_are_not_admission_checked(tmp_path):
    pack = """# Evidence Pack

Body with no citations.

## Unverified & excluded

- Could not stand up: [C001]
"""
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=[], pack=pack))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []
