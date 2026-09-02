import time

from scratchpad import Finding, Scratchpad


def test_findings_are_appended_with_their_locations(pad):
    pad.append(Finding("where is the gate", "run.py calls it before the vault build", ["run.py:88"]))
    pad.append(Finding("how many copies", "four", ["gate/verify.py:1"]))

    notes = pad.read()
    assert "run.py:88" in notes and "four" in notes


def test_an_unwritten_scratchpad_reads_empty(pad):
    assert pad.read() == ""


def test_the_manifest_round_trips(pad, manifest):
    pad.save(manifest)
    loaded = pad.load()

    assert loaded.goal == manifest.goal
    assert loaded.session_id == "sess-1"
    assert loaded.files_seen == manifest.files_seen


def test_saving_stamps_the_time(pad, manifest):
    manifest.updated_at = 0
    pad.save(manifest)
    assert pad.load().updated_at > 0


def test_a_missing_manifest_loads_as_none(tmp_path):
    assert Scratchpad(tmp_path / "empty").load() is None


def test_staleness_is_measured_from_the_last_save(manifest):
    assert not manifest.stale()
    manifest.updated_at = time.time() - (48 * 3600)
    assert manifest.stale()


def test_the_injected_summary_leads_with_conclusions(pad, manifest):
    pad.append(Finding("detail", "a long body", ["x.py:1"]))
    summary = pad.summary(manifest)

    assert summary.index("## Established") < summary.index("## Detail")
    assert "run.py:88" in summary
    assert "which of the four copies diverged" in summary


def test_the_summary_names_files_already_read(pad, manifest):
    assert "gate/verify.py" in pad.summary(manifest)
