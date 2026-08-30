"""web_search, executed here.

Server-side search would have needed no provider at all. Client-side tools mean
this process does the searching, so one has to be chosen — Brave and Serper are
key-based JSON APIs and reliable; the DuckDuckGo fallback needs no key and is
best-effort scraping, which is fine for finding candidate pages and not something
to build a pipeline's reliability on.

Nothing downstream depends on which one ran: a search only ever produces
candidate URLs, and a claim is only ever backed by a page that was fetched.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx2

from ..settings import (
    BRAVE_KEY_ENV,
    FETCH_TIMEOUT_SECONDS,
    SERPER_KEY_ENV,
    search_provider_name,
)

DEFINITION = {
    "name": "web_search",
    "description": (
        "Search the web and return candidate pages with titles, URLs and snippets. "
        "A snippet is never evidence — fetch the page before claiming anything from it."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

MAX_RESULTS = 8


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""


class SearchUnavailable(RuntimeError):
    """No usable provider. Raised at wave assembly, not mid-run."""


def _brave(query: str, key: str, client=None) -> list[Result]:
    response = _get("https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": MAX_RESULTS},
                    headers={"Accept": "application/json", "X-Subscription-Token": key},
                    client=client)
    payload = response.json()
    return [Result(r.get("title", ""), r.get("url", ""), r.get("description", ""))
            for r in (payload.get("web") or {}).get("results", [])][:MAX_RESULTS]


def _serper(query: str, key: str, client=None) -> list[Result]:
    response = _post("https://google.serper.dev/search",
                     content=json.dumps({"q": query, "num": MAX_RESULTS}),
                     headers={"X-API-KEY": key, "Content-Type": "application/json"},
                     client=client)
    payload = response.json()
    return [Result(r.get("title", ""), r.get("link", ""), r.get("snippet", ""))
            for r in payload.get("organic", [])][:MAX_RESULTS]


_DDG_ROW = re.compile(
    r'<a[^>]+class="result-link"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?<td[^>]*class="result-snippet"[^>]*>(?P<snippet>.*?)</td>',
    re.DOTALL | re.IGNORECASE)


def _duckduckgo(query: str, client=None) -> list[Result]:
    """Best-effort, no key. Parses the lite HTML endpoint."""
    from .fetch import html_to_text

    response = _post("https://lite.duckduckgo.com/lite/",
                     data={"q": query},
                     headers={"User-Agent": "Mozilla/5.0 (compatible; research-agent-batch)"},
                     client=client)
    return [
        Result(html_to_text(m.group("title")), m.group("url"),
               html_to_text(m.group("snippet")))
        for m in _DDG_ROW.finditer(response.text)
    ][:MAX_RESULTS]


def available_provider(env: dict[str, str] | None = None) -> tuple[str, str]:
    """``(provider, key)``. Raises SearchUnavailable when a keyed one has no key."""
    import os
    env = os.environ if env is None else env
    name = search_provider_name() if env is os.environ else (
        env.get("RESEARCH_BATCH_SEARCH_PROVIDER") or "duckduckgo")

    if name == "brave":
        key = env.get(BRAVE_KEY_ENV, "")
        if not key:
            raise SearchUnavailable(
                f"search provider 'brave' selected but {BRAVE_KEY_ENV} is not set")
        return name, key
    if name == "serper":
        key = env.get(SERPER_KEY_ENV, "")
        if not key:
            raise SearchUnavailable(
                f"search provider 'serper' selected but {SERPER_KEY_ENV} is not set")
        return name, key
    if name == "duckduckgo":
        return name, ""
    raise SearchUnavailable(
        f"unknown search provider {name!r}; set {BRAVE_KEY_ENV} or {SERPER_KEY_ENV}, "
        f"or leave RESEARCH_BATCH_SEARCH_PROVIDER unset for the keyless fallback")


def search(query: str, client=None, env: dict[str, str] | None = None) -> list[Result]:
    """Candidate pages for a query. Never raises: an empty list is an answer."""
    try:
        provider, key = available_provider(env)
        if provider == "brave":
            return _brave(query, key, client)
        if provider == "serper":
            return _serper(query, key, client)
        return _duckduckgo(query, client)
    except Exception:  # noqa: BLE001 — a dead search must not end the agent's turn
        return []


def _get(url, params=None, headers=None, client=None):
    if client is not None:
        return client.get(url, params=params, headers=headers)
    with httpx2.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as http:
        return http.get(url, params=params, headers=headers)


def _post(url, content=None, data=None, headers=None, client=None):
    if client is not None:
        return client.post(url, content=content, data=data, headers=headers)
    with httpx2.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as http:
        return http.post(url, content=content, data=data, headers=headers)
