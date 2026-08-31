# Ledger Forensics Plugin — Design

**Date:** 2026-08-31
**Status:** Approved design, pending implementation plan
**Author:** Chandima Ranaweera (with Claude)

## Problem

An internal audit function is being given access to the MS SQL Server database behind
eFinancials, the core banking system of Mercantile Investments — a leasing, hire-purchase and
deposit-taking finance company. The audit objective is data discovery, relationship and
pattern analysis, and fraud detection across that database.

Three things make this hard, and all three are structural rather than analytical:

1. **The data cannot reach Claude.** The database holds personal data of customers,
   guarantors and staff. Nothing identifying may enter a model context hosted outside the
   institution. An instruction not to read PII is not a control; the model can read whatever
   its tools can reach.
2. **The data must not be modified, and the source system must not be disturbed.** A
   core banking database is a live production asset. An accidental `UPDATE` is a
   catastrophe; an accidental table scan during business hours is an outage.
3. **Nobody has seen the schema yet.** The plugin cannot be written against known table
   names. It must discover the schema, work out which columns hold personal data, work out
   which columns matter for fraud, and only then run detections.

A fourth problem is quieter and defeats naive designs: **anonymisation destroys the
signal.** Tokenise a NIC and `000000000V` — a placeholder identity, and a primary
ghost-lending indicator — becomes indistinguishable from a real one. Suppress a name and
"C. Ranaweera" can no longer be matched to "Chandima Ranaweera" as a duplicate borrower.
The naive pipeline of *anonymise, then analyse* silently removes several of the highest-value
fraud tests.

## Goal

A Claude Code plugin, `ledger-forensics`, that takes an undocumented core banking database
and produces an audit-grade fraud detection programme — schema map, PII classification,
canonical ontology mapping, audit scope, a parameterised fraud pattern library, executed
detections, and workpapers — under a guarantee that **no personal data enters Claude's
context at any point**.

The guarantee is enforced by database permissions first and by hooks second. Prompts
that say "do not read PII" are not the mechanism.

## Non-goals

- **Not an AML transaction monitoring system.** This is an audit tool producing exceptions
  for human investigation, not a real-time screening platform. The
  `research/aml-system-architecture-for-sri-lankan-banks-with-enterprise` evidence pack
  covers the platform question; this plugin is the audit-side counterpart.
- **Does not touch production.** Ever. The plugin operates on a restored backup or
  read-only replica. Production access is out of scope by design.
- **Does not decide anything.** Output is "exception requiring investigation", never
  "fraud". This follows the repo's own finding that the AI layer must be assistive with
  mandatory human review, and PDPA constraints on automated decision-making.
- **Ships no eFinancials-specific table names.** Everything physical is discovered and recorded
  in a per-installation `mapping.yaml`.
- **Not a general-purpose SQL agent.** Read paths are narrow and governed by design.
- **Node is never a hard dependency.** The Pi triage module (D12) is optional and
  feature-flagged off; the plugin installs, tests and runs fully without a Node runtime.
- **Takes on no dependency on the host repo's existing pipeline** (D14). It does not read
  `sql/gold_*.sql`, does not import `batch/`, and does not require Airflow, Spark, Iceberg,
  Trino, Superset or Keycloak to be running. Deliberately duplicates rather than couples.
- **Node is never a hard dependency.** The Pi triage module (D12) is optional and
  feature-flagged off; the plugin installs, tests and runs fully without a Node runtime.

## Decisions

Settled during brainstorming, recorded here so the implementation does not relitigate them.

| # | Decision | Rationale |
|---|---|---|
| D1 | Operate on a **sandbox restore**, plugin connects locally | Only topology where the deny controls are enforceable end to end |
| D2 | **Enforce at the GRANT, not the hook** | Hooks protect against Claude; grants protect against bugs in our own scripts and against agents added later |
| D3 | **Deterministic pseudonymisation with a local encrypted token vault** | Exact-match linkage across tables survives; auditor can still re-identify an exception locally |
| D4 | **Presidio scrubs, SLM classifies** | Scrubbing must be deterministic and exhaustive; classification benefits from judgment on a sample |
| D5 | **SLM reads raw data, pre-anonymisation, on the trusted box** | It is inside the trust boundary. It is the translator at the PII firewall |
| D6 | **Linkage and pathology features computed trusted-side** | Fuzzy matching and placeholder detection are impossible post-tokenisation |
| D7 | **Amounts and posting timestamps kept exact** | Structuring, Benford, round-number, after-hours and interval tests need truth. Recorded as a residual risk in the DPIA input |
| D8 | **Deny hooks fail closed** | Deliberate divergence from `proposal-research`, where guards fail open. A leaked NIC costs more than a blocked session |
| D9 | **Detection defaults to a local DuckDB mirror** | Rule tuning is where most queries happen; it should cost the database nothing |
| D10 | **Rules written against a canonical ontology, not physical tables** | Pattern library survives an eFinancials upgrade; unmapped entities become audit findings |
| D11 | **No FIU cash-reporting threshold is hardcoded** | The figure must be sourced, not asserted from memory, in a control a regulator may read |
| D12 | **Pi-orchestrated local SLM triage is an optional module, off by default** | Pi is an orchestrator, not a model. It adds a Node runtime to the zone holding raw PII, so it must be opt-in and the plugin must run fully without it |
| D13 | **Local-only processing is proven, not asserted** | The requirement is demonstrability to a third party, which is an evidence problem distinct from the control problem. Hence `/lf:attest` and a reproducibility-based proof |
| D14 | **Standalone. Zero dependency on the host repo's existing pipeline** | The Airflow/Spark/Iceberg/Trino implementation in `mi-audit-data-pipeline` is unfinished and not working. The plugin imports nothing from it and runs with all of it switched off |
| D15 | **Scale-out is a documented fork, taken later** | When data volume outgrows single-box DuckDB, either a Claude Agent SDK version of the same logic or a handoff to the Spark/Iceberg batch path. Neither is designed now; the pattern definitions and the ontology are the portable assets |
| D17 | **Two detection tiers, not one** | The scrub wants recall (over-redaction is free); the sentinel trips a circuit breaker and wants precision. One matcher cannot serve both — on a real ledger, `TXN-1234` and 12-digit account numbers would halt the run continuously, and a tripwire that cries wolf gets switched off |
| D16 | **The host repo's constitution is binding** | `internal-audit-system-constitution.md` governs. Articles 10, 29, 30, 32 and Prohibited Practices 8, 9 and 13 impose hard requirements, and Part XII is a release gate |

