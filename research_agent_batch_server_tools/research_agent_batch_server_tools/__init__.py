"""proposal-research on the Message Batches API, with the tools on the server.

The third port of the same six-agent pipeline. `research-agent` runs it on the
Claude Agent SDK; `research_agent_batch` runs it on the Message Batches API with
`web_search` and `web_fetch` implemented and executed in that repo. This one
runs it on the Batches API with those two tools declared as **server tools**, so
Anthropic's servers do the searching and the fetching.

The pipeline, the ledgers and the gate are identical across all three. What
changes is where the tool call goes, and that one decision moves nearly
everything else:

- **The agent loop disappears.** A custom tool stops the turn at
  `stop_reason: "tool_use"` and the Batches API provides nothing to continue it,
  so the sibling rebuilds the loop and spends one batch per round. A server tool
  does not stop the turn: the search runs inside the request. One agent is one
  request, and a phase is one batch.
- **The tools disappear.** No fetcher, no HTML-to-text, no PDF extraction, no
  Brave key, no Serper key, no scraping DuckDuckGo's lite endpoint. Roughly 300
  lines of retrieval code, and the class of run that quietly changed search
  backends, are gone.
- **The restrictions move upstream.** A validator's `allowed_domains` is a field
  on the tool definition the API enforces, rather than a check this repo's
  dispatcher makes.
- **Provenance moves too**, and this is the only trade that runs the other way.
  The sibling writes a fetch-log row when its own socket closes. Here the row is
  read out of the `web_fetch_tool_result` blocks the response carries — still
  the fetcher's account of what it retrieved rather than the model's, and still
  unforgeable by the model, but observed one layer further away.

The cost moves both ways as well: the token side is 50% off like any batch
request, and searching becomes a metered line item instead of a search
subscription paid off the books.
"""
from __future__ import annotations

__version__ = "0.1.0"
