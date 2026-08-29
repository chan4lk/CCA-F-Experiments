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


# --- provenance warning at append time (defect 2, found by a real run) ----

def write_fetch_log(tmp_path, urls):
    (tmp_path / "fetch-log.jsonl").write_text(
        "".join(json.dumps({"ts": "2026-08-29T09:41:00Z", "tool": "WebFetch",
                            "url": u, "query": None, "agent_id": "res-1",
                            "agent_type": "proposal-research:researcher"}) + "\n"
                for u in urls), encoding="utf-8")


def test_claim_with_a_logged_url_warns_about_nothing(tmp_path, capsys):
    write_fetch_log(tmp_path, [VALID["url"]])
    assert add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)]) == 0
    assert "PROVENANCE" not in capsys.readouterr().err


def test_claim_whose_url_was_never_fetched_warns_immediately(tmp_path, capsys):
    """A real run lost 17 claims to this, discovered an hour later at the gate.

    The researcher had used curl, which the PostToolUse hook cannot see. The
    claim is still appended — a WebFetch now makes the provenance appear
    retroactively — but the researcher is told while still in context.
    """
    write_fetch_log(tmp_path, ["https://example.com/something-else"])
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    err = capsys.readouterr().err
    assert rc == 0, "the claim must still land; this is a warning, not a rejection"
    assert "PROVENANCE" in err
    assert "WebFetch" in err
    assert VALID["url"] in err


def test_provenance_warning_ignores_fragment_and_trailing_slash(tmp_path, capsys):
    write_fetch_log(tmp_path, [VALID["url"] + "/#section"])
    add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    assert "PROVENANCE" not in capsys.readouterr().err


def test_missing_fetch_log_names_the_likely_cause(tmp_path, capsys):
    """An empty log usually means the run was never registered in .active.json.

    That failure is otherwise silent and total: every claim fails the gate.
    """
    rc = add_claim.main(["--workspace", str(tmp_path), "--json", json.dumps(VALID)])
    err = capsys.readouterr().err
    assert rc == 0
    assert "PROVENANCE" in err
    assert "active.json" in err


# --- raw_hash honesty (9 claims in a real run recorded the string "n/a") --

def test_raw_hash_may_be_omitted(tmp_path):
    """Headroom is optional; a claim without a compression hash is fine."""
    row = {k: v for k, v in VALID.items() if k != "raw_hash"}
    assert add_claim.validate_claim(row, set()) == []


def test_raw_hash_of_n_a_is_rejected(tmp_path):
    """A real run recorded 'n/a' nine times, and once
    'n/a-direct-quote-verified-on-fetched-page'. Nothing validated it."""
    for junk in ("n/a", "N/A", "none", "n/a-direct-quote-verified-on-fetched-page", "-"):
        errors = add_claim.validate_claim(dict(VALID, raw_hash=junk), set())
        assert any("raw_hash" in e for e in errors), f"{junk!r} was accepted"


def test_a_real_looking_hash_is_accepted():
    assert add_claim.validate_claim(dict(VALID, raw_hash="fa03013ee499075913dbebef"), set()) == []
