# research_agent_batch_server_tools

The same proposal-research pipeline as [`research-agent/`](../research-agent) and
[`research_agent_batch/`](../research_agent_batch), running on the **Message Batches API**
with **`web_search` and `web_fetch` as server-side tools**.

Six agents research a proposal question, every claim is verified by an independent validator
against the page it came from, a gate proves each cited page was actually retrieved, and the
result is an evidence pack plus an Obsidian vault. That part is unchanged across all three.
What changes here is one decision — *where the tool call goes* — and it turns out to move
nearly everything else.

```bash
python -m research_agent_batch_server_tools "Can Copilot Studio host our claims-triage assistant?" \
  --client "Northwind Mutual" --audience "technical buyer"
#   plan: submitted batch msgbatch_01A — 1 request
#   ...exits. The batch runs.

python -m research_agent_batch_server_tools status     # what it is waiting on
python -m research_agent_batch_server_tools resume     # collect, advance, submit the next phase
python -m research_agent_batch_server_tools resume --wait   # or sit and poll until it blocks
```

No `BRAVE_SEARCH_API_KEY`. No `SERPER_API_KEY`. An `ANTHROPIC_API_KEY` is the whole setup.

---

## The three ports

|  | `research-agent` | `research_agent_batch` | this |
|---|---|---|---|
| **Engine** | Claude Agent SDK | Batches API | Batches API |
| **Tools** | the SDK's built-ins | written and run in that repo | **Anthropic-hosted** |
| **The agent loop** | the SDK provides it | rebuilt — one batch per round | **there isn't one to rebuild** |
| **A research phase costs** | ~8 concurrent dispatches | ~6 batches | **1 batch** |
| **Search backend** | the harness's | Brave / Serper / scraped DDG | none to choose |
| **Search cost** | inside the SDK's bill | a subscription, off the ledger | **$10 / 1,000, metered** |
| **Token cost** | list price | 50% of list | 50% of list |
| **A PDF** | `WebFetch` cannot decode one | `pypdf`, in-process | the fetcher returns it |
| **Retrieval code** | none | ~300 lines | none |
| **Provenance** | a PostToolUse hook | written when its socket closes | read from the response |
| **Survives a closed laptop** | no | yes | yes |

---

## The loop is gone, not rebuilt

This is the headline, and it is worth being precise about why.

A **custom** tool ends the turn. The response comes back `stop_reason: "tool_use"`, and
something has to run the tool and send the result before the model can continue. The Agent
SDK is that something. The Batches API is not — so `research_agent_batch` builds it:

```
round 1  [ 9 researchers ]  -> 9 tool_use          -> it searches and fetches
round 2  [ 9 researchers ]  -> 6 tool_use, 3 done  -> it fetches
round 3  [ 6 researchers ]  -> ...
```

Six batches for nine researchers. Correct, and genuinely clever, and it exists because the
tools are in the wrong place.

A **server** tool does not end the turn. The search runs on Anthropic's servers, the result
is appended, and the model keeps going — all inside the one request. So:

```
round 1  [ 9 researchers ]  -> 9 answers, with every search and fetch already in them
```

**One batch.** A phase is a batch rather than a stack of them, `conversation.py` becomes
[`task.py`](research_agent_batch_server_tools/task.py), and the `http` client threaded
through the orchestrator for dispatching tools has nothing left to do and is gone.

What is left of the loop is one case. A long server-tool turn can come back
`stop_reason: "pause_turn"`, meaning *resubmit me to continue*. So a task can go round
again — but a continuation resends what came back rather than computing anything, and the
ceilings on it are 1–4 rather than 2–10.

---

## What moved, and which way

Four things move. Three of them improve; one is the honest cost of the trade, so it goes
first.

**Provenance is now observed one layer away.** The gate proves a validator opened the page
it ruled on by joining `fetch-log.jsonl` against `verdicts.jsonl`. `research_agent_batch`
writes that row when its own socket closes — an unimprovable direct observation. Here the
row is read back out of the `web_fetch_tool_result` blocks the response carries. That is
still the *fetcher's* account of what it retrieved, not the model's: the model does not
write those blocks and cannot forge one, and a claim citing a page nobody fetched arrives
with no matching block and dies at the gate. But it is a report rather than a measurement,
and it is the one guarantee this port holds slightly less tightly than its sibling.

It also handles a case the sibling does not. `server_tool_use` carries the URL the model
asked for; `web_fetch_result` carries the URL the content came from. A vendor doc that
redirects to a regional path makes those differ, and the claim may cite either — so both are
logged, and an honest citation does not fail the gate on a redirect.

**Restrictions moved upstream of this repo.** A validator's `web_fetch` carries
`allowed_domains: ["learn.microsoft.com"]`, enforced before Anthropic's fetcher opens a
socket. It is given no `web_search` at all, so there is no searching to be talked into. The
sibling enforces both in its own dispatcher, which is equally sound and requires trusting
this repo's code; here the enforcement is in front of it.

**A whole class of failure stopped existing.** No search provider to choose, no key to
forget, no HTML scraper to break when a lite endpoint changes its markup, no `pypdf`, no
10 MB fetch ceiling. About 300 lines of retrieval code and its entire test surface are not
here, because there is nothing to test.

**The search bill became visible.** The sibling's searches are paid for by a Brave
subscription that never appears in its cost report, which makes its reported figure look
lower than its real one. Here searching is $10 per 1,000 requests, counted per run and
reported alongside the tokens.

---

