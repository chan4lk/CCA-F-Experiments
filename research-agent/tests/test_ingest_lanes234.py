import json
from pathlib import Path


import research_agent.ingest as ingest_context

QUESTION = "ServiceNow agent via Copilot Studio MCP versus native AI Agent Studio"


def note(dir_path: Path, name: str, body: str = "Some body text.", frontmatter: str = "") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text((frontmatter + "\n" if frontmatter else "") + body, encoding="utf-8")
    return path


# --- frontmatter --------------------------------------------------------

def test_parse_frontmatter_reads_scalars_and_lists():
    text = "---\ntitle: My Note\ntags: [alpha, beta]\n---\n\nBody here.\n"
    meta, body = ingest_context.parse_frontmatter(text)
    assert meta["title"] == "My Note"
    assert meta["tags"] == ["alpha", "beta"]
    assert body.strip() == "Body here."


def test_parse_frontmatter_absent_returns_empty_meta():
    meta, body = ingest_context.parse_frontmatter("Just body.\n")
    assert meta == {}
    assert body.strip() == "Just body."


def test_parse_frontmatter_strips_quotes():
    meta, _ = ingest_context.parse_frontmatter('---\ntitle: "Quoted"\n---\nx\n')
    assert meta["title"] == "Quoted"


# --- discovery and ranking ---------------------------------------------

def test_discover_notes_finds_markdown_recursively(tmp_path):
    note(tmp_path / "a", "one.md")
    note(tmp_path / "a" / "b", "two.md")
    note(tmp_path / "a", "ignored.txt")
    found = ingest_context.discover_notes([tmp_path])
    assert {p.name for p in found} == {"one.md", "two.md"}


def test_discover_notes_skips_obsidian_config(tmp_path):
    note(tmp_path / ".obsidian", "workspace.md")
    note(tmp_path, "real.md")
    assert {p.name for p in ingest_context.discover_notes([tmp_path])} == {"real.md"}


def test_discover_notes_missing_path_is_skipped(tmp_path):
    assert ingest_context.discover_notes([tmp_path / "nope"]) == []


def test_score_note_rewards_question_terms_in_title(tmp_path):
    p = note(tmp_path, "copilot-studio-mcp.md")
    high = ingest_context.score_note(p, {"title": "Copilot Studio MCP limits"}, QUESTION)
    low = ingest_context.score_note(p, {"title": "Cafeteria menu"}, QUESTION)
    assert high > low


def test_rank_notes_respects_limit(tmp_path):
    for i in range(10):
        note(tmp_path, f"servicenow-{i}.md")
    assert len(ingest_context.rank_notes(ingest_context.discover_notes([tmp_path]), QUESTION, 3)) == 3


def test_rank_notes_is_deterministic(tmp_path):
    for i in range(6):
        note(tmp_path, f"copilot-{i}.md")
    notes = ingest_context.discover_notes([tmp_path])
    assert ingest_context.rank_notes(notes, QUESTION, 4) == ingest_context.rank_notes(notes, QUESTION, 4)


# --- the firewall -------------------------------------------------------

def test_internal_claims_are_never_material(tmp_path):
    p = note(tmp_path, "n.md", "Copilot Studio supports 200 tools per server.")
    rows = ingest_context.to_internal_claims([p], lane=2)
    assert rows[0]["tier"] == "context"


def test_internal_claims_have_internal_source_type_and_null_url(tmp_path):
    p = note(tmp_path, "n.md")
    row = ingest_context.to_internal_claims([p], lane=2)[0]
    assert row["source_type"] == "internal"
    assert row["url"] is None


def test_internal_claims_carry_the_unverified_verdict(tmp_path):
    p = note(tmp_path, "n.md")
    assert ingest_context.to_internal_claims([p], lane=2)[0]["verdict"] == "INTERNAL_UNVERIFIED"


def test_internal_claims_record_their_lane_and_path(tmp_path):
    p = note(tmp_path, "n.md")
    row = ingest_context.to_internal_claims([p], lane=3)[0]
    assert row["lane"] == 3
    assert row["source_path"] == str(p)