## Architecture

### Trust zones

```
ZONE 0  eFinancials PRODUCTION       never touched by this plugin
   |  nightly restore, out of band, by the DBA
   v
ZONE 1  sandbox  dbo.*           raw PII. Claude's login has NO GRANT here.
   |                             SLM probe reads here. seal.py writes from here.
   |  ---- crossing #1: seal.py + probe.py ----------------------------
   v
ZONE 2  sandbox  anon.*          tokenised views, DuckDB mirror, vault.sqlite
   |                             Claude's login: SELECT on anon only
   |  ---- crossing #2: query.py + extract.py ------------------------
   v
ZONE 3  Claude context           metadata, statistics, tokens, derived features
```

Exactly two boundary crossings, each a single audited script, each one-way. Zone 1 is
reachable only by scripts the human invokes with an elevated local login; Claude's
credentials cannot address it.

### Pipeline

```
/lf:preflight     guardrail self-test; gates everything else
      |
/lf:discover      schema-cartographer  -> schema.json, fk-graph.json, volumetrics
      |
/lf:probe         probe.py (local SLM, Zone 1) -> probe-report.json
      |
      +-- /lf:triage   OPTIONAL. Pi orchestrator + local SLM, Zone 1.
      |                Multi-step triage over raw rows; emits de-identified
      |                findings only. Off by default; skipped if absent.
      |
/lf:classify      pii-classifier -> classification.yaml (status: draft)
      |
   [HUMAN SIGN-OFF GATE]   approved_by + approved_at + schema_hash
      |
/lf:seal          seal.py, run by the human with elevated login
      |           builds anon.*, applies grants, verifies, snapshots schema hash
      |
/lf:map-ontology  ontology-mapper -> mapping.yaml + gap list
      |
/lf:audit-scope   audit-scoper -> audit-data-map.md, risk-control-matrix.md,
      |                            untestable-register.md
/lf:patterns      pattern-designer -> patterns/resolved/*.sql
      |
/lf:detect        detect.py (DuckDB by default, --fresh for SQL Server)
      |
/lf:rings         ring-analyst -> shared-attribute graph, components, scores
      |
/lf:findings      exception-triage -> workpapers, vault, dpia-input.md
      |
/lf:attest        attest.py -> attestation pack proving Zone 1 stayed local

ccaf-deanon <token>    human-only CLI. Hook-denied to Claude. Every resolution logged.
```

### Six guardrail layers

| # | Layer | Mechanism | Defeats |
|---|---|---|---|
| L1 | Grant | `claude_ro` has `SELECT` on `anon`, `VIEW DEFINITION` and `SHOWPLAN`; no grant on `dbo`; member of `db_denydatawriter` | raw PII read and all writes, by construction |
| L2 | Connection | `SET QUERY_GOVERNOR_COST_LIMIT`, `LOCK_TIMEOUT`, statement timeout, `MAXDOP 1`, rollback-only, non-`sa` login | runaway load, accidental commit |
| L3 | Query gate | single-statement SELECT-only parser; injected `TOP` cap; `SHOWPLAN_XML` estimated-cost pre-flight; session budget ledger | DML smuggling, table scans |
| L3.5 | Output scrub | `query.py` and `probe.py` run every result set through the LK recognisers and Presidio **before printing it**; a hit redacts the cell, records an incident and fails the call | a column nobody classified — preventively |
| L4 | Deny hooks | `sql_guard`, `pii_read_guard`, `model_guard`, `budget_guard` — PreToolUse, exit 2 | bypassing the CLI, vault/`.env` reads, cloud model calls, budget exhaustion |
| L5 | Leak sentinel | PostToolUse on every tool; regex-scans the tool result for LK PII patterns and the canary; on a hit, records an incident and trips the circuit breaker that blocks all further data commands | anything that reached context by a path L3.5 does not own |

L1 is primary. L4 exists because L1 cannot see what Claude does outside SQL.
L3.5 and L5 exist because L1 through L4 all assume the classification was correct.

**The two layers consume different matchers (D17).** This was learned the hard way
during implementation, and it is the more important half of the L3.5/L5 distinction:

- `find_all()` is **recall-biased** and feeds L3.5. It over-matches deliberately — a
  needless redaction costs nothing.
- `find_high_confidence()` is **precision-biased** and feeds L5 alone. Eligible kinds are
  NIC (both generations, each requiring a valid day-of-year code, with the 12-digit form
  additionally requiring a birth year in 1900-2100), mobile and landline.

Vehicle registrations and passport numbers are **excluded from the sentinel tier**,
because `CAB-1234` is structurally indistinguishable from `TXN-1234`, and `N1234567` from
a part number, without knowing which column the value came from. Pointing the
recall-biased matcher at a control that halts the audit run would have halted it on
ordinary ledger content — `INV-9999`, `CHQ-0451`, `07-2025`, every account number.

Accepted residual, recorded rather than hidden: a leaked vehicle registration or passport
number will not trip the breaker. L3.5 still redacts both, and L5 exists to catch paths
that bypass L3.5, so this narrows the tripwire rather than opening a hole. A 12-digit
account number that happens to begin 19xx/20xx and carry a valid daycode still trips it;
that case is genuinely ambiguous without a column name and belongs to the classifier.

Dates are a related casualty to avoid: the numeric vehicle form must not match
`12-08-2026`. Posting timestamps are kept exact by design (D7), so redacting a date
destroys evidence the after-hours and interval tests need.

**L3.5 and L5 are not the same control, and the distinction is deliberate.** L3.5 is
*preventive* and runs inside our own scripts, where output is still ours to withhold — it is
the layer that can genuinely stop a stray value from ever being printed. L5 is *detective*:
a `PostToolUse` hook runs after the tool has already produced its result, so it must be
treated as a tripwire and circuit breaker, not as a filter. Claiming otherwise would put the
plugin's central guarantee on a mechanism that cannot carry it.

The practical consequence: every path that can emit data must route through L3.5. A tool
result reaching L5 with PII in it means a path exists that bypasses our scripts, which is a
defect to be fixed rather than a case to be filtered — hence the circuit breaker and the
incident record instead of a quiet redaction.

