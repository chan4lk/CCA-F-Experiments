"""The tools this process executes on the model's behalf."""
import pytest
from fakes import FakeHTTP, FakeResponse

from research_agent_batch.tools import execute
from research_agent_batch.tools.fetch import (
    domain_allowed,
    fetch,
    host_of,
    html_to_text,
)
from research_agent_batch.tools.search import (
    SearchUnavailable,
    available_provider,
    search,
)

MS = "https://learn.microsoft.com/copilot/limits"


# --- domain pinning: the validator's blindness ----------------------------

def test_an_exact_host_is_allowed():
    assert domain_allowed(MS, ["learn.microsoft.com"])


def test_a_subdomain_is_allowed():
    assert domain_allowed("https://docs.learn.microsoft.com/a", ["learn.microsoft.com"])


def test_another_host_is_refused():
    assert not domain_allowed("https://example.com/a", ["learn.microsoft.com"])


def test_a_suffix_lookalike_is_refused():
    """`learn.microsoft.com.evil.com` ends with the allowed string but is not a
    subdomain of it. A naive endswith check would let it through."""
    assert not domain_allowed("https://learn.microsoft.com.evil.com/a",
                              ["learn.microsoft.com"])


def test_none_means_unrestricted_and_an_empty_list_means_nothing():
    """These are different states. Folding an empty list into "unrestricted"
    would turn a validator with no allowed host into one that can fetch the web."""
    assert domain_allowed(MS, None)
    assert not domain_allowed(MS, [])


def test_a_refused_fetch_says_what_to_do_instead():
    result = fetch("https://example.com/a", ["learn.microsoft.com"], FakeHTTP())
    assert not result.ok
    assert "outside the domains you may fetch" in result.error
    assert "Finding a different source is not your job" in result.error


def test_a_refused_fetch_never_opens_a_socket():
    """The check runs before the request, not after it. A validator that reached
    a page it may not read has already seen it, whatever we do with the bytes."""
    http = FakeHTTP()
    fetch("https://example.com/a", ["learn.microsoft.com"], http)
    assert http.requested == []


# --- reading pages --------------------------------------------------------

def test_html_becomes_text():
    assert html_to_text("<h1>Cap</h1><p>Max 10 &amp; rising</p>") == "Cap Max 10 & rising"


def test_scripts_and_styles_are_dropped():
    """Their contents are not page text, and they are the bulk of a modern page."""
    assert "alert" not in html_to_text("<p>Real</p><script>alert(1)</script>")
    assert "color" not in html_to_text("<style>a{color:red}</style><p>Real</p>")


def test_a_page_with_no_text_is_a_failure_not_an_empty_success():
    """An empty string would let a validator "read" a page and rule on nothing."""
    result = fetch(MS, None, FakeHTTP(default=FakeResponse(b"<html></html>")))
    assert not result.ok and "no readable text" in result.error


def test_an_http_error_is_reported_with_its_status():
    result = fetch(MS, None, FakeHTTP(default=FakeResponse(b"", status=404)))
    assert not result.ok and "404" in result.error


def test_a_network_failure_is_a_result_not_an_exception():
    class Broken:
        def get(self, url, **kw):
            raise OSError("connection reset")
    result = fetch(MS, None, Broken())
    assert not result.ok and "connection reset" in result.error


def test_a_long_page_is_truncated_rather_than_dropped():
    """The Agent SDK's WebFetch refuses anything oversized and returns nothing,
    which cost one run six claims to a single large PDF."""
    from research_agent_batch.settings import MAX_TEXT_CHARS
    body = ("<p>" + "word " * 200_000 + "</p>").encode()
    result = fetch(MS, None, FakeHTTP(default=FakeResponse(body)))
    assert result.ok
    assert "truncated" in result.text
    assert len(result.text) < MAX_TEXT_CHARS + 200


def test_a_pdf_is_read_as_text():
    """57% of the claims in the plugin's first real run cited PDFs, and its
    validator needed a shell to read one. Fetching here makes a PDF just bytes."""
    pypdf = pytest.importorskip("pypdf")
    import io
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    http = FakeHTTP(default=FakeResponse(buffer.getvalue(), "application/pdf"))
    result = fetch("https://x/spec.pdf", None, http)
    # A blank page has no text, so this asserts the PDF path ran at all rather
    # than the HTML path producing binary soup.
    assert not result.ok and "no readable text" in result.error


