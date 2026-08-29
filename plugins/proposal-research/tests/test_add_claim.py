import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import add_claim  # noqa: E402

VALID = {
    "id": "C001",
    "sub_q": "Q1",
    "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": "https://learn.microsoft.com/example",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc",
}


def test_valid_claim_has_no_errors():
    assert add_claim.validate_claim(dict(VALID), set()) == []


def test_missing_quote_is_rejected():
    row = dict(VALID)
    del row["quote"]
    errors = add_claim.validate_claim(row, set())
    assert any("quote" in e for e in errors)


def test_empty_quote_is_rejected():
    row = dict(VALID, quote="   ")
    assert any("quote" in e for e in add_claim.validate_claim(row, set()))


def test_null_id_is_rejected():
    assert any("id" in e for e in add_claim.validate_claim(dict(VALID, id=None), set()))


def test_null_quote_is_rejected():
    assert any("quote" in e for e in add_claim.validate_claim(dict(VALID, quote=None), set()))


def test_null_url_is_rejected():
    assert any("url" in e for e in add_claim.validate_claim(dict(VALID, url=None), set()))


def test_null_tier_is_rejected():
    assert any("tier" in e for e in add_claim.validate_claim(dict(VALID, tier=None), set()))


def test_quote_over_fifty_words_is_rejected():
    row = dict(VALID, quote=" ".join(["word"] * 51))
    assert any("50 words" in e for e in add_claim.validate_claim(row, set()))


def test_quote_of_exactly_fifty_words_is_accepted():
    row = dict(VALID, quote=" ".join(["word"] * 50))
    assert add_claim.validate_claim(row, set()) == []


def test_bad_claim_id_is_rejected():
    assert any("id" in e for e in add_claim.validate_claim(dict(VALID, id="C1"), set()))


def test_duplicate_id_is_rejected():
    errors = add_claim.validate_claim(dict(VALID), {"C001"})
    assert any("duplicate" in e.lower() for e in errors)


def test_bad_tier_is_rejected():
    assert any("tier" in e for e in add_claim.validate_claim(dict(VALID, tier="high"), set()))


def test_non_http_url_is_rejected():
    assert any("url" in e for e in add_claim.validate_claim(dict(VALID, url="file:///etc/passwd"), set()))


def test_internal_source_type_is_rejected_from_public_ledger():
    errors = add_claim.validate_claim(dict(VALID, source_type="internal"), set())
    assert any("internal" in e.lower() for e in errors)


def test_unknown_source_type_is_rejected():
    assert any("source_type" in e for e in add_claim.validate_claim(dict(VALID, source_type="tweet"), set()))


def test_main_appends_and_fills_fetched_at(tmp_path):
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 0
    rows = [json.loads(l) for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["fetched_at"].endswith("Z")


def test_main_rejects_invalid_and_writes_nothing(tmp_path, capsys):
    bad = dict(VALID)
    del bad["quote"]
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(bad)])
    assert rc == 1
    assert not (tmp_path / "claims.jsonl").exists()
    assert "quote" in capsys.readouterr().err


def test_main_rejects_duplicate_id_on_second_append(tmp_path):
    add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert rc == 1
    rows = [l for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1


def test_concurrent_appends_do_not_interleave(tmp_path):
    import concurrent.futures

    payloads = [json.dumps(dict(VALID, id=f"C{i:03d}")) for i in range(1, 41)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda p: add_claim.main(["--workspace", str(tmp_path), "--json", p]),
            payloads,
        ))
    lines = [l for l in (tmp_path / "claims.jsonl").read_text().splitlines() if l.strip()]
    rows = [json.loads(line) for line in lines]  # every line must be independently parseable
    assert len(rows) == 40
    ids = {r["id"] for r in rows}
    assert len(ids) == 40  # all distinct
    assert ids == {f"C{i:03d}" for i in range(1, 41)}
