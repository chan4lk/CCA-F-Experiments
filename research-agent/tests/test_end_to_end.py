"""Drive a whole run through the deterministic scripts with no model in the loop.

Agents are simulated by calling the same CLIs they would call, so this proves the
file contracts hold end to end: ingest -> claims -> verdicts -> pack -> gate -> vault
-> export -> ingestable by the next run.
"""
import json


import research_agent.ledger.claims as add_claim
import research_agent.ledger.verdicts as add_verdict
import research_agent.vault.build as build_vault
import research_agent.ingest as ingest_context
import research_agent.gate.verify as verify_pack
import research_agent.ledger.workspace as workspace

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

    # Phase 6b — the vault is built only after the gate passes
    assert build_vault.main(["--workspace", str(ws)]) == 0
    vault = ws / "vault"
    assert (vault / "00-MOC" / "Proposal Brief.md").is_file()
    assert "### C001" in (vault / "06-Sources" / "Sources.md").read_text()


def test_fabricated_citation_is_caught_by_the_gate(tmp_path):
    """The failure this plugin exists to prevent — isolated to the one check that
    catches it.

    A naive fixture lets three checks co-fire on the same scenario:
    verdict-admission (missing the sonnet escalation pass), fetch-provenance
    (the never-fetched URL — the intended mechanism), and validator-blindness,
    which independently produces a matching "never retrieved" substring for the
    same claim. Asserting on report text alone would stay green even if
    fetch-provenance itself were gutted, because validator-blindness fires too.

    This fixture removes the other two triggers so fetch-provenance is the only
    check that CAN fail: the claim carries its full two CONFIRMED verdicts (so
    verdict-admission has nothing to object to), and it is cited only from the
    pack's appendix rather than the body — verdict-admission and
    validator-blindness both walk body citations only, so an appendix-only
    citation is invisible to them, while fetch-provenance walks every citation
    in the pack, body and appendix alike. Both validators genuinely fetch a
    real, retrieved URL, so their recorded identity is real; it is only the
    claim's own cited URL that never appears in the fetch log.
    """
    ws = tmp_path / "research" / "fabricated"
    ws.mkdir(parents=True)

    pack = """# Evidence Pack: Fabrication Isolation

## Summary

This fixture isolates fetch-provenance from the checks that would otherwise co-fire.

## Unverified & excluded

The following claim cites a page that was never retrieved this session [C001].
"""

    add_claim.main(["--workspace", str(ws), "--json", json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material",
        "claim": "Copilot Studio supports 200 MCP tools per connection",
        "url": "https://learn.microsoft.com/never-fetched",  # never in the fetch log
        "quote": QUOTE, "source_type": "vendor_doc",
    })])
    for agent_id, model in [("val-h1", "haiku"), ("val-s1", "sonnet")]:
        simulate_fetch(ws, agent_id, "validator")  # fetches the real URL, not the claim's
        add_verdict.main(["--workspace", str(ws), "--infer-agent-from", URL,
                          "--json", json.dumps({"claim_id": "C001", "verdict": "CONFIRMED",
                                                "validator_model": model, "quote": QUOTE})])
    (ws / "evidence-pack.md").write_text(pack, encoding="utf-8")

    # CLI path: the gate still fails end to end.
    assert verify_pack.main(["--workspace", str(ws)]) == 1
    assert "GATE: FAIL" in (ws / "verify-report.md").read_text()

    # Structural path: exactly fetch-provenance fired, nothing else — pinned by
    # check name, not by a message substring another check could also produce.
    ctx = verify_pack.load_context(ws)
    fail_checks = {f.check for f in verify_pack.run_checks(ctx) if f.severity == verify_pack.FAIL}
    assert fail_checks == {"fetch-provenance"}


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
