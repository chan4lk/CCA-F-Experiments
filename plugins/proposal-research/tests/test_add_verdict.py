import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import add_verdict  # noqa: E402

VALID = {
    "claim_id": "C001",
    "verdict": "CONFIRMED",
    "validator_agent_id": "a0b0ba8988783040d",
    "validator_model": "haiku",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
}


def test_valid_verdict_has_no_errors():
    assert add_verdict.validate_verdict(dict(VALID)) == []


def test_unknown_verdict_is_rejected():
    errors = add_verdict.validate_verdict(dict(VALID, verdict="PROBABLY"))
    assert any("verdict" in e for e in errors)


def test_null_claim_id_is_rejected():
    assert any("claim_id" in e for e in add_verdict.validate_verdict(dict(VALID, claim_id=None)))


def test_null_verdict_is_rejected():
    assert any("verdict" in e for e in add_verdict.validate_verdict(dict(VALID, verdict=None)))


def test_null_validator_agent_id_is_rejected():
    assert any("validator_agent_id" in e for e in add_verdict.validate_verdict(dict(VALID, validator_agent_id=None)))


def test_confirmed_without_own_quote_is_rejected():
    row = dict(VALID)
    del row["quote"]
    errors = add_verdict.validate_verdict(row)
    assert any("quote" in e for e in errors)


def test_misleading_requires_caveat():
    row = dict(VALID, verdict="MISLEADING", quote="Public preview.")
    errors = add_verdict.validate_verdict(row)
    assert any("caveat" in e for e in errors)


def test_misleading_with_caveat_is_accepted():
    row = dict(VALID, verdict="MISLEADING", quote="Public preview.", caveat="Preview only, not GA.")
    assert add_verdict.validate_verdict(row) == []


def test_not_found_needs_no_quote():
    row = {k: v for k, v in VALID.items() if k != "quote"}
    row["verdict"] = "NOT_FOUND"
    assert add_verdict.validate_verdict(row) == []


def test_missing_validator_agent_id_is_rejected():
    row = dict(VALID)
    del row["validator_agent_id"]
    assert any("validator_agent_id" in e for e in add_verdict.validate_verdict(row))


def test_bad_claim_id_is_rejected():
    assert any("claim_id" in e for e in add_verdict.validate_verdict(dict(VALID, claim_id="nope")))


def test_main_appends_and_fills_ruled_at(tmp_path):
    rc = add_verdict.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["ruled_at"].endswith("Z")


def test_main_rejects_invalid_and_writes_nothing(tmp_path, capsys):
    rc = add_verdict.main(["--workspace", str(tmp_path), "--json", json.dumps(dict(VALID, verdict="MAYBE"))])
    assert rc == 1
    assert not (tmp_path / "verdicts.jsonl").exists()
    assert "verdict" in capsys.readouterr().err


def write_fetch_log(tmp_path, rows):
    (tmp_path / "fetch-log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def write_verdicts(tmp_path, rows):
    (tmp_path / "verdicts.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_resolve_validator_agent_id_finds_the_fetching_validator(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "res-1", "agent_type": "researcher"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-9", "agent_type": "validator"},
    ])
    assert add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001") == ("val-9", "")


def test_resolve_ignores_trailing_slash_and_fragment(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x/", "agent_id": "val-9", "agent_type": "validator"},
    ])
    assert add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x#top", "C001") == ("val-9", "")


def test_resolve_returns_none_when_no_validator_fetched_it(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "res-1", "agent_type": "researcher"},
    ])
    agent_id, error = add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001")
    assert agent_id is None
    assert "no validator fetched" in error


def test_resolve_refuses_when_several_validators_have_not_yet_ruled(tmp_path):
    """Was: "returns the latest". Picking one silently was CRITICAL 2.

    Attributing both rulings on a claim to whichever validator finished second
    made a single validator's two passes satisfy the material escalation rule.
    Ambiguity must fail loudly.
    """
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-1", "agent_type": "validator"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-2", "agent_type": "validator"},
    ])
    agent_id, error = add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001")
    assert agent_id is None
    assert "cannot be inferred" in error
    assert "val-1" in error and "val-2" in error


def test_resolve_picks_the_validator_that_has_not_ruled_yet(tmp_path):
    """The SKILL's ordering, made unambiguous by construction.

    The fetch log is cumulative, so by the time the escalation validator records
    its verdict two validators have fetched the page. Subtracting the ones that
    already ruled on this claim leaves exactly one candidate.
    """
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-h1", "agent_type": "validator"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-s1", "agent_type": "validator"},
    ])
    write_verdicts(tmp_path, [
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
         "validator_model": "haiku"},
    ])
    assert add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001") == ("val-s1", "")


def test_resolve_ignores_verdicts_on_other_claims(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-h1", "agent_type": "validator"},
    ])
    write_verdicts(tmp_path, [
        {"claim_id": "C002", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
         "validator_model": "haiku"},
    ])
    assert add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001") == ("val-h1", "")


def test_resolve_refuses_when_the_only_fetcher_already_ruled(tmp_path):
    """The same validator cannot be inferred twice onto one claim."""
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-h1", "agent_type": "validator"},
    ])
    write_verdicts(tmp_path, [
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "val-h1",
         "validator_model": "haiku"},
    ])
    agent_id, error = add_verdict.resolve_validator_agent_id(
        tmp_path, "https://a.com/x", "C001")
    assert agent_id is None
    assert "already ruled" in error


def test_main_refuses_an_ambiguous_inference(tmp_path, capsys):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-1", "agent_type": "validator"},
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-2", "agent_type": "validator"},
    ])
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--infer-agent-from", "https://a.com/x",
    ])
    assert rc == 1
    assert not (tmp_path / "verdicts.jsonl").exists()
    assert "cannot be inferred" in capsys.readouterr().err


def test_main_accepts_an_explicit_validator_agent_id(tmp_path):
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--validator-agent-id", "val-explicit",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["validator_agent_id"] == "val-explicit"


def test_main_rejects_both_identity_flags_together(tmp_path, capsys):
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(VALID),
        "--infer-agent-from", "https://a.com/x",
        "--validator-agent-id", "val-explicit",
    ])
    assert rc == 1
    assert "not both" in capsys.readouterr().err


def test_two_verdicts_recorded_in_order_get_distinct_ids(tmp_path):
    """The SKILL's Phase 3 ordering, end to end through the CLI."""
    log = []
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        log.append({"tool": "WebFetch", "url": "https://a.com/x",
                    "agent_id": agent_id, "agent_type": "validator"})
        write_fetch_log(tmp_path, log)
        assert add_verdict.main([
            "--workspace", str(tmp_path), "--infer-agent-from", "https://a.com/x",
            "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                  "validator_model": model, "quote": "q"}),
        ]) == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert [r["validator_agent_id"] for r in rows] == ["val-h1", "val-s1"]


def test_main_infers_agent_id_from_the_fetch_log(tmp_path):
    write_fetch_log(tmp_path, [
        {"tool": "WebFetch", "url": "https://a.com/x", "agent_id": "val-7", "agent_type": "validator"},
    ])
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--infer-agent-from", "https://a.com/x",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "verdicts.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["validator_agent_id"] == "val-7"


def test_main_fails_when_inference_finds_nothing(tmp_path, capsys):
    write_fetch_log(tmp_path, [])
    row = {k: v for k, v in VALID.items() if k != "validator_agent_id"}
    rc = add_verdict.main([
        "--workspace", str(tmp_path), "--json", json.dumps(row),
        "--infer-agent-from", "https://a.com/x",
    ])
    assert rc == 1
    assert "no validator" in capsys.readouterr().err.lower()