Query rejection at L3 covers: `;`-chained statements, CTEs containing DML, `SELECT ... INTO`,
`EXEC`/`sp_executesql`, `xp_*`, `OPENROWSET`/`OPENQUERY`, four-part linked-server names, and
any statement whose first keyword is not `SELECT` or `WITH`.

### Fail-closed rules

- **Unclassified column is absent from `anon`, not masked.** A column added by an eFinancials
  upgrade is invisible until classified. Absence is detectable in review; a bad mask is not.
- **SLM unavailable, timed out, schema-invalid, or low-confidence** → the whole free-text
  column is suppressed, emitting only a redaction marker plus a length bucket.
- **`classification.yaml` lacking human sign-off** → `seal.py` refuses to run.
- **Schema hash mismatch against the sealed snapshot** → re-classification required before
  any detection command will run.
- **A deny hook that raises** → exit 2 (block). Justified by D8; mitigated by `/lf:preflight`
  self-testing every hook so a crash surfaces before an audit run rather than during one.

### Agent roster

Seven subagents. Each is defined by what it *cannot* reach as much as by its prompt.

| Agent | Tools | Consumes | Produces |
|---|---|---|---|
| `schema-cartographer` | Bash (`metadata.py` only), Read, Write | catalogue views | `schema.json`, `fk-graph.json`, volumetrics, ERD |
| `pii-classifier` | Bash (`classify.py`, `profile.py`), Read, Write | column names, statistics, `probe-report.json` | `classification.yaml` (draft) |
| `ontology-mapper` | Read, Write, Bash (`query.py`) | schema, classification | `mapping.yaml`, gap list |
| `audit-scoper` | Read, Write | `mapping.yaml` | audit data map, risk-and-control matrix, untestable register |
| `pattern-designer` | Read, Write, Bash (`query.py`) | `mapping.yaml`, pattern library | `patterns/resolved/*.sql` |
| `ring-analyst` | Read, Write, Bash (`detect.py`) | tokens, cluster ids | shared-attribute graph, components, ring scores |
| `exception-triage` | Read, Write | tokenised exceptions | workpapers, findings |

`schema-cartographer` is hook-denied from `query.py`: it works on metadata and must not be
able to select data rows. `pii-classifier` never receives a value — `profile.py` and
`probe.py` return verdicts and statistics, never the inputs that produced them.
`exception-triage` is prompt-constrained and test-enforced never to assert fraud.

### The SLM probe

The probe is the design's least obvious component and its most valuable one.

**Why it may read raw PII.** It runs as a local process on the sandbox box. Its input never
leaves the machine. It is inside the trust boundary in the same sense the DBA is.

**What it buys.**

1. **Value-based column classification.** Legacy core banking schemas carry `UDF1..UDF20`,
   `TEXT3`, `REF_NO`, `FIELD_23`. Name-based classification is blind to a NIC sitting in
   `UDF7`; value-based classification is the only thing that finds it.
2. **Format-pathology features that anonymisation would destroy.** Extracted pre-tokenisation
   and emitted as derived booleans: `nic_is_placeholder`, `nic_checkdigit_invalid`,
   `name_is_test_pattern`, `addr_is_null_placeholder`, `contact_is_default`. These feed
   ghost-customer detection, which is otherwise impossible on tokenised data.
3. **Free-text triage.** Decides per column whether narrative fields can ever hold PII, and
   therefore what anonymisation policy applies.
4. **Ontology hints.** Proposes which canonical entity a table represents, from its values.

**Six controls.**

1. **Constrained output only.** JSON against a fixed schema: enum class, confidence,
   boolean flags, counts. No prose crosses the boundary. Schema-validation failure discards
   the verdict and suppresses the column. This is also the prompt-injection defence —
   remarks and memo fields are customer-influenceable text, a small model will follow an
   injected instruction, and the worst case here is a discarded verdict rather than an
   exfiltration.
2. **Output-side scrubbing.** The probe's own output passes through Presidio and the leak
   sentinel before being written to any Zone 2 path. Small models echo examples into their
   rationales; assume it and scrub.
3. **Sampling classifier, never a filter.** ~25 distinct non-null values per column,
   truncated to 120 characters. Every value in the sealed output is scrubbed
   deterministically by Presidio regardless of what the probe said.
4. **Determinism by artifact.** Temperature 0, pinned seed, every verdict cached with
   `(model_digest, prompt_hash, input_hash)`. Re-runs read the cache, so the workpaper is
   stable even though the model is not. A model digest change invalidates the cache and
   forces re-review. The probe proposes; human sign-off makes it authoritative.
5. **Egress lockdown.** `OLLAMA_HOST` forced to `127.0.0.1`; model verified by digest; any
   `:cloud` tag or non-loopback host hard-denied at both `model_guard` and inside `slm.py`.
   Ollama's log and history directories are treated as Zone 1 and hook-denied to Claude.
   Preflight asserts the probe *fails* when the loopback model is unavailable rather than
   falling back to anything.
6. **Recall-biased prompting.** The prompt carries the Sri Lankan format catalogue with
   synthetic examples. Low confidence resolves to *sensitive*. Over-flagging costs a needless
   suppression; under-flagging costs a leak.

**Model tiering.** Cold path, once per schema: `qwen3:8b-q4_K_M` (~5 GB) — better judgment
where a miss becomes a leak. Hot path, bulk free-text redaction: `qwen3:4b-q4_K_M` (~2.5 GB),
batched, concurrency 1. Both pinned by digest. Neither resolving locally degrades to
Presidio-only plus full suppression of free text.

Sizing note: the development machine is an M3 Pro / 18 GB, which accommodates the 8B
comfortably when nothing else is resident.

### Optional: Pi-orchestrated local triage

**Status: optional module, feature-flagged off by default. Nothing else in the plugin
depends on it, and the plugin must install, pass its full test suite and run end to end on a
machine with no Node runtime present.**

The baseline probe above is single-shot: one prompt per column, fixed JSON out, no tools.
That is the right shape for classification, and it stays the default. But *triage* — "look at
this cluster of rows and tell me which of them deserve a human" — is genuinely multi-step:
sample, form a hypothesis, check it against another table, narrow, report. That is an agent
loop, and it is worth having one on the trusted box, where it may look at real values.

