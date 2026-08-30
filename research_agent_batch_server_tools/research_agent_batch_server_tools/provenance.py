"""fetch-log.jsonl — every retrieval, and which agent caused it.

The gate reads this file to prove two things: that a cited page was actually
retrieved during the run, and that the validator who ruled on a claim opened
that claim's page itself. Both checks are the difference between a citation and
a plausible-looking string.

Where the row comes from is the whole difference between the three ports:

- the plugin recovered it from a PostToolUse hook keyed by a session id, and a
  mis-registration silently emptied the log and failed every claim an hour later
- `research_agent_batch` writes it when its own socket closes, which is a direct
  observation and cannot miss
- here it is read back out of the assistant message

The third is not a reconstruction either. A server tool's retrieval is reported
in the response as a `web_fetch_tool_result` block carrying the URL that was
actually fetched and the timestamp it was fetched at — the fetcher's own account
of what it did, not the model's. The model does not write these blocks and
cannot forge one: a claim citing a page nobody fetched arrives with no matching
block, and the gate fails it.

## Redirects

`server_tool_use` carries the URL the model *asked for*; `web_fetch_result`
carries the URL the content *came from*. A vendor doc that redirects to a
regional or versioned path makes those differ, and the claim may cite either.
Both are logged, so the gate proves retrieval against whichever one the
researcher recorded rather than failing an honest citation on a redirect.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ledger.workspace import append_jsonl, utc_now


@dataclass
class Retrieval:
    """One thing Anthropic's servers fetched or searched for an agent."""

    tool: str
    url: str | None = None
    query: str | None = None
    # The URL the content came from, when a redirect made it differ from `url`.
    resolved_url: str | None = None
    retrieved_at: str = ""
    # A refused fetch or an exhausted search budget. Kept as a retrieval so the
    # run can report it, but never written to the log: nothing was retrieved.
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def urls(self) -> list[str]:
        """Every URL this retrieval proves, in the order the log should get them."""
        found = [u for u in (self.url, self.resolved_url) if u]
        return list(dict.fromkeys(found))


def _field(block: Any, name: str, default: Any = None) -> Any:
    """One field off a content block, whether it is a pydantic model or a dict."""
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)


def _error_code(content: Any) -> str:
    """The error code on a failed tool result, or "" if this one succeeded.

    A web search's successful content is a *list* of results and its failed
    content is a single error object, so the list check comes first: indexing
    an error object as a list is the shape mistake this branch exists to avoid.
    """
    if isinstance(content, list):
        return ""
    code = _field(content, "error_code")
    return str(code) if code else ""


def retrievals(message: Any) -> list[Retrieval]:
    """What running one request's server tools actually retrieved.

    Reads the response rather than a log this process kept, because this process
    performed none of it. Requests and results are paired by `tool_use_id`, the
    same id the API uses to associate them.
    """
    requested: dict[str, tuple[str, dict]] = {}
    for block in _field(message, "content") or []:
        if _field(block, "type") == "server_tool_use":
            requested[_field(block, "id") or ""] = (
                _field(block, "name") or "", _field(block, "input") or {})

    found: list[Retrieval] = []
    for block in _field(message, "content") or []:
        kind = _field(block, "type")
        if kind not in ("web_search_tool_result", "web_fetch_tool_result"):
            continue

        tool_use_id = _field(block, "tool_use_id") or ""
        _name, args = requested.get(tool_use_id, ("", {}))
        content = _field(block, "content")
        error = _error_code(content)

        if kind == "web_search_tool_result":
            found.append(Retrieval(
                tool="web_search",
                query=str(args.get("query") or "") or None,
                error=error))
            continue

        requested_url = str(args.get("url") or "") or None
        resolved = None if error else (_field(content, "url") or None)
        found.append(Retrieval(
            tool="web_fetch",
            url=requested_url,
            resolved_url=resolved if resolved != requested_url else None,
            retrieved_at=("" if error else (_field(content, "retrieved_at") or "")),
            error=error))
    return found


def record(workspace: Path, agent_id: str, agent_type: str,
           found: list[Retrieval]) -> int:
    """Log what one agent retrieved. Returns how many rows landed.

    A failed retrieval is not logged. The log is the run's proof that a page was
    read, so a row for a fetch that was refused would be a false one — and the
    gate would then pass a citation to a page nobody could open.
    """
    log = Path(workspace) / "fetch-log.jsonl"
    rows = 0
    for item in found:
        if not item.ok:
            continue
        # One row per URL: a search has none, a fetch has one, a redirected
        # fetch has the requested URL and the one it landed on.
        for url in item.urls() or [None]:
            append_jsonl(log, {
                "ts": utc_now(),
                # web_fetch/web_search rather than WebFetch/WebSearch: these are
                # the server tools' own names, not the Agent SDK harness's.
                "tool": item.tool,
                "url": url,
                "query": item.query,
                "retrieved_at": item.retrieved_at or None,
                "agent_id": agent_id,
                "agent_type": agent_type,
            })
            rows += 1
    return rows