def test_a_malformed_pdf_is_reported_as_unreadable():
    http = FakeHTTP(default=FakeResponse(b"%PDF-1.4 not really", "application/pdf"))
    result = fetch("https://x/spec.pdf", None, http)
    assert not result.ok and "PDF" in result.error


@pytest.mark.parametrize("url", ["", "ftp://x/a", "javascript:alert(1)", "/etc/passwd"])
def test_only_http_urls_are_fetched(url):
    assert not fetch(url, None, FakeHTTP()).ok


def test_host_of():
    assert host_of("https://Learn.Microsoft.com/a") == "learn.microsoft.com"
    assert host_of("not a url") == ""


# --- search ---------------------------------------------------------------

def test_the_keyless_fallback_needs_no_configuration():
    assert available_provider({}) == ("duckduckgo", "")


def test_a_keyed_provider_without_its_key_is_an_error_not_a_silent_fallback():
    """Falling back would silently change which search backend a run used."""
    with pytest.raises(SearchUnavailable, match="BRAVE_SEARCH_API_KEY"):
        available_provider({"RESEARCH_BATCH_SEARCH_PROVIDER": "brave"})


def test_an_unknown_provider_names_the_ones_that_exist():
    with pytest.raises(SearchUnavailable, match="SERPER_API_KEY"):
        available_provider({"RESEARCH_BATCH_SEARCH_PROVIDER": "altavista"})


def test_a_keyed_provider_with_its_key_is_selected():
    assert available_provider({"RESEARCH_BATCH_SEARCH_PROVIDER": "brave",
                               "BRAVE_SEARCH_API_KEY": "k"}) == ("brave", "k")


def test_brave_results_are_parsed():
    import json as _json

    class BraveHTTP:
        def get(self, url, params=None, headers=None):
            assert headers["X-Subscription-Token"] == "k"
            return FakeResponse(_json.dumps({"web": {"results": [
                {"title": "Limits", "url": MS, "description": "Max 10"}]}}).encode())

    results = search("cap", BraveHTTP(),
                     {"RESEARCH_BATCH_SEARCH_PROVIDER": "brave", "BRAVE_SEARCH_API_KEY": "k"})
    assert [(r.title, r.url) for r in results] == [("Limits", MS)]


def test_a_dead_search_returns_nothing_rather_than_ending_the_turn():
    """A search that raised would kill the researcher's whole conversation."""
    class Broken:
        def get(self, *a, **kw):
            raise OSError("dns")
        def post(self, *a, **kw):
            raise OSError("dns")
    assert search("cap", Broken(), {}) == []


# --- dispatch -------------------------------------------------------------

def test_a_search_result_is_labelled_as_candidates_not_evidence(monkeypatch):
    """Quoting a search snippet is indistinguishable from inventing the quote."""
    import json as _json

    class BraveHTTP:
        def get(self, url, params=None, headers=None):
            return FakeResponse(_json.dumps({"web": {"results": [
                {"title": "Limits", "url": MS, "description": "Max 10"}]}}).encode())

    monkeypatch.setenv("RESEARCH_BATCH_SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
    outcome = execute("web_search", {"query": "cap"}, http=BraveHTTP())
    assert "candidates, not evidence" in outcome.content
    assert "Fetch a page" in outcome.content
    assert MS in outcome.content


def test_a_search_is_logged_even_when_it_returns_nothing():
    """The gate's source-mix and provenance checks read this log; a search that
    happened and found nothing is still something that happened."""
    class Empty:
        def get(self, *a, **kw):
            return FakeResponse(b"{}")
        def post(self, *a, **kw):
            return FakeResponse(b"")
    outcome = execute("web_search", {"query": "cap"}, http=Empty())
    assert [r.tool for r in outcome.retrievals] == ["web_search"]
    assert not outcome.is_error


def test_an_unknown_tool_is_an_error_result_not_a_crash():
    outcome = execute("rm_rf", {}, http=FakeHTTP())
    assert outcome.is_error and "No such tool" in outcome.content
    assert outcome.retrievals == []