**The division of labour.** Pi is the orchestrator; the local SLM is the brain. Pi contributes
session management, the tool loop and structured output; it contributes no intelligence and no
model. All inference is local.

```
MACHINE / BOX (trusted, Zone 1)
   Pi SDK  (orchestrator, tool loop)
      |  models.json: baseUrl http://127.0.0.1:11434/v1, api openai-completions
      v
   Ollama  (the brain, pinned digest)
      |
   fixed local tool allowlist  ->  raw rows, never off the box
      |
   constrained JSON findings  ->  scrubbed  ->  Zone 2
```

**Why Pi can be trusted here despite being a coding agent.** `@earendil-works/pi-coding-agent`
is a coding agent: its native shape is to take actions, including shell and file access. In
the zone holding raw PII that is the wrong shape by default, so the module constrains it:

1. **Fixed tool allowlist, no shell, no network.** Pi is given only tools we define:
   `sample_rows`, `column_stats`, `check_pattern`, `emit_finding`. No shell tool, no file
   write outside its scratch directory, no fetch tool. An orchestrator needs *some* tools —
   this is a curated set, not an empty one, and not the default set.
2. **No credentials in the environment.** The process runs under `env -i` with no `*_API_KEY`
   present. Pi's default providers are Anthropic and OpenAI; with no key it cannot
   authenticate to either even if a code path tried. This is the control that makes the
   cloud-by-default posture inert.
3. **Loopback-only model resolution.** `models.json` pins `baseUrl` to `127.0.0.1`;
   `model_guard` and `slm.py`'s existing checks apply unchanged. Any non-loopback host or
   `:cloud` tag is denied.
4. **No egress route.** Where the box is air-gapped, this is physics. Where it is not, the
   process runs with all outbound blocked and the block logged — the log being the evidence.
5. **Output is constrained and scrubbed.** Findings are schema-validated JSON, then passed
   through the L3.5 output scrub before reaching Zone 2. Identical treatment to `probe.py`;
   the optional module gets no exemption from the boundary.
6. **Vendored dependencies.** `node_modules` is vendored and hash-pinned, and appears in the
   SBOM. This is the module's real cost and the honest argument against enabling it: it
   enlarges the dependency surface that has to be defended in the zone that holds raw PII.

**What it produces.** Tokenised, de-identified triage output only: which exception clusters
merit human attention and why, expressed in ontology terms and tokens. It never emits a real
value, and it is never the decider — `exception-triage` on the Claude side and a human
auditor both remain in the loop. Per the assistive-only constraint, an SLM triage verdict is
an input to a workpaper, not a conclusion in one.

**Degradation.** Feature flag off, or Node absent, or Pi's model resolution failing → the
module is skipped and the pipeline proceeds exactly as specced. No phase consumes its output
as a required input.

### Attestation — proving raw data never left the box

The requirement is not only that raw data stays local but that this is **demonstrable to a
third party**: an audit committee, the client's security function, or a regulator. That is an
evidence problem distinct from the control problem, so it gets its own deliverable.

`/lf:attest` emits an attestation pack covering **all** Zone 1 processing — the baseline probe
and, when enabled, the Pi triage module. The evidence is the same either way, because safety
comes from the environment rather than from the SDK.

| Artifact | What it establishes |
|---|---|
| `run-manifest.jsonl` | hash-chained, one record per Zone 1 run: host id, interface state, model digest, config hash, input row counts, output hash, SHA-256 of every file read and written. Chained so it cannot be retro-edited |
| `egress-proof/` | packet capture and interface state spanning the run, showing zero outbound; or, where containerised, the `--network=none` config hash |
| `env-proof.json` | the process ran under `env -i` with no `*_API_KEY` present — it could not authenticate to any hosted provider |
| `sbom.json` | every dependency present in Zone 1, Python wheels and vendored `node_modules` alike |
| `model-pin.json` | model digest resolved offline and verified against the pinned value |
| `canary-report.md` | a unique canary planted in the raw data, never observed in any Zone 2/3 output, transcript or log. Absence across the whole run is affirmative evidence, not merely absence of evidence |
| `reproduction.md` | temperature 0, pinned seed, pinned digest — an independent auditor re-runs on their own box and obtains identical output hashes |
| `ATTESTATION.md` | the human-readable statement, indexed into the evidence above |

`reproduction.md` is the strongest item. Determinism means the claim does not rest on trusting
our code or our logs: an independent party can reproduce the transformation and compare
hashes. Every other artifact supports a claim about *this* run; reproducibility supports a
claim anyone can re-test.

**Air-gapped operation.** Supported but not required, and it does not change D1. Three staging
consequences: Ollama models pre-pulled and digest-verified offline, Presidio's spaCy models
pre-downloaded, Python wheels and `node_modules` vendored. `/lf:preflight` gains an air-gap
mode asserting no interface is up, and refusing to run if one is.

One structural note recorded so it is not discovered late: Claude Code requires the Anthropic
API, so a genuinely air-gapped box cannot run Claude. Full air-gap therefore implies two
machines — an offline box for Zone 1 and a connected one running Claude against the Zone 2
extract — with a reviewed transfer between them. That topology is a stronger version of the
same guarantee and the transfer boundary is specced as a clean seam so the same code runs in
either arrangement, but it is **not** the primary topology and D1 is unchanged.

### Anonymisation transforms

| Class | Transform | Rationale |
|---|---|---|
| NIC, passport, TIN | HMAC-SHA256 → `NIC_<hex>` | exact-match linkage survives |
| Person name | suppressed; emit `name_phonetic_token`, `name_cluster_id` | fuzzy duplicate-borrower detection, computed trusted-side |
| Address | suppressed; emit `addr_norm_token`, `district`, `addr_cluster_id` | collusion rings; geography no finer than district |
| Mobile, email | HMAC token | shared-contact ring detection survives |
| Date of birth | 5-year age band | no date of birth crosses, ever |
| Account, lease, contract number | HMAC token, prefix-preserving | joins survive; product type stays visible |
| Vehicle registration, chassis, engine | HMAC token + `vehicle_cluster_id` | double-pledge and transposed-digit detection |
| Posting and value timestamps | **kept exact** | after-hours, weekend, sequence and interval tests need truth |
| Monetary amounts | **kept exact** | structuring, Benford, round-number tests need truth |
| Free text | SLM NER redaction, then Presidio as a second net; suppressed on any failure | residual risk concentrates here |
| Staff and user identifiers | HMAC token, staff↔customer link preserved | insider detection |
| Anything unclassified | absent | fail closed |

