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


def test_material_claim_with_two_verdicts_from_one_validator_fails(tmp_path):
    """CRITICAL 2: two rulings by one validator is not an escalation.

    The SKILL's own documented flow produced this — both verdicts were recorded
    with --infer-agent-from, which returned the LAST validator that fetched the
    URL, so both rows carried the same id. The gate only counted rows.
    """
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1]["validator_agent_id"] = "val-h1"
    verdicts[1]["validator_model"] = "haiku"
    fetches = [f for f in build.FETCHES_OK if f["agent_id"] != "val-s1"]
    ws = build.make_workspace(tmp_path, verdicts=verdicts, fetches=fetches)
    ctx = verify_pack.load_context(ws)
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("same validator" in f.message for f in findings)
    assert verify_pack.main(["--workspace", str(ws)]) == 1


def test_material_claim_ruled_twice_by_the_same_model_fails(tmp_path):
    """Two distinct haiku validators are still not an escalation."""
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1]["validator_model"] = "haiku"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    findings = fails(verify_pack.check_verdict_admission(ctx))
    assert any("escalation pass is missing" in f.message and "haiku" in f.message
               for f in findings)
    assert not any("same validator" in f.message for f in findings)


def test_material_claim_missing_both_distinctions_reports_both(tmp_path):
    verdicts = [dict(v) for v in build.VERDICTS_OK]
    verdicts[1]["validator_agent_id"] = "val-h1"
    verdicts[1]["validator_model"] = "haiku"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    messages = [f.message for f in fails(verify_pack.check_verdict_admission(ctx))]
    assert any("same validator" in m for m in messages)
    assert any("escalation pass is missing" in m for m in messages)


def test_context_claim_may_carry_a_single_verdict(tmp_path):
    """The distinctness rule is material-only; context claims need one pass."""
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert fails(verify_pack.check_verdict_admission(ctx)) == []


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


def test_verdict_row_with_no_claim_id_is_not_bucketed(tmp_path):
    """build_vault guards this key; the gate must guard it identically."""
    verdicts = list(build.VERDICTS_OK) + [
        {"verdict": "CONFIRMED", "validator_agent_id": "val-x", "validator_model": "haiku"},
    ]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, verdicts=verdicts))
    assert None not in ctx.verdicts
    assert set(ctx.verdicts) == {"C001", "C002"}


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


