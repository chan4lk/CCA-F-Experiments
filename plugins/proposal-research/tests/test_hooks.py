import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import workspace  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[1]
RECORD_FETCH = PLUGIN / "hooks" / "record_fetch.py"
LEDGER_LINT = PLUGIN / "hooks" / "ledger_lint.py"
SESSION = "sess-abc-123"


def run_hook(script: Path, payload: dict):
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def fetch_log(tmp_path):
    return workspace.read_jsonl(tmp_path / "research" / "run-a" / "fetch-log.jsonl")


# --- active run pointer -------------------------------------------------

def test_set_and_get_active_run(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    assert workspace.get_active_run(tmp_path, SESSION) == "run-a"


def test_get_active_run_unknown_session_returns_none(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    assert workspace.get_active_run(tmp_path, "other") is None


def test_set_active_run_supports_concurrent_sessions(tmp_path):
    workspace.set_active_run(tmp_path, "s1", "run-a")
    workspace.set_active_run(tmp_path, "s2", "run-b")
    assert workspace.get_active_run(tmp_path, "s1") == "run-a"
    assert workspace.get_active_run(tmp_path, "s2") == "run-b"


# --- record_fetch -------------------------------------------------------

def test_webfetch_is_recorded_with_agent_id(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    result = run_hook(RECORD_FETCH, {
        "session_id": SESSION,
        "cwd": str(tmp_path),
        "tool_name": "WebFetch",
        "tool_input": {"url": "https://learn.microsoft.com/x"},
        "agent_id": "val-001",
        "agent_type": "validator",
    })
    assert result.returncode == 0
    rows = fetch_log(tmp_path)
    assert rows[0]["url"] == "https://learn.microsoft.com/x"
    assert rows[0]["agent_id"] == "val-001"
    assert rows[0]["agent_type"] == "validator"
    assert rows[0]["ts"].endswith("Z")


def test_websearch_records_query_and_null_url(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "WebSearch",
        "tool_input": {"query": "copilot studio mcp tool limit"},
        "agent_id": "res-002", "agent_type": "researcher",
    })
    rows = fetch_log(tmp_path)
    assert rows[0]["query"] == "copilot studio mcp tool limit"
    assert rows[0]["url"] is None


def test_ms_docs_fetch_is_recorded(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "mcp__microsoft_docs_mcp__microsoft_docs_fetch",
        "tool_input": {"url": "https://learn.microsoft.com/y"},
        "agent_id": "res-003", "agent_type": "researcher",
    })
    assert fetch_log(tmp_path)[0]["url"] == "https://learn.microsoft.com/y"


def test_main_session_call_records_null_agent_id(tmp_path):
    workspace.set_active_run(tmp_path, SESSION, "run-a")
    run_hook(RECORD_FETCH, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "WebFetch", "tool_input": {"url": "https://example.com"},
    })
    assert fetch_log(tmp_path)[0]["agent_id"] is None


def test_no_active_run_records_nothing_and_exits_zero(tmp_path):
    result = run_hook(RECORD_FETCH, {
        "session_id": "unknown", "cwd": str(tmp_path),
        "tool_name": "WebFetch", "tool_input": {"url": "https://example.com"},
    })
    assert result.returncode == 0
    assert not (tmp_path / "research" / "run-a" / "fetch-log.jsonl").exists()


def test_malformed_payload_exits_zero_without_crashing(tmp_path):
    result = subprocess.run(
        [sys.executable, str(RECORD_FETCH)],
        input="not json at all", capture_output=True, text=True,
    )
    assert result.returncode == 0


# --- ledger_lint --------------------------------------------------------

def test_direct_write_to_claims_ledger_is_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "claims.jsonl"),
                       "content": "{}"},
    })
    assert result.returncode == 2
    assert "add_claim.py" in result.stderr


def test_direct_edit_to_verdicts_ledger_is_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "verdicts.jsonl"),
                       "old_string": "a", "new_string": "b"},
    })
    assert result.returncode == 2
    assert "add_verdict.py" in result.stderr


def test_write_to_other_files_is_allowed(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "plan.md"),
                       "content": "# Plan"},
    })
    assert result.returncode == 0


def test_internal_claims_ledger_is_not_blocked(tmp_path):
    result = run_hook(LEDGER_LINT, {
        "session_id": SESSION, "cwd": str(tmp_path),
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "research" / "run-a" / "internal-claims.jsonl"),
                       "content": "{}"},
    })
    assert result.returncode == 0


def test_ledger_lint_malformed_payload_exits_zero(tmp_path):
    result = subprocess.run(
        [sys.executable, str(LEDGER_LINT)],
        input="{{{", capture_output=True, text=True,
    )
    assert result.returncode == 0


# --- hooks.json ---------------------------------------------------------

def test_hooks_json_registers_both_hooks():
    cfg = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    post = cfg["hooks"]["PostToolUse"]
    pre = cfg["hooks"]["PreToolUse"]
    assert "WebFetch" in post[0]["matcher"]
    assert "microsoft_docs_mcp" in post[0]["matcher"]
    assert "record_fetch.py" in post[0]["hooks"][0]["command"]
    assert "CLAUDE_PLUGIN_ROOT" in post[0]["hooks"][0]["command"]
    assert pre[0]["matcher"] == "Write|Edit"
    assert "ledger_lint.py" in pre[0]["hooks"][0]["command"]