**Re-identification risk on aggregates.** Exact amounts plus exact timestamps plus district
plus age band can re-identify in a small population. Mitigation, and the reason the
distinction matters:

- **Descriptive aggregate tables** get *k*-anonymity suppression: cells with n < 5 suppressed.
- **Exception rows** carry tokens only, with no quasi-identifier columns, so a single-row
  exception — which is the entire point of fraud detection — remains safe.

D7 is recorded in `dpia-input.md` as an accepted residual risk with its analytical
justification, so the DPIA records a decision rather than an oversight.

### Token vault

Deterministic tokens: `HMAC-SHA256(secret, class || normalised_value)`, truncated, prefixed
by class. The secret lives in the macOS Keychain, never in a file, never in `.env`.

`vault.sqlite` holds `token → real value` and is encrypted at rest. It is:

- written only by `seal.py`,
- read only by `deanon.py`,
- hook-denied to Claude for Read, Grep, Glob and Bash,
- append-only, with every resolution recorded to `deanon-access-log.jsonl`.

The access log matters beyond hygiene: PDPA accountability means every re-identification
should itself be an auditable event.

### Ontology

Canonical entities: `Party`, `Employee`, `Facility` (Lease / HP / Loan), `Collateral`,
`Deposit`, `Posting`, `Receipt`, `Waiver`, `GLAccount`, `Branch`, `MasterDataChange`,
`AuditEvent`.

`ontology/canonical.yaml` defines entities, required and optional attributes, and
relationships. `mapping.yaml` binds each to physical eFinancials tables and columns, per
installation.

Three payoffs. The pattern library survives an eFinancials upgrade, because only the mapping
changes. **Unmapped canonical entities are themselves audit findings** — "double-pledge
cannot be tested because no collateral-to-facility relationship exists in the data" is a
reportable control weakness, captured in `untestable-register.md`. And the plugin ports: the
vendor states eFinancials is in use at **25 registered financial institutions in Sri Lanka**,
so a mapping is the only per-institution work.

### eFinancials module map

Sourced from the vendor's published module list, not from the schema. This is a *prior* for
`/lf:discover` — a hypothesis about what to look for and what table-prefix families to
expect — never a substitute for discovery. eFinancials is described as a **decentralised**
system covering leasing, loans, recovery, impairment, credit risk rating and scorecard,
recovery call centre, and **yard management**.

| eFinancials module | Canonical entities | Audit relevance |
|---|---|---|
| Central Module | `Party`, `Branch`, `Employee`, `MasterDataChange` | customer master, the IN-03 payout-preceded-by-edit test |
| Leasing System | `Facility`, `Collateral` | CO-01..CO-04, CO-07, CO-08 |
| Loan Module | `Facility` | CO-05, CO-06, CO-09 |
| Revolving Loan | `Facility` | limit-utilisation cycling, evergreening |
| Recovery System | `Receipt`, `Waiver`, `Posting` | CR-01..CR-06 |
| Credit Risk Rating & Score Card | `Facility` | **scorecard override** — new pattern CO-11 |
| Recovery Call Centre | `AuditEvent` | recovery-officer contact vs collection reality |
| Lead Management | `Party` | origination-side introducer concentration |
| Central CRIB Management System | `Party`, `Facility` | **CRIB inquiry absent or post-dated** — new pattern CO-12 |
| Fixed Deposit System | `Deposit` | DP-02, DP-04, DP-05 |
| Savings System | `Deposit`, `Posting` | DP-01, DP-03, DP-06 |
| General Ledger | `GLAccount`, `Posting` | CR-03, IN-07, IN-08 |
| SLIPS Module | `Posting` | **outbound interbank payments** — beneficiary-change pattern IN-09 |
| Fixed Assets Module | — | candidate fifth domain, see Open items |
| Accounts Payable | — | candidate fifth domain (vendor and duplicate-payment fraud) |
| Accounts Receivable | — | candidate fifth domain |
| AML | `Posting`, `Party` | DP-07 becomes checkable against the module's own alert tables |

Five consequences for the design, all of which improve it:

1. **A dedicated AML module exists.** DP-07 changes from "find unreported threshold breaches"
   to the sharper audit question: *did the AML module generate an alert, and was it
   dispositioned?* An alert raised and silently closed is a stronger finding than a
   transaction never flagged. The module's own alert and disposition tables become audit
   evidence, and its threshold configuration becomes the sourced value D11 is waiting for.
2. **CRIB integration is a control test, not just data.** A disbursement with no preceding
   CRIB inquiry, or an inquiry dated after disbursement, is a concrete, checkable exception —
   the same shape as the advance-payment/CUSDEC reconciliation the repo's evidence pack
   recommends as a first rule.
3. **Yard management makes CR-06 real.** Repossessed-vehicle custody and sale proceeds have
   a system of record, so proceeds-versus-valuation shortfall and yard-dwell-time anomalies
   are testable rather than aspirational.
4. **Scorecard and impairment are override surfaces.** A manual override of a scorecard
   result, and impairment-stage regrading that avoids NPL classification (evergreening), are
   both high-value leasing-sector typologies that the module list confirms are in scope.
5. **SLIPS is the money-out door.** Outbound payment instructions are where a master-data
   change turns into a loss, which raises IN-03's priority and adds IN-09.

Six new patterns follow, taking the library from 33 to 39: **CO-11** scorecard override
concentration · **CO-12** CRIB inquiry absent or post-dated at disbursement · **CO-13**
evergreening and impairment-stage regrading to avoid NPL classification · **CR-09** yard
dwell-time and sale-proceeds anomalies · **IN-09** SLIPS beneficiary account changed between
approval and payment · **DP-08** AML alert raised then closed without documented disposition.

### Fraud pattern library

39 patterns across the four domains. Each is a YAML carrying: `id`, `title`, `domain`,
`typology`, `audit_assertion`, `requires.entities`, `requires.attributes`, detection
template, `thresholds`, `false_positive_drivers`, `evidence_columns`, `severity`,
`requires_human_verification`.

