# extraction — structured data extraction

> Backlog item 1 of `docs/backlog/2026-09-02-ccar-f-scenarios.md`.
> CCAR-F Scenario 6. Domains 4 (Prompt Engineering & Structured Output) and 5 (Context
> Management & Reliability).

**The trade:** the schema is the contract, and everything the schema cannot express is a
separate layer. `tool_use` with a strict JSON schema removes syntax errors entirely — no
response is ever re-parsed from prose — which leaves a clean split: `schema.py` owns the
shape, `validate.py` owns the semantics, `review.py` owns who looks at it. A retry exists
only where a retry can help.

## Run

```bash
cd src/extraction
PYTHONPATH=extraction uv run --project ../.. python -m extraction samples/invoice_clean.txt invoice
PYTHONPATH=extraction uv run --project ../.. python -m extraction samples/receipt_sparse.txt   # type unknown
uv run --project ../.. pytest                                                                  # 42 tests, no network
```

`EXTRACTION_MODEL` (default `claude-haiku-4-5`), `EXTRACTION_REVIEW_THRESHOLD` (default `0.85`)
and `EXTRACTION_MAX_ATTEMPTS` (default `3`) override the pinned settings.

## The four decisions

**Structure is guaranteed, not requested.** `strict: true` plus `additionalProperties: false`
plus every property in `required` means `tool_use.input` validates exactly. `tool_choice` is
forced to a named tool when the document type is known, because the downstream steps assume a
shape; when the type is unknown it drops to `{"type": "any"}` — still a guaranteed tool call,
just not a guaranteed *which*. It is never `auto`: `auto` permits a conversational reply.

**The schema is designed not to induce fabrication.** Every field a real document may omit is
nullable, so absence has somewhere to go. Every categorical field carries `unclear` and
`other` + a detail string, so an ambiguous term is recorded as ambiguous instead of being
rounded to the nearest enum — `"30 days end of month"` is not `net_30`. `stated_total` and
`calculated_total` are two separate fields for one reason: a single `total` field lets the
model quietly reconcile a document that contradicts itself, and the contradiction is the
thing worth knowing.

**Retry only where retry works.** A failed extraction is resent with the document, the failed
record, and the numbered validation errors — a bare "try again" gives the model nothing to
correct against. But a field the source does not contain is not a correctable error, and
asking three more times only spends money. `validate.py` reads the model's own 0.0 confidence
on a null field as *absent from source*, marks that issue non-retryable, and the loop stops on
the first pass and routes to a human instead.

**Confidence is per field.** A 97%-accurate extractor can be 40% accurate on one field of one
document type, and a document-level score cannot show that. Fields are scored individually,
any field under the threshold sends the record to review, and `audit_sample` takes a
stratified sample of the *auto-approved* records — the population where an unnoticed error
pattern lives.

## Batch

`batch.py` is the same extraction at half the cost with no latency guarantee: right for an
overnight backlog, wrong for anything a user waits on. Two constraints shape it. The batch API
cannot run a tool loop inside one request, so the retry from `extract.py` does not exist —
a failure comes back in the next batch. And results arrive in arbitrary order, so every
document is keyed by `custom_id` and nothing is matched by position. `collect()` returns the
failures separately so a resubmission pays only for those.

## Layout

| File | Holds |
|---|---|
| `schema.py` | the two tool definitions — the output contract |
| `prompts.py` | system prompt with worked examples of the ambiguous cases; the retry prompt |
| `extract.py` | `tool_choice` selection, the single call, the retry loop |
| `validate.py` | semantic checks a schema cannot express, each tagged retryable or not |
| `review.py` | routing to auto/review, and stratified audit sampling of auto |
| `batch.py` | the Message Batches path |
