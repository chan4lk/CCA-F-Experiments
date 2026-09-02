import pytest
from scratchpad import Manifest, Scratchpad


@pytest.fixture
def pad(tmp_path):
    return Scratchpad(tmp_path / "explorer")


@pytest.fixture
def manifest():
    import time

    return Manifest(
        goal="find where the gate rejects a citation",
        session_id="sess-1",
        updated_at=time.time(),
        files_seen=["gate/verify.py", "ledger/read.py"],
        open_questions=["which of the four copies diverged"],
        findings=[{"question": "where is the gate invoked", "answer": "run.py:88", "locations": ["run.py:88"]}],
    )