**Credit origination and collateral (13)** — CO-01 ghost lease (disbursed with no collateral,
valuation or insurance record) · CO-02 valuation inflation and valuer concentration ·
CO-03 duplicate identity (same NIC token on multiple parties; shared phone and address
cluster) · CO-04 double pledge (same collateral token on multiple active facilities) ·
CO-05 staff-linked borrower · CO-06 approval-limit splitting · CO-07 backdated approval ·
CO-08 serial guarantor · CO-09 first-payment-default clusters by originator ·
CO-10 placeholder-identity concentration by originating officer ·
CO-11 scorecard override concentration · CO-12 CRIB inquiry absent or post-dated at
disbursement · CO-13 evergreening and impairment-stage regrading to avoid NPL
classification.

**Collections, recovery and cash (9)** — CR-01 receipt-to-posting lag outliers by officer
(teeming and lading) · CR-02 reversal and cancellation concentration · CR-03 suspense
parking uncleared beyond n days · CR-04 waiver beyond authority, or waiver immediately
before settlement · CR-05 early-settlement rebate recomputation mismatch · CR-06
repossession proceeds against valuation shortfall · CR-07 teller cash-shortage patterns ·
CR-08 round-number and duplicate-amount receipts · CR-09 yard dwell-time and
sale-proceeds anomalies.

**Deposits and AML/CTR (8)** — DP-01 cash structuring below the reporting threshold in a
rolling window per party cluster · DP-02 dormant reactivation followed by withdrawal ·
DP-03 third-party payout (payee account token differs from registered) · DP-04 rapid FD
open-close cycling · DP-05 interest-rate override by user · DP-06 shared contact or address
across unrelated depositors · DP-07 threshold-breaching transactions with no matching
report · DP-08 AML alert raised then closed without documented disposition.

**Insider, master data and GL (9)** — IN-01 maker equals checker · IN-02 after-hours,
weekend and holiday postings · IN-03 master-data change (bank account, phone, address)
within n days before a payout · IN-04 terminated-employee login activity · IN-05 privilege
escalation events · IN-06 audit-trail sequence gaps · IN-07 Benford first-digit deviation
and round-number journals by user · IN-08 postings to closed periods · IN-09 SLIPS
beneficiary account changed between approval and payment.

Per D11, DP-01 and DP-07 carry a `threshold_ref` that must be populated from a sourced
authority. `/lf:preflight` refuses to enable the deposits domain while it is unset.

### Data load governance

- Row counts from `sys.dm_db_partition_stats`, **never `COUNT(*)`** — free, no scan.
- Column profiling via `TABLESAMPLE (1 PERCENT)` or `TOP 10000`. No full scans.
- `SHOWPLAN_XML` estimated-cost pre-flight on every query; default governor limit 150.
- Session budget: 50,000 rows. Per-query cap `TOP 5000` unless raised with a justification
  recorded in the query ledger.
- `/lf:detect` runs against the DuckDB mirror by default. SQL Server is touched only on
  `--fresh`.
- Extraction chunked by primary-key range, throttled, inside a configurable run window.
- `query-log.jsonl` records sql hash, estimated cost, actual rows, duration and `agent_id`,
  and is the input to `budget_guard`.

### `/lf:preflight` — the trust anchor

Every other command refuses to run without a passing preflight matching the current config
hash. It proves rather than asserts:

1. Claude's login receives a permission denial on `dbo.*`.
2. A DML statement is rejected independently at L1, L2 and L3.
3. A **planted canary NIC** in a sandbox row never reaches context; the sentinel fires.
4. The pinned model resolves on loopback; a `:cloud` tag is rejected; probe fails rather
   than falls back when the model is absent.
5. Vault read is hook-denied across Read, Grep, Glob and Bash.
6. The governor rejects a deliberately over-budget query.
7. Every deny hook is exercised with an attack string and returns exit 2.

Output: `preflight-report.md`, plus a config-hash stamp the other commands check.

## Constitutional conformance

The host repository's `internal-audit-system-constitution.md` governs this work. Six
provisions impose requirements the design would otherwise have missed, and one is a release
gate.

| Provision | Requirement | Where it lands |
|---|---|---|
| **Article 29** + **PP8** | Full population is the default; sampling requires justification, and sampling from a population whose completeness has not been evidenced is prohibited | Detections run **full population**. `TABLESAMPLE`/`TOP` caps are confined to *profiling*, which produces no findings. Every detection run emits a reconciliation record — source row count, sealed row count, extracted row count, control totals — and refuses to report if they disagree |
| **Article 30** + **PP13** | Analytics supporting a finding must be explainable and reperformable; unexplainable analytics cannot support a finding | **An SLM verdict may never be the sole basis of a finding.** Every finding record must cite a deterministic pattern id. A finding whose only support is an SLM output is structurally impossible to emit, and there is a test for it |
| **Article 10** | Chain of custody: source system, extraction method, extractor, timestamp, integrity hash; auditee-provided evidence marked as such | The run manifest carries exactly these fields, using the host repo's existing field names (`EXTRACTION_METHOD`, `EXTRACTOR`, `AUDITEE_PROVIDED`) as a **naming convention only** — no import, no coupling (D14) |
| **Article 32** + **PP9** | Internal audit holds no write access to auditee production systems, ever; access denials are logged and reportable as scope limitations | Already satisfied by L1/L2 (D2). Adds a requirement: the query gate logs **denials** as candidate scope limitations, not merely as errors |
| **Article 14** + **Article 36** | Testing is reproducible; historical work reconstructable including the methodology in force at the time | Every detection run snapshots pattern versions, thresholds, `mapping.yaml`, `classification.yaml` hash and model digest into an immutable run bundle |
| **Article 1** + **Article 28** | Independence is architectural; no in-scope role may alter the audit log | The token vault secret is **audit-held**, not IT-held. `deanon-access-log.jsonl` is append-only and hash-chained. Where IT operates the box, that is a recorded compensating-control gap |

**Part XII standing test** is a release gate: the twelve questions are answered explicitly in
`docs/CONSTITUTION-CONFORMANCE.md` before any phase is called done. A failure on any one is a
blocking defect, per the constitution's own terms.

