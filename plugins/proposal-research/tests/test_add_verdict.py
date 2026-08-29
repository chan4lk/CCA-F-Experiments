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
