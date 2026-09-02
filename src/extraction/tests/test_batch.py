from conftest import Block, make_record

import batch


class Result:
    def __init__(self, type, blocks=None):
        self.type = type
        self.message = type and Message(blocks or [])


class Message:
    def __init__(self, content):
        self.content = content


class Entry:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


class FakeBatches:
    def __init__(self, entries):
        self.entries = entries
        self.created = None

    def create(self, requests):
        self.created = requests
        return type("Batch", (), {"id": "msgbatch_test"})()

    def retrieve(self, batch_id):
        return type("Batch", (), {"processing_status": "ended"})()

    def results(self, batch_id):
        return iter(self.entries)


class FakeClient:
    def __init__(self, entries=()):
        self.messages = type("M", (), {"batches": FakeBatches(list(entries))})()


def test_submit_sets_one_custom_id_per_document(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "STATE", tmp_path / "batch-state.json")
    client = FakeClient()

    batch.submit({"a": "doc a", "b": "doc b"}, doc_type="invoice", client=client)

    ids = [r["custom_id"] for r in client.messages.batches.created]
    assert ids == ["a", "b"]
    assert batch.STATE.exists()


def test_results_are_keyed_by_custom_id_not_position():
    record = make_record()
    entries = [
        Entry("second", Result("succeeded", [Block("extract_invoice", record)])),
        Entry("first", Result("succeeded", [Block("extract_invoice", record)])),
    ]
    records, failed = batch.collect("msgbatch_test", client=FakeClient(entries))

    assert set(records) == {"first", "second"}
    assert failed == []


def test_only_failures_are_reported_for_resubmission():
    record = make_record()
    entries = [
        Entry("ok", Result("succeeded", [Block("extract_invoice", record)])),
        Entry("too_long", Result("errored")),
        Entry("stale", Result("expired")),
    ]
    records, failed = batch.collect("msgbatch_test", client=FakeClient(entries))

    assert list(records) == ["ok"]
    assert failed == [("too_long", "errored"), ("stale", "expired")]


def test_batch_results_still_run_validation_and_routing():
    broken = make_record(stated_total=700.0)
    entries = [Entry("x", Result("succeeded", [Block("extract_invoice", broken)]))]
    records, _ = batch.collect("msgbatch_test", client=FakeClient(entries))

    assert records["x"]["issues"]
    assert records["x"]["decision"].needs_review