def test_internal_claim_ids_are_prefixed_to_avoid_ledger_collision(tmp_path):
    p = note(tmp_path, "n.md")
    assert ingest_context.to_internal_claims([p], lane=2)[0]["id"].startswith("I")


# --- CLI ----------------------------------------------------------------

def test_main_writes_internal_claims_and_report(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    ctx_dir = tmp_path / "notes"
    note(ctx_dir, "copilot-studio.md", "Prior notes on Copilot Studio.")

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(ctx_dir), "--limit", "5",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert rows and rows[0]["source_type"] == "internal"
    assert "Ingestion Report" in (ws / "ingest-report.md").read_text()


def test_main_writes_carried_claims_from_prior_run(tmp_path):
    prior = tmp_path / "research" / "prior"
    prior.mkdir(parents=True)
    (prior / "claims.jsonl").write_text(json.dumps({
        "id": "C001", "sub_q": "Q1", "tier": "material", "claim": "x",
        "url": "https://learn.microsoft.com/a", "quote": "q",
        "source_type": "vendor_doc", "fetched_at": "2026-08-20T00:00:00Z",
    }) + "\n")
    (prior / "verdicts.jsonl").write_text("".join(json.dumps(v) + "\n" for v in [
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v1",
         "validator_model": "haiku", "quote": "q"},
        {"claim_id": "C001", "verdict": "CONFIRMED", "validator_agent_id": "v2",
         "validator_model": "sonnet", "quote": "q"},
    ]))

    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION, "--prior", str(prior),
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "carried-claims.jsonl").read_text().splitlines() if l.strip()]
    assert rows[0]["needs_revalidation"] is True


def test_main_enforces_the_note_budget(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    ctx_dir = tmp_path / "notes"
    for i in range(40):
        note(ctx_dir, f"servicenow-note-{i}.md")

    ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(ctx_dir), "--limit", "25",
    ])
    rows = [l for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 25


def test_main_with_no_sources_writes_empty_ledgers(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    assert ingest_context.main(["--workspace", str(ws), "--question", QUESTION]) == 0
    assert (ws / "ingest-report.md").is_file()


def test_earlier_lane_wins_on_duplicate_note(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    shared = tmp_path / "shared"
    note(shared, "copilot.md")

    ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(shared), "--configured-vault", str(shared),
    ])
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["lane"] == 2


# --- lane 4 (repo docs/ and README.md) -----------------------------------

def test_main_discovers_lane4_repo_docs_and_readme(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    repo = tmp_path / "repo"
    note(repo / "docs", "architecture.md")
    (repo / "README.md").write_text("Project readme.", encoding="utf-8")

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--repo", str(repo),
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    names = {Path(r["source_path"]).name for r in rows}
    assert names == {"architecture.md", "README.md"}
    assert all(r["lane"] == 4 for r in rows)


def test_earlier_lane_wins_over_lane4_repo(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    repo = tmp_path / "repo"
    docs_dir = repo / "docs"
    note(docs_dir, "copilot.md")

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(docs_dir), "--repo", str(repo),
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["lane"] == 2


def test_main_repo_lane_missing_docs_and_readme_does_not_error(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    repo = tmp_path / "empty-repo"
    repo.mkdir(parents=True)

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--repo", str(repo),
    ])
    assert rc == 0
    rows = [l for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert rows == []


def test_budget_caps_lane4_after_earlier_lanes_partially_consume_it(tmp_path):
    ws = tmp_path / "research" / "run-a"
    ws.mkdir(parents=True)
    ctx_dir = tmp_path / "notes"
    for i in range(20):
        note(ctx_dir, f"context-note-{i}.md")
    repo = tmp_path / "repo"
    for i in range(10):
        note(repo / "docs", f"doc-note-{i}.md")

    rc = ingest_context.main([
        "--workspace", str(ws), "--question", QUESTION,
        "--context", str(ctx_dir), "--repo", str(repo), "--limit", "25",
    ])
    assert rc == 0
    rows = [json.loads(l) for l in (ws / "internal-claims.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 25
    by_lane: dict[int, int] = {}
    for r in rows:
        by_lane[r["lane"]] = by_lane.get(r["lane"], 0) + 1
    assert by_lane == {2: 20, 4: 5}