def test_cited_claim_with_no_url_fails_provenance(tmp_path):
    """I1: `if url and ...` skipped a urlless claim, so the check passed vacuously."""
    claims = [{k: v for k, v in build.CLAIM_MATERIAL.items() if k != "url"},
              build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = fails(verify_pack.check_fetch_provenance(ctx))
    assert any("C001" in f.message and "no url" in f.message for f in findings)


def test_cited_claim_with_blank_url_fails_provenance(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, url="  "), build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    assert any("no url" in f.message for f in fails(verify_pack.check_fetch_provenance(ctx)))


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


def test_urlless_body_claim_fails_blindness(tmp_path):
    """I1: `if not url: continue` skipped it, so blindness passed vacuously too."""
    claims = [{k: v for k, v in build.CLAIM_MATERIAL.items() if k != "url"},
              build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = fails(verify_pack.check_validator_blindness(ctx))
    assert any("C001" in f.message and "no url" in f.message for f in findings)


def test_a_urlless_material_claim_no_longer_passes_the_whole_gate(tmp_path):
    """I1 end to end: an empty fetch log used to give findings: [] and GATE: PASS."""
    claims = [{k: v for k, v in build.CLAIM_MATERIAL.items() if k != "url"}]
    pack = ("# Pack\n\nCopilot Studio caps MCP tools at 10 per server connection "
            "[C001].\n")
    ws = build.make_workspace(
        tmp_path, claims=claims, fetches=[], pack=pack,
        verdicts=[v for v in build.VERDICTS_OK if v["claim_id"] == "C001"])
    assert verify_pack.main(["--workspace", str(ws)]) == 1
    checks = {f.check for f in fails(verify_pack.run_checks(verify_pack.load_context(ws)))}
    assert {"fetch-provenance", "validator-blindness"} <= checks


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


def test_headings_and_code_are_ignored(tmp_path):
    """Genuine structure stays exempt. Tables no longer do — see the tests below.

    This test previously asserted tables were exempt as well. That exemption was
    the hole Critical 1 walked through: a pack of bullets and table rows and no
    citations at all passed the whole gate. Headings and fenced code are still
    exempt because neither is the pack asserting anything.
    """
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "### A heading that is quite long indeed and has many words in it here\n\n"
        "```\nsome code block with plenty of words inside it for length\n```\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


UNCITED_BULLETS_AND_TABLE = """# Evidence Pack: Copilot Studio

## Summary

- Copilot Studio enforces a hard cap of 10 MCP tools per server connection, a binding constraint.
- Licensing is 200 USD per tenant per month for the Copilot Studio prepaid capacity pack.
- MCP support in Copilot Studio is generally available in all commercial regions today.

## Recommendation

| Option | Tool cap | Price | Availability |
|---|---|---|---|
| Copilot Studio + MCP | 10 tools per server, a hard limit | 200 USD per tenant monthly | GA in all commercial regions |

## Unverified & excluded

Nothing was excluded.
"""


def test_pack_of_uncited_bullets_and_table_rows_fails(tmp_path):
    """Critical 1: a cap, a price and an availability claim, zero citations.

    Every other check keys off the citations that are present, so with none
    present this check is the only thing standing between that pack and a PASS.
    """
    ws = build.make_workspace(tmp_path, claims=[], verdicts=[], fetches=[],
                              pack=UNCITED_BULLETS_AND_TABLE)
    assert verify_pack.main(["--workspace", str(ws)]) == 1
    ctx = verify_pack.load_context(ws)
    kinds = {f.message.split()[1] for f in fails(verify_pack.check_uncited_prose(ctx))}
    assert kinds == {"list", "table"}  # "factual list item" / "factual table row"
    assert len(fails(verify_pack.check_uncited_prose(ctx))) == 4


def test_cited_bullets_and_table_rows_pass(tmp_path):
    pack = UNCITED_BULLETS_AND_TABLE.replace("constraint.", "constraint [C001].") \
        .replace("capacity pack.", "capacity pack [C001].") \
        .replace("regions today.", "regions today [C001].") \
        .replace("commercial regions |", "commercial regions [C001] |")
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_short_structural_table_rows_are_ignored(tmp_path):
    """A table of contents asserts nothing; the word threshold keeps it exempt."""
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "| Section | Page |\n|---|---|\n| Findings | 2 |\n| Options | 5 |\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_short_open_questions_bullets_are_ignored(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "## Open Questions\n\n- Regional GA status\n- Seat pricing at 500 users\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_a_no_citation_marker_above_a_list_exempts_the_whole_list(tmp_path):
    """The escape hatch is block-level, so an Open Questions list needs one marker."""
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "## Open Questions\n\n"
        "<!-- no-citation: open questions are by definition not yet evidenced -->\n"
        "- Whether the ten-tool cap applies per connection or per environment is unconfirmed.\n"
        "- Whether seat pricing changes above five hundred users is unconfirmed anywhere.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_a_wrapped_list_item_is_one_unit(tmp_path):
    """The citation at the end of a wrapped bullet must satisfy the whole bullet."""
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "- Copilot Studio enforces a hard cap of ten MCP tools per server connection,\n"
        "  which is the binding constraint on this design [C001].\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert fails(verify_pack.check_uncited_prose(ctx)) == []


def test_table_delimiter_rows_are_never_flagged():
    units = verify_pack._body_units("| a | b |\n|:---|---:|\n| x | y |")
    assert [u.text for u in units] == ["a b", "x y"]


def test_blockquotes_remain_exempt(tmp_path):
    """A blockquote carries verbatim source text, not the pack's own assertion."""
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "> A maximum of ten tools per MCP server connection is supported by the product.\n\n"
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


def test_a_lone_closing_fence_does_not_swallow_the_rest_of_the_pack(tmp_path):
    """The fence state machine must not fail open.

    A fenced block whose closing fence is preceded by a blank line used to leave
    the parser stuck inside code, so every later paragraph was silently skipped
    and an uncited assertion after a code block passed the gate.
    """
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "```\nsome code\n\n```\n\n"
        "Copilot Studio is clearly the stronger option for this client given the "
        "existing Microsoft investment and the team's familiarity with Power Platform.\n\n"
        "## Unverified & excluded",
    )
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, pack=pack))
    assert any("stronger option" in f.message for f in fails(verify_pack.check_uncited_prose(ctx)))


