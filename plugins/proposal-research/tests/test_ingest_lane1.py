import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ingest_context  # noqa: E402

NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
OLD = (NOW - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")

CLAIM = {
    "id": "C001", "sub_q": "Q1", "tier": "material",
    "claim": "Copilot Studio caps MCP tools at 10 per server connection",
    "url": "https://learn.microsoft.com/a",
    "quote": "A maximum of 10 tools per MCP server connection is supported.",
    "source_type": "vendor_doc", "fetched_at": FRESH,
}
CONFIRMED = [{"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v1",
              "validator_model": "haiku", "quote": "A maximum of 10 tools."},
             {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v2",
              "validator_model": "sonnet", "quote": "A maximum of 10 tools."}]


def write_workspace(tmp_path, claims, verdicts):
    ws = tmp_path / "research" / "prior-run"
    ws.mkdir(parents=True)
    (ws / "claims.jsonl").write_text("".join(json.dumps(c) + "\n" for c in claims))
    (ws / "verdicts.jsonl").write_text("".join(json.dumps(v) + "\n" for v in verdicts))
    return ws


def write_vault(tmp_path, rows):
    vault = tmp_path / "some-vault"
    (vault / "06-Sources").mkdir(parents=True)
    (vault / "06-Sources" / "ledger-export.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    return vault


# --- staleness ----------------------------------------------------------

def test_fresh_claim_is_not_stale():
    assert ingest_context.is_stale(FRESH, NOW) is False


def test_old_claim_is_stale():
    assert ingest_context.is_stale(OLD, NOW) is True


def test_exactly_ninety_days_is_not_stale():
    ts = (NOW - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert ingest_context.is_stale(ts, NOW) is False


def test_unparseable_timestamp_is_treated_as_stale():
    assert ingest_context.is_stale("not-a-date", NOW) is True


def test_missing_timestamp_is_treated_as_stale():
    assert ingest_context.is_stale(None, NOW) is True


# --- loading ------------------------------------------------------------

def test_load_prior_ledger_from_workspace(tmp_path):
    ws = write_workspace(tmp_path, [CLAIM], CONFIRMED)
    rows = ingest_context.load_prior_ledger(ws)
    assert rows[0]["id"] == "C001"
    assert len(rows[0]["verdicts"]) == 2


def test_load_prior_ledger_from_vault_export(tmp_path):
    vault = write_vault(tmp_path, [dict(CLAIM, verdicts=CONFIRMED)])
    rows = ingest_context.load_prior_ledger(vault)
    assert rows[0]["id"] == "C001"
    assert len(rows[0]["verdicts"]) == 2


def test_load_prior_ledger_missing_path_returns_empty(tmp_path):
    assert ingest_context.load_prior_ledger(tmp_path / "nope") == []


def test_verdict_with_no_claim_id_is_not_attached(tmp_path):
    ws = write_workspace(tmp_path, [CLAIM], [
        {"verdict": "CONFIRMED", "validator_agent_id": "v1"},  # Missing claim_id
    ])
    rows = ingest_context.load_prior_ledger(ws)
    assert rows[0]["verdicts"] == []


def test_claim_with_no_id_is_skipped(tmp_path):
    claim_no_id = dict(CLAIM, id=None)
    ws = write_workspace(tmp_path, [claim_no_id], CONFIRMED)
    rows = ingest_context.load_prior_ledger(ws)
    assert len(rows) == 0


# --- carry forward ------------------------------------------------------

def test_confirmed_claim_is_carried(tmp_path):
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED, _slug="prior-run")], NOW)
    assert len(rows) == 1
    assert rows[0]["url"] == CLAIM["url"]
    assert rows[0]["origin"]["claim_id"] == "C001"
    assert rows[0]["origin"]["slug"] == "prior-run"


def test_every_carried_claim_needs_revalidation(tmp_path):
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED)], NOW)
    assert rows[0]["needs_revalidation"] is True


def test_fresh_carried_claim_is_not_flagged_stale():
    rows = ingest_context.carry_forward([dict(CLAIM, verdicts=CONFIRMED)], NOW)
    assert rows[0]["stale"] is False


def test_old_carried_claim_is_flagged_stale():
    rows = ingest_context.carry_forward(
        [dict(CLAIM, fetched_at=OLD, verdicts=CONFIRMED)], NOW)
    assert rows[0]["stale"] is True


def test_contradicted_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0]), dict(CONFIRMED[1], verdict="CONTRADICTED")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_not_found_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0], verdict="NOT_FOUND")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_misleading_claim_is_not_carried():
    verdicts = [dict(CONFIRMED[0], verdict="MISLEADING", caveat="preview")]
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=verdicts)], NOW) == []


def test_claim_with_no_verdicts_is_not_carried():
    assert ingest_context.carry_forward([dict(CLAIM, verdicts=[])], NOW) == []


def test_internal_claim_is_never_carried_as_public():
    row = dict(CLAIM, source_type="internal", url=None, verdicts=CONFIRMED)
    assert ingest_context.carry_forward([row], NOW) == []


def test_carried_ids_are_reassigned_sequentially():
    rows = ingest_context.carry_forward([
        dict(CLAIM, id="C007", verdicts=CONFIRMED),
        dict(CLAIM, id="C009", url="https://learn.microsoft.com/b", verdicts=CONFIRMED),
    ], NOW)
    assert [r["id"] for r in rows] == ["C001", "C002"]


def test_duplicate_urls_are_carried_once():
    rows = ingest_context.carry_forward([
        dict(CLAIM, id="C007", verdicts=CONFIRMED),
        dict(CLAIM, id="C009", verdicts=CONFIRMED),
    ], NOW)
    assert len(rows) == 1


def test_different_claims_on_same_url_are_both_carried():
    rows = ingest_context.carry_forward([
        dict(CLAIM, id="C007", claim="Copilot Studio caps MCP tools at 10", verdicts=CONFIRMED),
        dict(CLAIM, id="C009", claim="Copilot Studio enforces licensing tier", verdicts=CONFIRMED),
    ], NOW)
    assert len(rows) == 2
    assert rows[0]["claim"] == "Copilot Studio caps MCP tools at 10"
    assert rows[1]["claim"] == "Copilot Studio enforces licensing tier"
