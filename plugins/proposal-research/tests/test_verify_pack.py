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


# --- url normalization --------------------------------------------------

def test_normalize_url_strips_fragment_and_trailing_slash():
    assert verify_pack.normalize_url("https://a.com/x/#frag") == "https://a.com/x"
    assert verify_pack.normalize_url("https://a.com/x") == "https://a.com/x"


def test_normalize_url_handles_none():
    assert verify_pack.normalize_url(None) == ""


# --- check 3: fetch provenance -----------------------------------------

def test_clean_workspace_passes_provenance(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_fetch_provenance(ctx)) == []


def test_cited_url_never_fetched_fails(tmp_path):
    fetches = [f for f in build.FETCHES_OK if f["url"] != build.URL_B]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_fetch_provenance(ctx))
    assert any("C002" in f.message and "never retrieved" in f.message for f in findings)


def test_provenance_matches_despite_trailing_slash(tmp_path):
    fetches = [dict(f) for f in build.FETCHES_OK]
    for f in fetches:
        if f["url"]:
            f["url"] = f["url"] + "/"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert fails(verify_pack.check_fetch_provenance(ctx)) == []


def test_empty_fetch_log_fails_every_cited_claim(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=[]))
    assert len(fails(verify_pack.check_fetch_provenance(ctx))) == 2


# --- check 4: validator blindness --------------------------------------

def test_clean_workspace_passes_blindness(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_validator_blindness(ctx)) == []


def test_validator_that_never_fetched_the_url_fails(tmp_path):
    fetches = [f for f in build.FETCHES_OK if f["agent_id"] != "val-s1"]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_validator_blindness(ctx))
    assert any("val-s1" in f.message and "C001" in f.message for f in findings)


def test_validator_that_fetched_a_different_url_fails(tmp_path):
    fetches = [dict(f) for f in build.FETCHES_OK]
    for f in fetches:
        if f["agent_id"] == "val-s1":
            f["url"] = "https://unrelated.example/other"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert any("val-s1" in f.message for f in fails(verify_pack.check_validator_blindness(ctx)))


def test_verdict_with_no_validator_agent_id_fails(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1].pop("validator_agent_id")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_validator_blindness(ctx))
    assert any("no validator_agent_id" in f.message for f in findings)


def test_blindness_only_applies_to_body_claims(tmp_path):
    pack = "# Pack\n\nNo citations here.\n\n## Unverified & excluded\n\n- [C001]\n"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=[], pack=pack))
    assert fails(verify_pack.check_validator_blindness(ctx)) == []


# --- validator tool restrictions ---------------------------------------

def test_validator_using_websearch_fails(tmp_path):
    fetches = list(build.FETCHES_OK) + [
        {"ts": "2026-08-29T09:53:00Z", "tool": "WebSearch", "url": None,
         "query": "friendlier source", "agent_id": "val-s1", "agent_type": "validator"},
    ]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    findings = fails(verify_pack.check_validator_tool_restrictions(ctx))
    assert any("val-s1" in f.message and "WebSearch" in f.message for f in findings)


def test_researcher_using_websearch_is_fine(tmp_path):
    fetches = list(build.FETCHES_OK) + [
        {"ts": "2026-08-29T09:53:00Z", "tool": "WebSearch", "url": None,
         "query": "mcp tool limit", "agent_id": "res-1", "agent_type": "researcher"},
    ]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, fetches=fetches))
    assert fails(verify_pack.check_validator_tool_restrictions(ctx)) == []


# --- check 5: uncited prose --------------------------------------------

