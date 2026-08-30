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


# --- the grant is checked here too, not only in the request ---------------

def test_a_tool_outside_the_grant_is_refused():
    """The name in a tool_use block is model-supplied. In normal operation a
    validator is never offered web_search, but a dispatcher that runs whatever
    it is named is one enforcement layer, and the design claims two."""
    outcome = execute("web_search", {"query": "cap"},
                      granted=["web_fetch"], http=FakeHTTP())
    assert outcome.is_error
    assert "not one of your tools" in outcome.content
    assert outcome.retrievals == []


def test_a_refused_tool_never_runs():
    """Refusing after the search has happened would leave the model told 'no'
    and the query already sent."""
    http = FakeHTTP()
    execute("web_search", {"query": "cap"}, granted=["web_fetch"], http=http)
    assert http.requested == []


def test_a_granted_tool_runs():
    outcome = execute("web_fetch", {"url": MS}, granted=["web_fetch"], http=FakeHTTP())
    assert not outcome.is_error
    assert [r.tool for r in outcome.retrievals] == ["web_fetch"]


def test_an_empty_grant_permits_nothing():
    """An agent with no tools is not an agent with every tool."""
    assert execute("web_fetch", {"url": MS}, granted=[], http=FakeHTTP()).is_error


def test_no_grant_means_unrestricted_for_direct_calls():
    """`None` and `[]` are different states here for the same reason they are in
    domain_allowed."""
    assert not execute("web_fetch", {"url": MS}, granted=None, http=FakeHTTP()).is_error


# --- the private network is not the web -----------------------------------

def only(address):
    return lambda _host: [address]


@pytest.mark.parametrize("address,what", [
    ("127.0.0.1", "loopback"),
    ("169.254.169.254", "the cloud metadata endpoint"),
    ("10.0.0.5", "RFC1918"),
    ("192.168.1.1", "RFC1918"),
    ("172.16.0.1", "RFC1918"),
    ("0.0.0.0", "unspecified"),
    ("::1", "IPv6 loopback"),
    ("fd00::1", "IPv6 unique-local"),
])
def test_an_internal_destination_is_refused(address, what):
    """The fetch URL is model-chosen and the model's choices come from pages it
    just read off the open web, so a prompt injection on any of them is a path
    to this address."""
    result = fetch("https://internal.example/x", None, FakeHTTP(), resolve=only(address))
    assert not result.ok, what
    assert "not a public internet host" in result.error


def test_an_internal_destination_never_opens_a_socket():
    http = FakeHTTP()
    fetch("https://internal.example/x", None, http, resolve=only("169.254.169.254"))
    assert http.requested == []


def test_a_public_destination_is_fetched():
    result = fetch(MS, None, FakeHTTP(), resolve=only("93.184.216.34"))
    assert result.ok


def test_one_private_address_among_public_ones_is_refused():
    """Every address, not the first. A host answering with both is a bypass, not
    a partial success."""
    result = fetch(MS, None, FakeHTTP(),
                   resolve=lambda _host: ["93.184.216.34", "127.0.0.1"])
    assert not result.ok and "not a public internet host" in result.error


def test_a_host_that_does_not_resolve_is_refused():
    def broken(_host):
        raise OSError("NXDOMAIN")
    assert not fetch(MS, None, FakeHTTP(), resolve=broken).ok


def test_a_literal_private_ip_in_the_url_is_refused():
    """No DNS involved; the guard still has to see it."""
    result = fetch("http://127.0.0.1:8080/admin", None, FakeHTTP(),
                   resolve=lambda host: [host])
    assert not result.ok and "not a public internet host" in result.error


# --- redirects do not launder a destination -------------------------------

def redirect(to, status=302):
    return FakeResponse(b"", status=status, location=to)


PAGE = FakeResponse(b"<p>A maximum of 10 tools is supported.</p>")


def test_a_redirect_is_followed_and_the_final_url_recorded():
    http = FakeHTTP(pages={MS: redirect("https://learn.microsoft.com/copilot/limits2"),
                           "https://learn.microsoft.com/copilot/limits2": PAGE})
    result = fetch(MS, None, http, resolve=only("93.184.216.34"))
    assert result.ok
    assert result.final_url == "https://learn.microsoft.com/copilot/limits2"


def test_a_redirect_off_the_pinned_host_is_refused():
    """The validator's one independence guarantee. A redirect that escaped it
    would have the validator ruling on a page it was never allowed to read."""
    http = FakeHTTP(pages={MS: redirect("https://evil.example/copy")})
    result = fetch(MS, ["learn.microsoft.com"], http, resolve=only("93.184.216.34"))
    assert not result.ok
    assert "outside the domains you may fetch" in result.error


def test_a_refused_redirect_target_is_never_requested():
    """Checking response.history after the fact would mean the request to the
    disallowed host had already been made — which for an internal address is the
    whole of the damage."""
    http = FakeHTTP(pages={MS: redirect("https://evil.example/copy")})
    fetch(MS, ["learn.microsoft.com"], http, resolve=only("93.184.216.34"))
    assert "https://evil.example/copy" not in http.requested


def test_a_redirect_to_a_private_address_is_refused():
    http = FakeHTTP(pages={MS: redirect("http://169.254.169.254/latest/meta-data/")})
    result = fetch(MS, None, http,
                   resolve=lambda host: ["93.184.216.34"] if "microsoft" in host
                   else ["169.254.169.254"])
    assert not result.ok and "not a public internet host" in result.error


def test_a_redirect_within_the_pinned_host_is_followed():
    """The pin is a host, not a URL. A vendor doc moving to a regional path is
    the normal case and must not be refused."""
    moved = "https://learn.microsoft.com/en-us/copilot/limits"
    http = FakeHTTP(pages={MS: redirect(moved), moved: PAGE})
    result = fetch(MS, ["learn.microsoft.com"], http, resolve=only("93.184.216.34"))
    assert result.ok and result.final_url == moved


def test_a_relative_redirect_is_resolved_against_the_current_url():
    moved = "https://learn.microsoft.com/copilot/limits-v2"
    http = FakeHTTP(pages={MS: redirect("/copilot/limits-v2"), moved: PAGE})
    result = fetch(MS, ["learn.microsoft.com"], http, resolve=only("93.184.216.34"))
    assert result.ok and result.final_url == moved


def test_a_redirect_loop_ends_rather_than_hanging():
    http = FakeHTTP(default=redirect(MS))
    result = fetch(MS, None, http, resolve=only("93.184.216.34"))
    assert not result.ok and "redirects" in result.error


def test_a_redirect_logs_both_the_requested_and_the_final_url():
    """The gate proves a page was retrieved by joining on this log. A row naming
    only the requested URL would claim a page was read that was not."""
    moved = "https://learn.microsoft.com/en-us/copilot/limits"
    http = FakeHTTP(pages={MS: redirect(moved), moved: PAGE})
    outcome = execute("web_fetch", {"url": MS}, http=http)
    assert [r.url for r in outcome.retrievals] == [MS, moved]


def test_an_unredirected_fetch_logs_one_url():
    outcome = execute("web_fetch", {"url": MS}, http=FakeHTTP())
    assert [r.url for r in outcome.retrievals] == [MS]


def test_a_failed_fetch_logs_nothing():
    """A row for a page that could not be read would let the gate pass a
    citation to it."""
    outcome = execute("web_fetch", {"url": MS},
                      http=FakeHTTP(default=FakeResponse(b"", status=404)))
    assert outcome.is_error and outcome.retrievals == []
