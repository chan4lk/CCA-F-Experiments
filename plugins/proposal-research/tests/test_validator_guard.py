"""The validator keeps Bash (57% of a real run's claims cited PDFs, which
WebFetch cannot decode) but must not use it to reach the ledger.

Before this guard, blindness was enforced by tool restriction: no Bash meant
no path to the researcher's quote. Granting Bash reduced that to instruction.
This hook restores mechanical enforcement.
"""
import json
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
GUARD = PLUGIN / "hooks" / "validator_guard.py"
VALIDATOR = "proposal-research:validator"


def run(payload: dict):
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True)


def bash(command: str, agent_type=VALIDATOR):
    return run({"tool_name": "Bash", "tool_input": {"command": command},
                "agent_id": "val-1", "agent_type": agent_type})


# --- what the validator must not do -------------------------------------

def test_validator_cannot_cat_the_claim_ledger():
    r = bash("cat research/run-a/claims.jsonl")
    assert r.returncode == 2
    assert "ledger" in r.stderr.lower() or "workspace" in r.stderr.lower()


def test_validator_cannot_grep_the_workspace_by_any_path():
    assert bash("grep -r C012 /Users/me/repo/research/run-a/").returncode == 2


def test_validator_cannot_read_verdicts():
    assert bash("head -5 research/run-a/verdicts.jsonl").returncode == 2


def test_validator_cannot_websearch():
    r = run({"tool_name": "WebSearch", "tool_input": {"query": "friendlier source"},
             "agent_id": "val-1", "agent_type": VALIDATOR})
    assert r.returncode == 2
    assert "search" in r.stderr.lower()


def test_validator_cannot_use_the_read_tool():
    r = run({"tool_name": "Read", "tool_input": {"file_path": "/x/claims.jsonl"},
             "agent_id": "val-1", "agent_type": VALIDATOR})
    assert r.returncode == 2


def test_bare_agent_type_is_guarded_too():
    assert bash("cat research/run-a/claims.jsonl", agent_type="validator").returncode == 2


# --- what the validator must still be able to do -------------------------

def test_validator_may_curl_a_pdf():
    """The whole reason Bash was granted."""
    assert bash("curl -sL https://example.com/circular.pdf -o /tmp/c.pdf").returncode == 0


def test_validator_may_convert_a_pdf_in_temp():
    assert bash("pdftotext /tmp/c.pdf - | head -100").returncode == 0


# --- everyone else is unaffected -----------------------------------------

def test_researcher_may_append_to_the_ledger():
    """Researchers call add_claim.py --workspace research/... constantly."""
    r = bash("python3 scripts/add_claim.py --workspace research/run-a --json '{}'",
             agent_type="proposal-research:researcher")
    assert r.returncode == 0


def test_researcher_may_search():
    r = run({"tool_name": "WebSearch", "tool_input": {"query": "aml sri lanka"},
             "agent_id": "res-1", "agent_type": "proposal-research:researcher"})
    assert r.returncode == 0


def test_main_session_is_unaffected():
    r = bash("cat research/run-a/claims.jsonl", agent_type=None)
    assert r.returncode == 0


def test_malformed_payload_allows_rather_than_blocks():
    """An unidentifiable agent cannot be judged a validator, so allow.

    Failing closed here would block every write in the session on a parse bug.
    """
    r = subprocess.run([sys.executable, str(GUARD)], input="{{{",
                       capture_output=True, text=True)
    assert r.returncode == 0
