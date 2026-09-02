# support_agent — customer support resolution

> Backlog item 4 of `docs/backlog/2026-09-02-ccar-f-scenarios.md`.
> CCAR-F Scenario 1. Domains 1 (Agentic Architecture & Orchestration), 2 (Tool Design & MCP
> Integration) and 5 (Context Management & Reliability).

**The trade:** the model decides, hooks enforce. The system prompt handles what needs judgement
about a person — is this customer asking for a human, is policy actually silent — and hooks
handle what must be true every time, like not refunding an unverified account. Putting the
second kind in the prompt gets it right almost always, and "almost always" is measured in
someone else's money.

## Run

```bash
cd src/support_agent
uv run --project ../.. pytest                    # 50 tests, no CLI, no network

PYTHONPATH=support_agent uv run --project ../.. python -m support_agent \
  "My monitor never turned up, order ORD-55121, I want my money back. priya@example.com"
```

Needs Node and the `claude` CLI on `PATH` — the Agent SDK spawns it. `SUPPORT_MODEL`
(default `claude-haiku-4-5`), `SUPPORT_REFUND_CEILING_USD` (default 500) and
`SUPPORT_BUDGET_USD` override the defaults.

## The five decisions

**Four tools, each with somewhere to point.** Tool descriptions are the only thing the model
selects on, so every one here says what it takes, what it returns, and which tool to use
instead — `get_customer` names `lookup_order`, `process_refund` names `escalate_to_human`. A
larger surface is worse, not more capable: eighteen tools makes every selection a harder
decision, and two tools that sound alike get confused with each other.

**Errors carry a category and a retry verdict.** A uniform "Operation failed" leaves the agent
guessing, so it retries a permanent failure or abandons a transient one. Every failure returns
`errorCategory` (transient / validation / business / permission), `isRetryable`, and — for
business rules — a `customerMessage` the agent can actually say out loud. The distinction that
matters most is the one that is not an error at all: a lookup matching nothing is a *successful*
query, returned as `found: false`. Conflating it with a failure makes the agent retry a working
tool or report an outage to a customer who simply has no orders.

**The prerequisite gate is a hook, not a sentence.** `process_refund` is blocked until
`get_customer` has returned exactly one verified match *in this conversation*, and blocked again
if the refund names a different customer than the verified one. Above the ceiling it is blocked
and the denial names the escalation path. These are `PreToolUse` denials — the call does not
happen. The tests assert the denial, which is the only thing worth asserting: a test that the
model chose not to call the tool proves nothing about the next conversation.

**Tool output is rewritten before the model reads it.** Three backends, three time formats, one
numeric status enum. `PostToolUse` turns unix seconds into ISO 8601, `30` into `delivered`, and
drops the twelve warehouse fields no support conversation uses — an order record carries forty,
and the rest accumulate in context at a cost proportional to what the warehouse tracks rather
than to what the case needs, pushing the customer's actual problem toward the middle of the
window where it is read least reliably.

**Case facts sit outside the summarised history.** Summarisation is lossy in precisely the wrong
direction: it keeps the shape of the conversation and condenses "£940, ORD-55121, delivered
2026-03-20" into "the customer discussed a refund". `case.py` holds the amounts, ids, statuses
and each open concern verbatim and re-injects them into the prompt. It also tracks concerns
separately, so the second one is not dropped when the first is resolved — and it is what fills
the escalation summary, because the human who takes the handoff cannot see the transcript.

## Escalation is the part that cannot be a hook

Whether a customer wants a person is a judgement, so the prompt gets what judgement needs:
explicit triggers, and worked pairs for the cases prose decides inconsistently. *"This is
ridiculous, put me through to a person"* escalates immediately — investigating first overrides
an explicit request. *"This is ridiculous, my order never arrived"* does not; frustration was
expressed, a human was not asked for. Competitor price matching escalates as a policy gap,
because silence in policy is not a no. And the prompt rules out the two proxies that feel like
signal and are not: anger, and the agent's own confidence. Both describe the agent, not the case.

## Layout

| File | Holds |
|---|---|
| `tools.py` | the four MCP tools and their descriptions |
| `errors.py` | the structured error envelope; the empty-result-is-not-an-error split |
| `hooks.py` | `Gate` (PreToolUse) and `Normalizer` (PostToolUse) |
| `normalize.py` | timestamp, status and field-trimming transforms |
| `case.py` | case facts carried outside the summarised history |
| `handoff.py` | the escalation summary the human receives |
| `prompts.py` | escalation criteria and the worked examples |
| `agent.py` | `ClaudeAgentOptions` wiring |
| `backend.py` | deliberately inconsistent stand-in for the backend systems |
