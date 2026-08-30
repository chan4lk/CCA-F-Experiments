"""The tool grants, as server-side tool definitions.

`research_agent_batch` ships `web_search` and `web_fetch` as custom tools with
input schemas, and runs them in-process. Here they are declared and nothing
else: `web_search` and `web_fetch` are Anthropic-hosted, so a request carrying
them comes back with the searching and the fetching already done.

Three things follow from that, and they are the reason this port exists.

**There is no loop.** A custom tool makes the model stop at
`stop_reason: "tool_use"` and wait for a process that the Batches API does not
provide. A server tool does not stop the turn at all — the search runs, the
result is appended, and the model keeps going inside the same request. One
request is a whole agent.

**There is no search provider.** No Brave key, no Serper key, no scraping
DuckDuckGo's lite endpoint and hoping the markup holds. That whole surface,
and the class of run that quietly changed search backends, is gone.

**A restriction is a server-side check.** `allowed_domains` on a validator's
`web_fetch` is enforced before Anthropic's fetcher opens a socket, and a
validator with no `web_search` in its grant has no searching to be talked into.
The sibling enforces both in its own dispatcher, which is equally sound and
requires trusting this repo's code; here the enforcement is upstream of it.

## Tool type variants

The dynamic-filtering variants (`_20260209`) run code execution under the hood
to filter results, and only some models support them. The basic variants run
everywhere. Roles are paired with models independently of this, so the variant
is chosen from the model rather than pinned per role — the validator runs on
haiku and gets the basic fetch tool; the researcher runs on sonnet and gets the
filtering one, for the same prompt.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# Models that accept the dynamic-filtering variants. Anything absent gets the
# basic tools, which every model supports — an unknown model degrades to the
# thing that works rather than to a 400.
DYNAMIC_FILTERING_MODELS = frozenset({
    "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-sonnet-4-6",
})

WEB_SEARCH_BASIC = "web_search_20250305"
WEB_SEARCH_FILTERING = "web_search_20260209"
WEB_FETCH_BASIC = "web_fetch_20250910"
WEB_FETCH_FILTERING = "web_fetch_20260209"

# A page's text costs input tokens on every subsequent turn of the same request,
# so an unbounded fetch of a 400-page PDF spends the budget for the ten pages
# after it. This is a ceiling, not a target.
MAX_CONTENT_TOKENS = 40_000


def supports_dynamic_filtering(model: str) -> bool:
    return model in DYNAMIC_FILTERING_MODELS


def host_of(url: str) -> str:
    """The host a URL lives on, which is what `allowed_domains` takes.

    `allowed_domains` matches a host and its subdomains, so pinning a validator
    to `learn.microsoft.com` lets it follow a path redirect on that host and
    stops it at a hop to anywhere else — including the vendor's own blog, which
    is exactly the friendlier source it must not go looking for.
    """
    return (urlparse(url).hostname or "").lower()


def web_search(model: str, *, max_uses: int,
               allowed_domains: list[str] | None = None) -> dict[str, Any]:
    """A `web_search` grant for `model`."""
    tool: dict[str, Any] = {
        "type": WEB_SEARCH_FILTERING if supports_dynamic_filtering(model)
        else WEB_SEARCH_BASIC,
        "name": "web_search",
        "max_uses": max_uses,
    }
    if allowed_domains:
        tool["allowed_domains"] = list(allowed_domains)
    return tool


def web_fetch(model: str, *, max_uses: int,
              allowed_domains: list[str] | None = None) -> dict[str, Any]:
    """A `web_fetch` grant for `model`.

    `citations` is deliberately never set. Enabling it makes the API return
    cited text blocks, which is a 400 alongside `output_config.format` — and
    every agent here ends on a structured object. The pack's citations come
    from the ledger's claim ids, which is the only kind this pipeline trusts:
    a citation that survives to the gate has a fetch log row behind it.

    One constraint this tool carries that the sibling's fetcher does not: it
    will only fetch a URL that is **already in the conversation**. It cannot be
    handed an invented address. That is why the researcher must search before it
    fetches — search results put the URLs in the turn — and why the validator's
    one URL is stated in its prompt rather than left for it to reconstruct.
    """
    tool: dict[str, Any] = {
        "type": WEB_FETCH_FILTERING if supports_dynamic_filtering(model)
        else WEB_FETCH_BASIC,
        "name": "web_fetch",
        "max_uses": max_uses,
        "max_content_tokens": MAX_CONTENT_TOKENS,
    }
    if allowed_domains:
        tool["allowed_domains"] = list(allowed_domains)
    return tool

