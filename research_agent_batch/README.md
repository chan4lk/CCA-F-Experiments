# research_agent_batch

The same proposal-research pipeline as [`research-agent/`](../research-agent), running on the
**Message Batches API** instead of the Claude Agent SDK.

Six agents research a proposal question, every claim is verified by an independent validator
against the page it came from, a gate proves each cited page was actually retrieved, and the
result is an evidence pack plus an Obsidian vault. That part is unchanged. What changes is
the engine, and the trade is real.

```bash
python -m research_agent_batch "Can Copilot Studio host our claims-triage assistant?" \
  --client "Northwind Mutual" --audience "technical buyer"
#   plan: submitted batch msgbatch_01A — 1 request, round 1
#   ...exits. The batch runs.

python -m research_agent_batch status     # what it is waiting on
python -m research_agent_batch resume     # collect, advance, submit the next round
python -m research_agent_batch resume --wait   # or sit and poll until it blocks
```

---

## The trade

| | `research-agent` (Agent SDK) | this (Batches API) |
|---|---|---|
| **Cost** | list price | **50% of list price**, on every request |
| **Latency** | a turn is seconds | a turn is one batch: usually minutes, up to 24 hours |
| **Agent loop** | the SDK provides it | **there isn't one** — rebuilt here, one round per batch |
| **Tools** | built in (WebSearch, WebFetch, Bash, MCP) | **none** — implemented in this repo and executed locally |
| **Parallelism** | ~8 concurrent dispatches | every request in a wave runs at once |
| **Survives a closed laptop** | no | yes — `batch-state.json` and `resume` |
| **max_tokens** | capped by HTTP timeouts | unconstrained; nothing is held open |

The headline is the loop. A batch request is a *single* Messages call: it comes back with
`stop_reason: "tool_use"` and stops. Nothing executes the tool, nothing continues the turn.
So the loop lives in `conversation.py`, and one batch carries the next turn of **every agent
still working**:

```
round 1  [ 9 researchers ]  -> 9 tool_use          -> we search and fetch
round 2  [ 9 researchers ]  -> 6 tool_use, 3 done  -> we fetch
round 3  [ 6 researchers ]  -> ...
```

Nine researchers taking six turns each is **six batches, not fifty-four requests** — and each
one is billed at half price.

---

## What executing our own tools buys

`tools/fetch.py` and `tools/search.py` are the tools. Because this process performs every
retrieval, three things that were awkward elsewhere become straightforward:

**Provenance is an observation, not a reconstruction.** The gate proves a validator opened
the page it ruled on by joining `fetch-log.jsonl` against `verdicts.jsonl`. The plugin
recovered those rows from a hook keyed by a session id — a mis-registration silently emptied
the log and failed every claim an hour later. Here a row is written when the socket closes.

**Blindness is enforced before the request, not asked for in prose.** A validator's
`web_fetch` is pinned to the cited URL's host; anything else comes back refused, and nothing
is retrieved, so nothing is logged. It is given no `web_search` at all — searching is how a
validator finds a friendlier source than the one it was asked about.

**A PDF is just bytes.** 57% of the claims in the plugin's first real run cited PDFs, and
`WebFetch` cannot decode one — which is the entire reason its validator had to hold `Bash`,
reopening the hole that removing `Read` had closed. Fetching here means `pypdf` handles it
and the validator needs no shell.

---

## The pipeline

| Phase | What runs | Model | Rounds |
|---|---|---|---|
| 0 / 0.5 | intake, ingest local notes and prior runs | — | local |
| 1 | `planner` — 6-12 self-contained sub-questions | `claude-sonnet-5` | ≤2 |
| 2 | one `researcher` per sub-question, all in one batch | `claude-sonnet-5` | ≤10 |
| 3 | one `validator` per claim | `claude-haiku-4-5` | ≤4 |
| 3b | **escalation** — every material claim re-ruled on a second model | `claude-sonnet-5` | ≤4 |
| 4 | `gap-hunter` | `claude-opus-5` | ≤5 |
| 5 | `synthesizer` writes the pack | `claude-fable-5` | ≤2 |
| 6 | **the gate** — eight checks | — | local |
| 6b | the Obsidian vault | — | local |
| — | **HUMAN GATE** | — | `draft` is a separate command |
| 7 | `proposal-writer`, then the gate again over the draft | `claude-fable-5` | ≤2 |

A material claim needs two `CONFIRMED` rulings from **two different validators on two
different models**; the gate checks the ids and the models, not the row count. A failing gate
raises, and the vault is never built over a pack that did not pass — a fully rendered vault
is the artefact a reader trusts most, so one must not exist for a pack that failed.

Every round ceiling is also a wall-clock ceiling, because every round is a batch.

---

## Structured output replaced markdown parsing

Nothing here has a filesystem — a batch request returns a message and nothing else. So every
agent ends on a JSON object (`schemas.py`) that this process writes to disk, rather than
writing its own file for the orchestrator to parse afterwards. A malformed heading can no
longer cost a sub-question its researcher.

The two pack writers are handed the **whole ledger inline** — every claim, its quote, and
every ruling on it — and given no tools. That is a stronger version of the same guarantee the
SDK port makes with an empty tool list: they cannot state a fact that is not in front of them.

---

## Resuming

A batch may take 24 hours, so holding a process open is not a plan. `batch-state.json` in the
workspace holds the phase, the in-flight batch id, and every agent's conversation mid-flight.

- `research` starts a run and returns as soon as a batch is in flight
- `resume` collects a finished batch, folds its tool calls in, and submits the next round
- `status` says what phase the run is in and how much of the current batch is done
- `--wait` on `research`, `resume` or `draft` just calls the same step function in a loop

`status` and `verify` never touch the API, so they work offline.

---

## Search needs a provider

Client-side tools mean this process does the searching. In order of preference:

| Provider | Set | Notes |
|---|---|---|
| Brave | `BRAVE_SEARCH_API_KEY` | JSON API, reliable |
| Serper | `SERPER_API_KEY` | JSON API, reliable |
| DuckDuckGo | nothing | keyless fallback, HTML scraping, best-effort |

Force one with `RESEARCH_BATCH_SEARCH_PROVIDER`. A keyed provider selected without its key is
an error rather than a silent fallback, so a run cannot quietly change search backends.

Nothing downstream depends on which one ran: a search only ever produces candidate URLs, and
a claim is only ever backed by a page that was **fetched**.

---

## Layout

```
research_agent_batch/
  settings.py       model pinning, batch pricing, round ceilings, search backend
  schemas.py        the JSON object each agent ends on
  agents.py         the six roles: prompt, tool grant, model, output schema
  prompts/          one markdown prompt per role
  tools/            web_fetch and web_search, executed here
  conversation.py   one agent's conversation, advanced one turn per round
  batching.py       submit / poll / collect, and which failures are retryable
  provenance.py     fetch-log.jsonl
  state.py          batch-state.json — what makes resume possible
  orchestrator.py   the phase machine, as a step function
  cli.py            research / resume / status / draft / verify
  ledger/ gate/ vault/ ingest.py    ] vendored from research-agent,
  templates/                         ] behaviour unchanged
```

## Tests

```bash
pytest        # from research_agent_batch/
```

444 tests. 280 are the plugin's original suite, vendored with the ledger, gate, vault and
ingest code and passing unchanged. The other 164 cover what this engine adds: the client-side
tools and their domain pinning, the round-per-batch loop, batch assembly and failure
classification, the resumable state file, the phase machine, and the CLI.
