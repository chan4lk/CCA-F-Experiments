"""The tools this process executes on the model's behalf.

The Batches API returns `stop_reason: "tool_use"` and stops. Nothing runs the
tool; that is the deal. So the loop lives in `conversation.py` and the work
lives here, which has one useful consequence: every retrieval passes through
this module, so provenance is recorded where it happens rather than inferred
afterwards.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import fetch as fetch_tool
from . import search as search_tool

WEB_FETCH = fetch_tool.DEFINITION
WEB_SEARCH = search_tool.DEFINITION


@dataclass
class Retrieval:
    """One thing this process fetched or searched, for the provenance log."""

    tool: str
    url: str | None = None
    query: str | None = None


@dataclass
class ToolOutcome:
    """A tool_result block plus whatever provenance running it produced."""

    content: str
    is_error: bool = False
    retrievals: list[Retrieval] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.retrievals is None:
            self.retrievals = []


def execute(name: str, args: dict[str, Any], *,
            allowed_domains: list[str] | None = None,
            http=None) -> ToolOutcome:
    """Run one tool call. Returns what to send back and what was retrieved.

    Never raises. An unknown tool, a dead host and a malformed PDF are all
    results the model can reason about; an exception here would end the agent's
    turn with an API error instead.
    """
    if name == "web_fetch":
        url = str(args.get("url") or "")
        result = fetch_tool.fetch(url, allowed_domains, http)
        retrievals = [Retrieval("web_fetch", url=url)] if result.ok else []
        if not result.ok:
            return ToolOutcome(f"Could not read {url}: {result.error}", True, retrievals)
        return ToolOutcome(f"Retrieved {url} ({result.content_type or 'text'}):\n\n"
                           f"{result.text}", False, retrievals)

    if name == "web_search":
        query = str(args.get("query") or "")
        results = search_tool.search(query, http)
        retrievals = [Retrieval("web_search", query=query)]
        if not results:
            return ToolOutcome(
                f"No results for {query!r}. Try different terms, or report this as "
                f"something you could not source.", False, retrievals)
        listing = "\n".join(
            f"{i}. {r.title}\n   {r.url}\n   {r.snippet}"
            for i, r in enumerate(results, start=1))
        return ToolOutcome(
            f"Results for {query!r} — these are candidates, not evidence. Fetch a page "
            f"before claiming anything from it.\n\n{listing}", False, retrievals)

    return ToolOutcome(f"No such tool: {name}", True, [])