def test_fenced_code_is_still_exempt_after_a_normal_fence(tmp_path):
    pack = build.PACK_OK.replace(
        "## Unverified & excluded",
        "```\nsome code block with plenty of words inside it for length here\n```\n\n"
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


# --- check 7: claim quotes ----------------------------------------------

def test_clean_workspace_passes_claim_quotes(tmp_path):
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert verify_pack.check_claim_quotes(ctx) == []


def test_cited_claim_with_no_quote_fails(tmp_path):
    """I2: the gate never read `quote`.

    add_claim.py enforces it, but ledger_lint only guards Write and Edit, and the
    researcher agent carries Bash — so an append redirect reaches claims.jsonl
    unvalidated.
    """
    claims = [{k: v for k, v in build.CLAIM_MATERIAL.items() if k != "quote"},
              build.CLAIM_CONTEXT]
    ws = build.make_workspace(tmp_path, claims=claims)
    ctx = verify_pack.load_context(ws)
    findings = fails(verify_pack.check_claim_quotes(ctx))
    assert any("C001" in f.message and "no verbatim quote" in f.message for f in findings)
    assert verify_pack.main(["--workspace", str(ws)]) == 1


def test_cited_claim_with_blank_quote_fails(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, quote="   "), build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    assert any("no verbatim quote" in f.message
               for f in fails(verify_pack.check_claim_quotes(ctx)))


def test_cited_claim_with_an_overlong_quote_fails(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, quote=" ".join(["word"] * 51)),
              build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = fails(verify_pack.check_claim_quotes(ctx))
    assert any("51-word quote" in f.message for f in findings)


def test_a_quote_at_exactly_the_limit_passes(tmp_path):
    claims = [dict(build.CLAIM_MATERIAL, quote=" ".join(["word"] * 50)),
              build.CLAIM_CONTEXT]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    assert fails(verify_pack.check_claim_quotes(ctx)) == []


def test_quote_check_covers_appendix_citations_too(tmp_path):
    """The appendix is where excluded claims live; they still need their quote."""
    claims = [build.CLAIM_MATERIAL, dict(build.CLAIM_CONTEXT, quote="")]
    pack = "# Pack\n\nCited [C001].\n\n## Unverified & excluded\n\n- Dropped [C002]\n"
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims, pack=pack))
    assert any("C002" in f.message for f in fails(verify_pack.check_claim_quotes(ctx)))


def test_uncited_claims_are_not_quote_checked(tmp_path):
    """A ledger row nobody cited cannot mislead the reader."""
    claims = [build.CLAIM_MATERIAL, build.CLAIM_CONTEXT,
              dict(build.CLAIM_MATERIAL, id="C003", quote="")]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    assert fails(verify_pack.check_claim_quotes(ctx)) == []


def test_claim_quotes_is_wired_into_the_runner():
    assert verify_pack.check_claim_quotes in verify_pack.ALL_CHECKS


# --- check 6: source mix ------------------------------------------------

def test_vendor_doc_material_claims_pass_source_mix(tmp_path):
    """Asserts on the WARNs, since check_source_mix never emits a FAIL.

    It previously asserted fails() == [], which is trivially true for any input
    at all and so could not fail — the same class of vacuous test this build has
    escalated twice.
    """
    ctx = verify_pack.load_context(build.make_workspace(tmp_path))
    assert verify_pack.check_source_mix(ctx) == []


def test_check_source_mix_only_ever_warns(tmp_path):
    """Pins the premise the test above rests on."""
    claims = [dict(build.CLAIM_MATERIAL, source_type="forum"),
              dict(build.CLAIM_CONTEXT, source_type="blog")]
    ctx = verify_pack.load_context(build.make_workspace(tmp_path, claims=claims))
    findings = verify_pack.check_source_mix(ctx)
    assert findings
    assert all(f.severity == verify_pack.WARN for f in findings)


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
