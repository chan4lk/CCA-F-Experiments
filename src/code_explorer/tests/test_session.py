import time

import session as sessions
from scratchpad import Manifest


def test_no_prior_session_starts_fresh():
    plan = sessions.decide(None)
    assert plan.action == sessions.FRESH
    assert not plan.resuming


def test_a_manifest_without_a_session_id_starts_fresh():
    assert sessions.decide(Manifest(goal="g")).action == sessions.FRESH


def test_unchanged_files_resume_cleanly(manifest):
    plan = sessions.decide(manifest, changed_files=["README.md"])
    assert plan.action == sessions.RESUME
    assert plan.session_id == "sess-1"


def test_a_changed_analysed_file_resumes_but_says_what_moved(manifest):
    plan = sessions.decide(manifest, changed_files=["gate/verify.py", "unrelated.py"])

    assert plan.action == sessions.RESUME_WITH_CHANGES
    assert plan.changed_files == ["gate/verify.py"]
    assert plan.resuming


def test_stale_tool_results_are_not_resumed(manifest):
    manifest.updated_at = time.time() - (48 * 3600)
    plan = sessions.decide(manifest)

    assert plan.action == sessions.FRESH
    assert "stale" in plan.reason


def test_the_change_notice_scopes_the_rereading():
    notice = sessions.change_notice(["gate/verify.py"])
    assert "gate/verify.py" in notice
    assert "Re-read only these" in notice
    assert "do not re-explore" in notice.lower()