One observation recorded for the host repo's owners rather than acted on here: the existing
`batch/ingest_bronze.py` names `debezium-cdc` as its intended extraction method. Enabling CDC
requires a DDL change on the source database, which for an auditee production system appears
to conflict with Article 32 and Prohibited Practice 9 — a practice the constitution admits no
business justification for. The sandbox-restore approach (D1) does not have this problem: the
restore is part of the DBA's own operations and audit reads a copy. Flagged, not decided.

## Plan decomposition

The spec is too large for a single implementation plan, and database access has not yet been
granted. Work is therefore split so that the first plan needs no database at all.

| Plan | Phases | Needs DB access? |
|---|---|---|
| **1 — Safety spine and attestation** | P1 + P7 | **No.** Proven against a synthetic eFinancials-shaped fixture |
| 2 — Discovery and probe | P2 + P3 | Yes |
| 3 — Ontology and audit scope | P4 | Yes |
| 4 — Pattern library and detection | P5 | Yes |
| 5 — Rings, triage and findings | P6 | Yes |
| 6 — Optional Pi triage module | P8 | Yes, plus Node |

## Repository layout

```
plugins/ledger-forensics/
├── .claude-plugin/plugin.json
├── README.md
├── commands/
│   ├── preflight.md      discover.md     probe.md      classify.md
│   ├── seal.md           map-ontology.md audit-scope.md
│   ├── patterns.md       detect.md       rings.md      findings.md
│   └── attest.md         triage.md  (optional module)
├── agents/
│   ├── schema-cartographer.md   pii-classifier.md   ontology-mapper.md
│   ├── audit-scoper.md          pattern-designer.md ring-analyst.md
│   └── exception-triage.md
├── hooks/
│   ├── hooks.json
│   ├── sql_guard.py        deny DML/DDL, non-sanctioned clients, deanon invocation
│   ├── pii_read_guard.py   deny vault, Zone 1 paths, .env, ollama logs
│   ├── model_guard.py      deny cloud tags, non-loopback hosts, unpinned models
│   ├── budget_guard.py     refuse queries past the session budget
│   └── leak_sentinel.py    PostToolUse result scan, redact and log
├── scripts/
│   ├── conn.py         connection factory; read-only, timeouts, governor
│   ├── metadata.py     catalogue extraction (no data rows)
│   ├── profile.py      column statistics; returns stats, never values
│   ├── recognizers_lk.py  NIC old/new, mobile, landline, passport, vehicle, TIN
│   ├── probe.py        local SLM sampling probe (Zone 1)
│   ├── slm.py          pinned Ollama client; loopback-only; fail-closed
│   ├── classify.py     tiered classifier -> classification.yaml
│   ├── vault.py        HMAC tokeniser + encrypted vault
│   ├── seal.py         emit anon schema, apply grants, verify, snapshot hash
│   ├── linkage.py      phonetic, normalised-address and near-duplicate clustering
│   ├── query.py        the single governed query gate
│   ├── extract.py      anon -> parquet -> DuckDB mirror
│   ├── detect.py       run resolved pattern packs
│   ├── deanon.py       human-only re-identification CLI
│   ├── attest.py       hash-chained run manifest, egress and env proof, SBOM
│   └── triage/         OPTIONAL Pi module. Absent-safe; no phase requires it
│       ├── models.json     loopback-pinned, openai-completions
│       ├── tools.ts        fixed allowlist: sample_rows, column_stats,
│       │                   check_pattern, emit_finding. No shell, no fetch
│       └── run.ts          Pi session; env -i; constrained JSON out
│   └── selftest.py     guardrail self-test behind /lf:preflight
├── ontology/
│   ├── canonical.yaml
│   └── mapping.example.yaml
├── patterns/
│   ├── credit-origination/       (13 yaml)
│   ├── collections-cash/         (9 yaml)
│   ├── deposits-aml/             (8 yaml)
│   └── insider-masterdata-gl/    (9 yaml)
└── tests/
```

Workspace, per engagement, outside the plugin:

```
engagements/<name>/
├── preflight-report.md        config-hash stamped
├── datamap/                   schema.json, fk-graph.json, volumetrics.md, erd.html
├── probe-report.json          scrubbed, schema-validated verdicts
├── classification.yaml        signed off
├── mapping.yaml
├── audit-data-map.md          risk-control-matrix.md   untestable-register.md
├── patterns/resolved/*.sql
├── exceptions/*.csv           tokens only
├── findings/*.md              workpapers
├── vault/                     Obsidian vault, house style
├── query-log.jsonl            deanon-access-log.jsonl   incidents.jsonl
└── dpia-input.md
```

## Deliverables

Data map and ERD · signed `classification.yaml` · `mapping.yaml` · audit data map ·
risk-and-control matrix · untestable register · resolved detection SQL · tokenised exception
CSVs · one workpaper per finding, each carrying assertion, population, test, exception count
and required human verification steps · Obsidian vault · `preflight-report.md` ·
`query-log.jsonl` · `deanon-access-log.jsonl` · `incidents.jsonl` · `dpia-input.md` ·
**`attestation/`** (run manifest, egress proof, env proof, SBOM, model pin, canary report,
reproduction instructions, `ATTESTATION.md`).

`dpia-input.md` is a pre-filled input to the PDPA data protection impact assessment that the
repo's own evidence pack identifies as a mandatory pre-go-live deliverable: processing
purposes, data categories, transforms applied, retention, and accepted residual risks
including D7.

## Testing

The hook tests are the most important tests in the plugin, because they are the tests of the
guarantee rather than of a feature.