def test_clean_workspace_passes_uncited_prose(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_long_uncited_body_paragraph_fails(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "Copilot Studio is clearly the stronger option for this client given the "
        "existing Microsoft investment and the team's familiarity with Power Platform.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert len(fails(verify_pack.check_uncited_prose(ctx))) == 1


def test_short_transition_paragraph_is_ignored(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded", "In summary:\n\n## Unverified & excluded")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_headings_tables_and_code_are_ignored(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "### A heading that is quite long indeed and has many words in it here\n\n"
        "| column one | column two | column three | column four | column five |\n"
        "|---|---|---|---|---|\n\n"
        "```\nsome code block with plenty of words inside it for length\n```\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_explicit_no_citation_marker_exempts_a_paragraph(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "<!-- no-citation: framing, not a factual claim -->\n"
        "This section compares the two candidate architectures against the client's "
        "stated priorities rather than asserting any new external fact.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_appendix_prose_is_never_flagged(tmp_path):
    pack = build.PACK_OK + (
        "\nThese claims could not be stood up against any first-party source "
        "and are recorded here so the reader can see what was excluded.\n")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


# --- check 6: source mix ------------------------------------------------

def test_vendor_doc_material_claims_pass_source_mix(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_source_mix(ctx)) == []


def test_material_claim_sourced_from_blog_warns(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, source_type="blog"), build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = verify_pack.check_source_mix(ctx)
    assert fails(findings) == []
    assert any(f.severity == verify_pack.WARN and "C001" in f.message for f in findings)


def test_collect_stats_counts_sources_and_verdicts(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    stats = verify_pack.collect_stats(ctx)
    assert stats["claims_total"] == 2
    assert stats["claims_cited"] == 2
    assert stats["source_mix"]["vendor_doc"] == 2
    assert stats["verdict_counts"]["CONFIRMED"] == 3
    assert stats["fetches_total"] == 5


# --- runner, renderer, CLI ---------------------------------------------

def test_run_checks_on_clean_workspace_has_no_failures(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.run_checks(ctx)) == []


def test_render_report_marks_pass(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    report = verify_pack.render_report([], verify_pack.collect_stats(ctx), True)
    assert "GATE: PASS" in report
    assert "Source mix" in report


def test_render_report_lists_failures(tmp_path):
    findings = [verify_pack.Finding("fetch-provenance", verify_pack.FAIL, "C001 was never retrieved")]
    report = verify_pack.render_report(findings, {"claims_total": 1, "claims_cited": 1,
                                                  "source_mix": {}, "verdict_counts": {},
                                                  "fetches_total": 0}, False)
    assert "GATE: FAIL" in report
    assert "C001 was never retrieved" in report


def test_render_report_no_spurious_none_with_failures_and_warnings(tmp_path):
    findings = [
        verify_pack.Finding("fetch-provenance", verify_pack.FAIL, "C001 was never retrieved"),
        verify_pack.Finding("source-mix", verify_pack.WARN, "C001 uses weak source"),
    ]
    stats = {
        "claims_total": 1,
        "claims_cited": 1,
        "source_mix": {"blog": 1},
        "verdict_counts": {"CONFIRMED": 1},
        "fetches_total": 0,
    }
    report = verify_pack.render_report(findings, stats, False)
    # Check that we have the expected content
    assert "C001 was never retrieved" in report
    assert "C001 uses weak source" in report
    # Ensure no spurious "- none" lines appear in sections with content
    lines = report.split("\n")
    in_failures = False
    in_warnings = False
    failures_section_has_content = False
    warnings_section_has_content = False
    for i, line in enumerate(lines):
        if "## Failures" in line:
            in_failures = True
            in_warnings = False
        elif "## Warnings" in line:
            in_failures = False
            in_warnings = True
        elif line.startswith("##"):
            in_failures = False
            in_warnings = False
        elif in_failures and line.startswith("- "):
            if "C001" in line:
                failures_section_has_content = True
            if line == "- none":
                assert False, "Spurious '- none' in failures section when failures exist"
        elif in_warnings and line.startswith("- "):
            if "C001" in line:
                warnings_section_has_content = True
            if line == "- none":
                assert False, "Spurious '- none' in warnings section when warnings exist"
    assert failures_section_has_content
    assert warnings_section_has_content


def test_main_passes_on_clean_workspace_and_writes_report(tmp_path):
    ws = build.make_workspace(tmp_path)
    assert verify_pack.main(["--workspace", str(ws)]) == 0
    assert "GATE: PASS" in (ws / "verify-report.md").read_text()


def test_main_fails_on_orphan_citation(tmp_path):
    ws = build.make_workspace(tmp_path, pack=build.PACK_OK.replace("[C002]", "[C999]"))
    assert verify_pack.main(["--workspace", str(ws)]) == 1
    assert "GATE: FAIL" in (ws / "verify-report.md").read_text()


def test_main_accepts_alternate_pack_name(tmp_path):
    ws = build.make_workspace(tmp_path, pack_name="proposal.md")
    assert verify_pack.main(["--workspace", str(ws), "--pack", "proposal.md"]) == 0
    assert (ws / "verify-report-proposal.md").is_file()
