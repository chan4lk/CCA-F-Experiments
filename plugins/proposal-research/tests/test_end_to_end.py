"""Drive a whole run through the deterministic scripts with no model in the loop.

Agents are simulated by calling the same CLIs they would call, so this proves the
file contracts hold end to end: ingest -> claims -> verdicts -> pack -> gate -> vault
-> export -> ingestable by the next run.
"""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import add_claim  # noqa: E402
import add_verdict  # noqa: E402
import build_vault  # noqa: E402
import ingest_context  # noqa: E402
import verify_pack  # noqa: E402
import workspace  # noqa: E402

URL = "https://learn.microsoft.com/copilot-studio/mcp-limits"
QUOTE = "A maximum of 10 tools per MCP server connection is supported."

PACK = """# Evidence Pack: Copilot Studio MCP

## Summary

The tool cap is the binding constraint on this design [C001].

## Recommendation

Proceed with Copilot Studio, splitting tools across two server connections [C001].

## Findings

### MCP tool limits

Copilot Studio caps MCP tools at 10 per server connection [C001].

## Options

### Copilot Studio with MCP

Viable within the cap [C001].

## Constraints

### Tool cap

Ten tools per connection [C001].

## Open Questions

- Regional GA status

## Unverified & excluded

Nothing was excluded.
"""


def simulate_fetch(ws, agent_id, agent_type, url=URL):
    workspace.append_jsonl(ws / "fetch-log.jsonl", {
        "ts": workspace.utc_now(), "tool": "WebFetch", "url": url,
        "query": None, "agent_id": agent_id, "agent_type": agent_type,
    })


def test_full_run_passes_the_gate_and_builds_a_vault(tmp_path):
    ws = tmp_path / "research" / "copilot-mcp"
    ws.mkdir(parents=True)

    # Phase 0.5
    assert ingest_context.main([
        "--workspace", str(ws), "--question", "Copilot Studio MCP tool limits"]) == 0

    # Phase 2 — researcher fetches, then appends
    simulate_fetch(ws, "res-1", "researcher")
    assert add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio caps MCP tools at 10 per server connection",
        "url": URL, "quote": QUOTE, "source_type": "vendor_doc",
    })]) == 0

    # Phase 3 — haiku validator, then sonnet escalation
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        simulate_fetch(ws, agent_id, "validator")
        assert add_verdict.main([
            "--workspace", str(ws), "--infer-agent-from", URL,
            "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                  "validator_model": model, "quote": QUOTE}),
        ]) == 0

    # Phase 5
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")

    # Phase 6 — the gate must pass
    assert verify_pack.main(["--workspace", str(ws)]) == 0
    assert "GATE: PASS" in (ws / "verify-report.md").read_text()

    # Phase 5b — the vault must build with no broken links
    assert build_vault.main(["--workspace", str(ws)]) == 0
    vault = ws / "vault"
    assert (vault / "00-MOC" / "Proposal Brief.md").is_file()
    assert "### C001" in (vault / "06-Sources" / "Sources.md").read_text()


def test_fabricated_citation_is_caught_by_the_gate(tmp_path):
    """The failure this plugin exists to prevent."""
    ws = tmp_path / "research" / "fabricated"
    ws.mkdir(parents=True)

    simulate_fetch(ws, "res-1", "researcher")
    add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio supports 200 MCP tools per connection",
        "url": "https://learn.microsoft.com/never-fetched",  # never in the fetch log
        "quote": QUOTE, "source_type": "vendor_doc",
    })])
    simulate_fetch(ws, "val-h1", "validator")
    add_verdict.main(["--workspace", str(ws), "--infer-agent-from", URL,
                      "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                            "validator_model": "haiku", "quote": QUOTE})])
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")

    assert verify_pack.main(["--workspace", str(ws)]) == 1
    report = (ws / "verify-report.md").read_text()
    assert "GATE: FAIL" in report
    assert "never retrieved" in report


def test_internal_claim_cannot_reach_the_pack_as_material(tmp_path):
    """The ingestion firewall."""
    ws = tmp_path / "research" / "firewall"
    ws.mkdir(parents=True)
    rc = add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "From my own notes", "url": "https://example.com/x",
        "quote": "note text", "source_type": "internal",
    })])
    assert rc == 1
    assert not (ws / "claims.jsonl").exists()


def test_a_finished_run_seeds_the_next_one(tmp_path):
    """Runs compound: a built vault is a lane-1 source for the next run."""
    from datetime import datetime, timezone

    ws = tmp_path / "research" / "run-one"
    ws.mkdir(parents=True)
    simulate_fetch(ws, "res-1", "researcher")
    add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio caps MCP tools at 10 per server connection",
        "url": URL, "quote": QUOTE, "source_type": "vendor_doc",
    })])
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        simulate_fetch(ws, agent_id, "validator")
        add_verdict.main(["--workspace", str(ws), "--infer-agent-from", URL,
                          "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                                "validator_model": model, "quote": QUOTE})])
    (ws / "evidence-pack.md").write_text(PACK, encoding="utf-8")
    vault = build_vault.build(ws)

    carried = ingest_context.carry_forward(
        ingest_context.load_prior_ledger(vault), datetime.now(timezone.utc))
    assert len(carried) == 1
    assert carried[0]["url"] == URL
    assert carried[0]["needs_revalidation"] is True