| Test | Asserts |
|---|---|
| `test_hooks_sql_guard.py` | table of DML, DDL, chained, `EXEC`, `OPENROWSET` and bypass-client strings each exit 2; legitimate `SELECT`s pass |
| `test_hooks_pii_read_guard.py` | vault, Zone 1 paths, `.env` and ollama log reads denied across Read, Grep, Glob, Bash; workspace reads pass |
| `test_hooks_model_guard.py` | `:cloud` tags, non-loopback `OLLAMA_HOST`, unpinned digests denied |
| `test_hooks_fail_closed.py` | a guard raising an exception exits 2, not 0 (D8) |
| `test_output_scrub.py` | L3.5 — a planted PII value in a result set is redacted and the call fails, before anything is printed |
| `test_leak_sentinel.py` | L5 — LK PII patterns and the canary in a tool result raise an incident and trip the circuit breaker |
| `test_recognizers_lk.py` | synthetic-but-real-format NIC (both formats), mobile, landline, passport, vehicle series, TIN |
| `test_probe_output.py` | deliberately poisoned rows produce no PII in `probe-report.json` |
| `test_probe_injection.py` | an injection payload in a remarks field yields a discarded verdict, never a leak |
| `test_probe_cache.py` | verdict cache is stable across runs; digest change invalidates it |
| `test_vault.py` | token determinism, prefix preservation, vault encryption, access logging |
| `test_query_governor.py` | over-cost query rejected pre-execution; budget exhaustion blocks |
| `test_seal_grants.py` | after seal, the `claude_ro` login is denied on `dbo`, permitted on `anon`, and holds `SHOWPLAN` (which L3 cost pre-flight requires) |
| `test_seal_signoff.py` | unsigned or hash-mismatched `classification.yaml` refuses to seal |
| `test_patterns_schema.py` | every pattern YAML validates; `threshold_ref` unpopulated blocks the domain |
| `test_agents.py` | agent frontmatter contract; `schema-cartographer` lacks `query.py` access |
| `test_attest_chain.py` | manifest hash chain detects an edited record; canary report is derived, not asserted |
| `test_attest_env_proof.py` | a run with any `*_API_KEY` in the environment fails rather than being attested |
| `test_triage_absent.py` | **with Node uninstalled and the flag off, the full suite still passes** — the optional module is genuinely optional |
| `test_triage_tools.py` | Pi's tool registry contains only the four allowlisted tools; no shell, file-write or fetch tool is reachable |
| `test_triage_loopback.py` | a `models.json` with a non-loopback `baseUrl` is rejected before a session opens |
| `test_triage_output.py` | triage findings are schema-validated and pass L3.5 scrub; a planted raw value never reaches Zone 2 |
| `test_end_to_end_no_pii.py` | synthetic eFinancials-shaped DB with Faker LK data through the full pipeline; **zero PII patterns and zero canary hits** in any output or transcript |

`test_end_to_end_no_pii.py` is the proof of the whole claim and should be written first,
failing, in P1.

## Build order

| Phase | Content | Gate |
|---|---|---|
| **P1** | Skeleton, `/lf:preflight`, all six guardrail layers, every hook test, the canary, `test_end_to_end_no_pii.py` | Nothing touches real data until preflight passes |
| P2 | `metadata.py`, `schema-cartographer`, `/lf:discover`, ERD | |
| P3 | `recognizers_lk.py`, `slm.py`, `probe.py`, `classify.py`, `vault.py`, `linkage.py`, `seal.py`, sign-off gate | |
| P4 | `ontology/canonical.yaml`, `ontology-mapper`, `audit-scoper` | |
| P5 | Pattern library (33), `pattern-designer`, `extract.py`, `detect.py`, DuckDB mirror | |
| P6 | `ring-analyst`, `exception-triage`, workpapers, vault builder, `dpia-input.md` | |
| P7 | `attest.py`, `/lf:attest`, air-gap preflight mode, attestation pack | Independent of P8; deliverable on its own |
| **P8** | **OPTIONAL** — Pi triage module: `models.json`, tool allowlist, `run.ts`, vendored `node_modules`, `/lf:triage` | Gated behind `test_triage_absent.py`: the plugin must pass its full suite with Node uninstalled before this phase may land |

P1 ships and is proven independently. It is the phase that earns the right to run the rest.

## New dependencies

`duckdb` (not installed) · one or two Ollama pulls (`qwen3:8b-q4_K_M`, `qwen3:4b-q4_K_M`).

**Optional module only (P8), never a hard dependency:** Node runtime ·
`@earendil-works/pi-coding-agent`, vendored and hash-pinned. The plugin's install, test suite
and full pipeline must all succeed with none of these present.
Already present: `presidio_analyzer`, `faker`, `pandas`, `sqlalchemy`, `pymssql`. No
Microsoft ODBC driver required — `pymssql` over FreeTDS.

## Open items

Carried deliberately rather than guessed at.

1. **FIU cash-reporting threshold** — unset until sourced from a citable authority or from
   the repo's existing evidence pack. Blocks the deposits domain, not the plugin.
2. **eFinancials physical schema** — unknown by design. `/lf:discover` is the answer, and
   `mapping.yaml` is where it lands. The module map above is a prior, not a schema.
3. **Is it one database or many?** The vendor describes eFinancials as a *decentralised*
   system, and the published material does not say what that means physically. If it is
   per-branch databases consolidating to head office, three things change: `/lf:discover`
   must enumerate instances rather than a schema, `seal.py` must run per database with one
   shared token secret so tokens stay comparable across branches, and a new and valuable
   pattern class opens up — **branch-to-head-office reconciliation gaps**, where a
   transaction exists at one level and not the other. That is a classic concealment route in
   decentralised cores. Resolve this in the first access conversation; it is the single
   question with the largest effect on P2.
4. **Does an audit trail actually exist?** The published module list names no audit-trail,
   user-administration or maker-checker component. If there is no audit-event table,
   IN-01, IN-02, IN-04, IN-05 and IN-06 are all untestable — and that absence is itself a
   significant reportable control weakness, not merely a gap in our coverage. First thing
   to confirm at discovery; it goes in `untestable-register.md` either way.
5. **Fifth domain: procurement and expenses.** Fixed Assets, Accounts Payable and Accounts
   Receivable are in the product but outside the four domains selected. They carry their own
   well-understood typologies — duplicate vendor payments, fictitious vendors, vendor bank
   account matching an employee's, invoice splitting below authority, asset disposal at
   undervalue. Deliberately out of scope for v1; raised because the data will be sitting
   right there and the marginal cost of adding the domain later is a pattern pack, not a
   redesign.
6. **Approval-authority matrix and waiver limits** — CO-06 and CR-04 need the institution's
   own delegated-authority thresholds, which are a document, not a database table.
7. **Holiday calendar** — IN-02 needs Sri Lankan public and bank holidays as config.

## Deferred

- Real-time or scheduled monitoring. This is a point-in-time audit tool.
- Two-machine air-gapped topology as the *primary* mode. Supported and specced as a clean
  seam, but D1 stands: one sandbox box is the documented default.
- Writing into the user's existing second-brain vault. Each engagement emits an isolated one.
- Cross-engagement pattern learning.
- Any production connection mode.
