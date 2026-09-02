from conftest import FakeClient, make_record
from extract import extract, tool_choice


def test_known_type_forces_the_named_tool():
    assert tool_choice("invoice") == {"type": "tool", "name": "extract_invoice"}


def test_unknown_type_still_guarantees_a_tool_call():
    assert tool_choice(None) == {"type": "any"}


def test_clean_extraction_costs_one_request(record):
    client = FakeClient(("extract_invoice", record))
    result = extract("doc text", doc_type="invoice", client=client)

    assert result.attempts == 1
    assert result.decision.route == "auto"
    assert result.issues == []


def test_the_request_carries_both_tools_and_a_cached_system_prompt(record):
    client = FakeClient(("extract_invoice", record))
    extract("doc text", doc_type="invoice", client=client)

    call = client.calls[0]
    assert [t["name"] for t in call["tools"]] == ["extract_invoice", "extract_receipt"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_retry_feeds_back_the_specific_errors(record):
    broken = make_record(calculated_total=650.00, stated_total=650.00)
    client = FakeClient(("extract_invoice", broken), ("extract_invoice", record))
    result = extract("doc text", doc_type="invoice", client=client)

    assert result.attempts == 2
    assert result.issues == []

    retry = client.calls[1]["messages"][0]["content"]
    assert "calculated_total" in retry
    assert "600.0" in retry
    assert "--- DOCUMENT ---" in retry


def test_retry_pins_the_tool_chosen_on_the_first_pass(record):
    broken = make_record(issue_date="14/03/2026")
    client = FakeClient(("extract_invoice", broken), ("extract_invoice", record))
    extract("doc text", client=client)

    assert client.calls[0]["tool_choice"] == {"type": "any"}
    assert client.calls[1]["tool_choice"] == {"type": "tool", "name": "extract_invoice"}


def test_absent_information_is_not_retried():
    confidence = {**make_record()["field_confidence"], "vendor_name": 0.0}
    absent = make_record(vendor_name=None, field_confidence=confidence)
    client = FakeClient(("extract_invoice", absent))

    result = extract("doc text", doc_type="invoice", client=client)

    assert len(client.calls) == 1
    assert result.decision.route == "review"


def test_retries_stop_at_the_cap():
    broken = make_record(issue_date="14/03/2026")
    client = FakeClient(*[("extract_invoice", broken)] * 3)
    result = extract("doc text", doc_type="invoice", client=client, max_attempts=3)

    assert result.attempts == 3
    assert len(client.calls) == 3
    assert result.decision.route == "review"


def test_missing_tool_use_block_is_reported():
    client = FakeClient((None, None))
    result = extract("doc text", doc_type="invoice", client=client)

    assert result.error == "no tool_use block returned"
    assert result.record is None


def test_dotenv_is_loaded_at_import(monkeypatch):
    """A local run reads ANTHROPIC_API_KEY from .env rather than requiring it exported.

    load_dotenv() resolves the .env from this module's own directory upward, so it finds
    the repo root one whatever the cwd. The call is what is asserted; asserting on the
    key's value would print a real secret on failure.
    """
    import importlib

    import dotenv

    calls = []
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: calls.append(True))

    import extract

    import batch

    importlib.reload(extract)
    importlib.reload(batch)

    assert len(calls) == 2, "both entry modules must call load_dotenv() at import"


def test_the_model_is_pinned_to_a_full_id(monkeypatch):
    """Full ids, not aliases - an alias moves under you between runs."""
    import importlib

    import settings

    monkeypatch.delenv("EXTRACTION_MODEL", raising=False)
    importlib.reload(settings)

    assert settings.MODEL == "claude-haiku-4-5"


def test_the_model_can_be_overridden_per_run(monkeypatch):
    import importlib

    import settings

    monkeypatch.setenv("EXTRACTION_MODEL", "claude-sonnet-5")
    importlib.reload(settings)
    try:
        assert settings.MODEL == "claude-sonnet-5"
    finally:
        monkeypatch.delenv("EXTRACTION_MODEL", raising=False)
        importlib.reload(settings)
