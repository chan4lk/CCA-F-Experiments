"""Reading the fetch log back out of the response.

This is the check the whole gate rests on. The sibling writes a row when its own
socket closes; here the row comes from the `web_fetch_tool_result` blocks the
response carries. Those blocks are written by Anthropic's fetcher, not by the
model, so the question these tests answer is whether this module reads them
faithfully — a row for something that was not retrieved would let the gate pass
a hallucinated citation.
"""
from fakes import Block, Message, answered, fetched, searched

from research_agent_batch_server_tools.ledger.workspace import read_jsonl
from research_agent_batch_server_tools.provenance import Retrieval, record, retrievals

URL = "https://learn.microsoft.com/en-us/copilot/limits"


def test_a_fetch_is_read_back_with_its_url():
    found = retrievals(answered("{}", fetched(URL)))
    assert [(r.tool, r.url) for r in found] == [("web_fetch", URL)]
    assert found[0].ok


def test_a_fetch_carries_the_timestamp_the_fetcher_reported():
    found = retrievals(answered("{}", fetched(URL, retrieved_at="2026-08-30T11:00:00Z")))
    assert found[0].retrieved_at == "2026-08-30T11:00:00Z"


def test_a_search_is_read_back_with_its_query():
    found = retrievals(answered("{}", searched("copilot mcp tool cap", [URL])))
    assert [(r.tool, r.query) for r in found] == [("web_search", "copilot mcp tool cap")]


def test_a_search_result_url_is_not_a_retrieval():
    """A search returns candidate URLs nobody opened. Logging one as retrieved
    would let a claim quoting a snippet pass the gate."""
    found = retrievals(answered("{}", searched("q", [URL, "https://other.example/x"])))
    assert all(r.url is None for r in found)


def test_several_tool_calls_are_paired_by_tool_use_id():
    """Results come back in message order, but the URL each one asked for lives
    on its request block — pairing by position would mislabel every row as soon
    as a search and a fetch interleave."""
    message = answered(
        "{}",
        searched("q", [URL], call_id="s1"),
        fetched(URL, call_id="f1"),
        fetched("https://example.com/b", call_id="f2"))
    found = retrievals(message)
    assert [r.url for r in found] == [None, URL, "https://example.com/b"]


# --- failures -------------------------------------------------------------

def test_a_refused_fetch_is_not_a_retrieval():
    found = retrievals(answered("{}", fetched(URL, error_code="url_not_allowed")))
    assert found[0].error == "url_not_allowed"
    assert not found[0].ok


def test_an_exhausted_search_budget_is_not_a_retrieval():
    found = retrievals(answered("{}", searched("q", error_code="max_uses_exceeded")))
    assert not found[0].ok


def test_a_search_error_object_is_not_indexed_as_a_result_list():
    """A successful search's content is a list and a failed one's is an object.
    Reading the error as a list is the shape mistake that would crash a whole
    wave on one refused search."""
    found = retrievals(answered("{}", searched("q", error_code="max_uses_exceeded")))
    assert found[0].error == "max_uses_exceeded"


def test_a_message_with_no_tool_blocks_retrieved_nothing():
    assert retrievals(answered("{}")) == []


def test_blocks_can_be_plain_dicts():
    """The state file round-trips messages as dicts, so a resumed run reads its
    retrievals off dicts rather than off SDK models."""
    message = Message([Block({"type": "server_tool_use", "id": "f1",
                              "name": "web_fetch", "input": {"url": URL}}),
                       Block({"type": "web_fetch_tool_result", "tool_use_id": "f1",
                              "content": {"type": "web_fetch_result", "url": URL}})])
    assert retrievals(message)[0].url == URL


# --- redirects ------------------------------------------------------------

def test_a_redirect_records_both_the_requested_and_the_landed_url():
    """A vendor doc that redirects to a regional path makes them differ, and the
    claim may cite either. Logging one would fail an honest citation."""
    found = retrievals(answered("{}", fetched(URL, resolved=URL + "?view=latest")))
    assert found[0].url == URL
    assert found[0].resolved_url == URL + "?view=latest"
    assert found[0].urls() == [URL, URL + "?view=latest"]


def test_no_redirect_records_one_url_not_two():
    found = retrievals(answered("{}", fetched(URL)))
    assert found[0].resolved_url is None
    assert found[0].urls() == [URL]


# --- writing the log ------------------------------------------------------

def test_a_row_names_the_agent_that_caused_it(tmp_path):
    """The gate joins on agent_id to prove a validator opened the page it ruled
    on, so a row that does not name its agent proves nothing."""
    record(tmp_path, "p3-validator-C001-a", "validator",
           retrievals(answered("{}", fetched(URL))))
    row = read_jsonl(tmp_path / "fetch-log.jsonl")[0]
    assert row["agent_id"] == "p3-validator-C001-a"
    assert row["agent_type"] == "validator"
    assert row["url"] == URL
    assert row["tool"] == "web_fetch"


def test_a_failed_retrieval_is_never_logged(tmp_path):
    """The log is the run's proof that a page was read. A row for a refused
    fetch would be a false one, and the gate would pass a citation to a page
    nobody could open."""
    written = record(tmp_path, "a", "validator",
                     retrievals(answered("{}", fetched(URL, error_code="url_not_allowed"))))
    assert written == 0
    assert not (tmp_path / "fetch-log.jsonl").exists()


def test_a_redirect_writes_a_row_for_each_url(tmp_path):
    record(tmp_path, "a", "researcher",
           retrievals(answered("{}", fetched(URL, resolved=URL + "?view=latest"))))
    urls = [r["url"] for r in read_jsonl(tmp_path / "fetch-log.jsonl")]
    assert urls == [URL, URL + "?view=latest"]


def test_a_search_writes_one_row_with_no_url(tmp_path):
    record(tmp_path, "a", "researcher", retrievals(answered("{}", searched("q", [URL]))))
    rows = read_jsonl(tmp_path / "fetch-log.jsonl")
    assert len(rows) == 1
    assert rows[0]["url"] is None and rows[0]["query"] == "q"


def test_tools_are_named_for_what_actually_ran(tmp_path):
    """web_fetch, not WebFetch. Naming them after the Agent SDK's tools would
    claim a provenance this run does not have."""
    record(tmp_path, "a", "researcher",
           [Retrieval("web_fetch", url=URL), Retrieval("web_search", query="q")])
    assert {r["tool"] for r in read_jsonl(tmp_path / "fetch-log.jsonl")} == \
        {"web_fetch", "web_search"}
