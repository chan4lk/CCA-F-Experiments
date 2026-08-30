import json
import sys
from pathlib import Path


import research_agent_batch_server_tools.ledger.workspace as workspace


def test_slugify_lowercases_and_hyphenates():
    assert workspace.slugify("ServiceNow Agent vs Copilot Studio!") == "servicenow-agent-vs-copilot-studio"


def test_slugify_collapses_runs_and_trims():
    assert workspace.slugify("  AML   solutions -- for  banks  ") == "aml-solutions-for-banks"


def test_slugify_truncates_to_60_chars():
    assert len(workspace.slugify("word " * 40)) <= 60


def test_workspace_root_is_research_slug_under_cwd(tmp_path):
    root = workspace.workspace_root(tmp_path, "my-slug")
    assert root == tmp_path / "research" / "my-slug"


def test_ensure_workspace_creates_directory(tmp_path):
    root = workspace.ensure_workspace(tmp_path / "research" / "s")
    assert root.is_dir()


def test_append_and_read_jsonl_roundtrip(tmp_path):
    p = tmp_path / "claims.jsonl"
    workspace.append_jsonl(p, {"id": "C001", "claim": "a"})
    workspace.append_jsonl(p, {"id": "C002", "claim": "b"})
    rows = workspace.read_jsonl(p)
    assert [r["id"] for r in rows] == ["C001", "C002"]


def test_append_jsonl_creates_parent_directories(tmp_path):
    p = tmp_path / "deep" / "nested" / "claims.jsonl"
    workspace.append_jsonl(p, {"id": "C001"})
    assert p.is_file()


def test_read_jsonl_skips_blank_lines(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "C001"}\n\n{"id": "C002"}\n')
    assert len(workspace.read_jsonl(p)) == 2


def test_read_jsonl_missing_file_returns_empty(tmp_path):
    assert workspace.read_jsonl(tmp_path / "nope.jsonl") == []


def test_read_jsonl_raises_on_malformed_line(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "C001"}\nNOT JSON\n')
    try:
        workspace.read_jsonl(p)
    except ValueError as exc:
        assert "line 2" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_utc_now_is_iso_z():
    v = workspace.utc_now()
    assert v.endswith("Z") and "T" in v and len(v) == 20


def test_constants_match_spec():
    assert workspace.VERDICTS == {
        "CONFIRMED", "CONTRADICTED", "NOT_FOUND", "MISLEADING", "INTERNAL_UNVERIFIED",
    }
    assert workspace.TIERS == {"material", "context"}
    assert workspace.SOURCE_TYPES == {
        "vendor_doc", "regulator", "analyst", "blog", "forum", "internal",
    }


def test_claim_id_regex_matches_padded_ids():
    assert workspace.CLAIM_ID_RE.fullmatch("C012")
    assert workspace.CLAIM_ID_RE.fullmatch("C1234")
    assert not workspace.CLAIM_ID_RE.fullmatch("C12")
    assert not workspace.CLAIM_ID_RE.fullmatch("X012")


# --- shared url normalisation (one implementation, three call sites) ------

def test_normalize_url_strips_fragment_and_trailing_slash():
    assert workspace.normalize_url("https://a.com/x/#frag") == "https://a.com/x"
    assert workspace.normalize_url("https://a.com/x") == "https://a.com/x"


def test_normalize_url_handles_none_empty_and_whitespace():
    assert workspace.normalize_url(None) == ""
    assert workspace.normalize_url("") == ""
    assert workspace.normalize_url("   ") == ""
    assert workspace.normalize_url("  https://a.com/x  ") == "https://a.com/x"


def test_gate_verdict_cli_and_ingester_share_one_normalizer():
    """All three joined on URLs with their own copy; drift would be invisible."""
    import research_agent_batch_server_tools.gate.verify as verify_pack
    import research_agent_batch_server_tools.ingest as ingest_context
    import research_agent_batch_server_tools.ledger.verdicts as add_verdict
    assert verify_pack.normalize_url is workspace.normalize_url
    assert add_verdict.normalize_url is workspace.normalize_url
    assert ingest_context.normalize_url is workspace.normalize_url


# --- fence state ---------------------------------------------------------

def test_iter_fence_state_marks_fenced_lines_and_the_fences_themselves():
    text = "before\n```\ncode\n```\nafter"
    assert list(workspace.iter_fence_state(text)) == [
        ("before", False), ("```", True), ("code", True), ("```", True), ("after", False),
    ]


def test_iter_fence_state_closes_on_a_lone_closing_fence():
    """A closing fence preceded by a blank line must still close the block."""
    text = "```\ncode\n\n```\nafter"
    states = dict(zip(range(5), [s for _, s in workspace.iter_fence_state(text)]))
    assert states[4] is False


def test_iter_fence_state_handles_language_tagged_fences():
    text = "```python\ncode\n```\nafter"
    assert list(workspace.iter_fence_state(text))[-1] == ("after", False)


def test_iter_fence_state_on_empty_text():
    assert list(workspace.iter_fence_state("")) == []
    assert list(workspace.iter_fence_state(None)) == []
