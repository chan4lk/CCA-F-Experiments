"""The orchestrator's own prose was ~500K of the ~600K context growth in the
first real run, and cache reads are turns x context. Nothing observed it.

This guard cannot *block* prose — prose is not a tool call — so it measures:
it samples the live context from the session transcript, warns the moment a
single turn balloons, and writes the curve where the gate can report it.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
GUARD = PLUGIN / "hooks" / "context_guard.py"
sys.path.insert(0, str(PLUGIN / "hooks"))
sys.path.insert(0, str(PLUGIN / "scripts"))

import context_guard  # noqa: E402
import workspace  # noqa: E402


def transcript(tmp_path, samples):
    """samples: list of (cache_read, output) per assistant turn."""
    p = tmp_path / "t.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for read, out in samples:
            fh.write(json.dumps({"type": "assistant", "message": {"usage": {
                "cache_read_input_tokens": read, "output_tokens": out}}}) + "\n")
    return p


def run(payload):
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True)


# --- reading the live context -------------------------------------------

def test_reads_the_most_recent_context_size(tmp_path):
    t = transcript(tmp_path, [(100_000, 500), (250_000, 900), (400_000, 700)])
    assert context_guard.latest_usage(t) == (400_000, 700)


def test_missing_transcript_is_not_an_error(tmp_path):
    assert context_guard.latest_usage(tmp_path / "nope.jsonl") is None


def test_reads_only_the_tail_of_a_large_transcript(tmp_path):
    """It runs on every tool call; it must not parse 10 MB each time."""
    t = transcript(tmp_path, [(i * 1000, 100) for i in range(1, 5001)])
    assert t.stat().st_size > 300_000
    assert context_guard.latest_usage(t) == (5_000_000, 100)


# --- the advisory --------------------------------------------------------

def test_a_normal_turn_says_nothing(tmp_path):
    t = transcript(tmp_path, [(100_000, 400), (103_000, 400)])
    assert context_guard.advisory(t, prev=100_000) == ""


def test_a_ballooning_turn_is_called_out(tmp_path):
    """A single turn adding 20K means a very long message was just written."""
    t = transcript(tmp_path, [(100_000, 9000), (130_000, 9000)])
    msg = context_guard.advisory(t, prev=100_000)
    assert "30,000" in msg or "30000" in msg
    assert "narrate" in msg.lower() or "prose" in msg.lower()


def test_crossing_the_ceiling_is_called_out(tmp_path):
    t = transcript(tmp_path, [(620_000, 500)])
    msg = context_guard.advisory(t, prev=619_000)
    assert "620,000" in msg or "ceiling" in msg.lower()


# --- what it records -----------------------------------------------------

def test_samples_are_appended_to_the_workspace(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    workspace.set_active_run(tmp_path, "sess-1", "run-a")
    t = transcript(tmp_path, [(250_000, 800)])
    r = run({"session_id": "sess-1", "cwd": str(tmp_path), "tool_name": "Bash",
             "transcript_path": str(t)})
    assert r.returncode == 0
    rows = workspace.read_jsonl(ws / "context-log.jsonl")
    assert rows and rows[0]["context"] == 250_000


def test_subagent_turns_are_ignored(tmp_path):
    """Subagent context is discarded when the agent finishes; only the
    orchestrator's context is re-read on every later turn."""
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    workspace.set_active_run(tmp_path, "sess-1", "run-a")
    t = transcript(tmp_path, [(250_000, 800)])
    run({"session_id": "sess-1", "cwd": str(tmp_path), "tool_name": "Bash",
         "transcript_path": str(t), "agent_id": "sub-1", "agent_type": "x:researcher"})
    assert workspace.read_jsonl(ws / "context-log.jsonl") == []


def test_no_active_run_records_nothing_and_exits_zero(tmp_path):
    t = transcript(tmp_path, [(250_000, 800)])
    r = run({"session_id": "unknown", "cwd": str(tmp_path), "tool_name": "Bash",
             "transcript_path": str(t)})
    assert r.returncode == 0


def test_never_blocks_and_never_crashes(tmp_path):
    """It runs on every tool call. A guard that raises would take down the run."""
    for payload in ["{{{", json.dumps({"session_id": "x"}), json.dumps([])]:
        r = subprocess.run([sys.executable, str(GUARD)], input=payload,
                           capture_output=True, text=True)
        assert r.returncode == 0