## What bounds an agent now

The sibling bounds a researcher with a round ceiling: ten turns, ten batches, and it can
stop the loop at any of them. Nothing here can interrupt a request once it is in a batch —
the model searches, reads, searches again and answers without this process seeing any of it.

So the brake is a budget stated up front, in
[`settings.py`](research_agent_batch_server_tools/settings.py):

| Role | `web_search` | `web_fetch` |
|---|---|---|
| researcher | 8 | 15 |
| validator | — | 3 |
| gap-hunter | 6 | — |

Exceeding one is not an error: the tool comes back refused and the model answers with what
it has. A researcher that hits the ceiling reports fewer claims and lists the rest in
`could_not_source`, which is the correct outcome. Each prompt says so, because an agent that
discovers its budget by running out has already wasted the last of it.

`max_content_tokens` caps what a single page may cost, for the same reason: a fetched page
is input tokens on every subsequent turn of the same request, so one 400-page PDF would
otherwise spend the budget for the ten pages after it.

---

## Two variants of each tool

`web_search_20260209` / `web_fetch_20260209` filter results dynamically and run only on some
models; the `_20250305` / `_20250910` variants run everywhere. Roles are paired with models
independently of this, so the variant is chosen from the **model**, in
[`servertools.py`](research_agent_batch_server_tools/servertools.py) — the validator's haiku
pass gets the basic fetch tool and the sonnet escalation pass gets the filtering one, from
the same role and the same prompt. An unrecognised model gets the basic tools rather than a
400.

One flag is never set. `citations` on `web_fetch` makes the API return cited text blocks,
which is a 400 alongside `output_config.format` — and every agent here ends on a structured
object. The pack's citations come from the ledger's claim ids instead, which is the only
kind this pipeline trusts: a citation that survives the gate has a fetch-log row behind it.

---

## The pipeline

| Phase | What runs | Model | Batches |
|---|---|---|---|
| 0 / 0.5 | intake, ingest local notes and prior runs | — | local |
| 1 | `planner` — 6-12 self-contained sub-questions | `claude-sonnet-5` | 1 |
| 2 | one `researcher` per sub-question, all in one batch | `claude-sonnet-5` | 1 |
| 3 | one `validator` per claim | `claude-haiku-4-5` | 1 |
| 3b | **escalation** — every material claim re-ruled on a second model | `claude-sonnet-5` | 1 |
| 4 | `gap-hunter` | `claude-opus-5` | 1 |
| 5 | `synthesizer` writes the pack | `claude-fable-5` | 1 |
| 6 | **the gate** — eight checks | — | local |
| 6b | the Obsidian vault | — | local |
| — | **HUMAN GATE** | — | `draft` is a separate command |
| 7 | `proposal-writer`, then the gate again over the draft | `claude-fable-5` | 1 |

One batch per phase, plus a gap round's worth if the gap hunter finds something, plus a
continuation if a turn pauses. A material claim needs two `CONFIRMED` rulings from **two
different validators on two different models**; the gate checks the ids and the models, not
the row count. A failing gate raises, and the vault is never built over a pack that did not
pass — a fully rendered vault is the artefact a reader trusts most, so one must not exist
for a pack that failed.

---

## Structured output replaced markdown parsing

Nothing here has a filesystem — a batch request returns a message and nothing else. So every
agent ends on a JSON object ([`schemas.py`](research_agent_batch_server_tools/schemas.py))
that this process writes to disk, rather than writing its own file for the orchestrator to
parse afterwards. A malformed heading can no longer cost a sub-question its researcher.

The two pack writers are handed the **whole ledger inline** — every claim, its quote, and
every ruling on it — and given no tools at all. They cannot state a fact that is not in
front of them.

---

## Resuming

A batch may take 24 hours, so holding a process open is not a plan. `batch-state.json` in
the workspace holds the phase, the in-flight batch id, and every agent's request mid-flight.

- `research` starts a run and returns as soon as a batch is in flight
- `resume` collects a finished batch and submits the next phase
- `status` says what phase the run is in and how much of the current batch is done
- `--wait` on `research`, `resume` or `draft` just calls the same step function in a loop

`status` and `verify` never touch the API, so they work offline.

---

## Layout

```
research_agent_batch_server_tools/
  settings.py       model pinning, batch + search pricing, tool budgets, continuation ceilings
  servertools.py    the grants: tool type per model, domain pins, what is never set
  schemas.py        the JSON object each agent ends on
  agents.py         the six roles: prompt, tool grant, model, output schema
  prompts/          one markdown prompt per role
  task.py           one agent, as one request — and the pause_turn case
  batching.py       submit / poll / collect, and which failures are retryable
  provenance.py     fetch-log.jsonl, read back out of the response
  state.py          batch-state.json — what makes resume possible
  orchestrator.py   the phase machine, as a step function
  cli.py            research / resume / status / draft / verify
  ledger/ gate/ vault/ ingest.py    ] vendored from research-agent,
  templates/                         ] behaviour unchanged
```

There is no `tools/` directory. That is the port.

## Tests

```bash
pytest        # from research_agent_batch_server_tools/
```

476 tests. 280 are the plugin's original suite, vendored with the ledger, gate, vault and
ingest code and passing unchanged. The rest cover what this engine adds and what it removes:
the grants and their two variants, the domain pin, the flags that must never be set, reading
retrievals back out of a response, the `pause_turn` continuation, batch assembly and failure
classification, the resumable state file, the phase machine, and the CLI.
