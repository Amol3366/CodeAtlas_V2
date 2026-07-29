# Phase 7 — Measured Semantic Uplift

Status: `in_progress` — the activation gate (explicit product, privacy, and
architecture approval) and this plan were both approved by the user on
2026-07-29 and are recorded in `docs/plans/PLAN.md`. Tasks may run.
Gate authority: user
Prerequisites: Phase 6 approved; `AGENTS.md` Sections 4.3, 4.4, 10, 16, 17, 18,
19; blueprint Sections 4.7, 4.9, 8.20–8.23, 12–15 (phases 12–14 and the
freshness/cost/provider strategy)

## Outcome

CodeAtlas gains an optional semantic retrieval layer that **measurably** improves
recall over the deterministic baseline — local embeddings by default, OpenAI
available only through per-repository opt-in with redaction and budgets — plus a
shadow-migration path that can swap embedding models with zero retrieval
downtime. Bounded reranking and evidence-grounded explanation are built last,
behind flags, and **admitted only if they show measured uplift**; a feature
without uplift is declined and the decline is recorded at the gate.

The deterministic product shipped in Phases 0–6 remains complete and fully
usable with every provider disabled. That is not a fallback slogan; it is a
tested gate condition.

## The Four Decisions the User Made (2026-07-29)

These were made at the activation gate and shape everything below.

1. **Full activation approval** — product, privacy, and architecture approval
   recorded in PLAN.md before this plan was written, as `AGENTS.md` Section 20
   requires.
2. **Provider scope: local + OpenAI opt-in**, behind one provider-neutral
   interface. `NoEmbeddingProvider` stays the default; deterministic fallback is
   always preserved.
3. **Local runtime: sentence-transformers + torch**, the blueprint's named
   option. The user accepted the packaging consequence (~1–2 GB added to the
   44 MB installer) with the requirement that ADR-0009 records the measured
   installer size before and after, and that the package remains functional.
4. **One phase, measurement admits.** Embeddings, migration, and privacy land
   first; reranking and explanation land last and are admitted **only** on
   measured uplift over the deterministic baseline, per the completion gate's
   "every admitted feature" wording. Features without uplift are declined and
   recorded, not shipped.

## What Already Exists (and What Does Not)

Built for this phase before it started:

- `SnapshotReference.semantic_coverage` is already in the response envelope
  (hardcoded `0.0` in `api/routers/repositories.py` today).
- `Derivation.SEMANTIC_CANDIDATE` and `Derivation.MODEL_GENERATED` already exist
  in the controlled derivation enum.
- `SnapshotFreshness.PARTIAL` already exists for the embeddings-pending state.
- `AnswerPipeline` names its own seam: "steps 14–15 — generation and claim
  re-validation of generated text — are Phase 7's."
- The evaluation harness (`evaluation/runner.py` + `queries.json`/`changes.json`)
  is the uplift yardstick, with explicit abstention scoring.

Spec gaps this phase closes (not scope expansion — the same pattern as
P6-STREAM closing Section 12.2):

- `GET /v1/repositories/{id}/semantic-status` (Section 12.1) — unimplemented.
- `GET/PATCH /v1/settings`, `GET /v1/models`, `POST /v1/models/test`, and the
  three `/v1/models/embedding-migrations` endpoints (Section 12.5) —
  unimplemented; no settings domain exists at all (the web "settings" today is
  a theme toggle).

Does not exist: any embedding, vector-store, generation, or provider code; any
provider settings surface; LanceDB, sentence-transformers, or OpenAI
dependencies.

## Completion Gate (from `AGENTS.md` Section 20)

Phase 7 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log. A missed target is
reported as missed, with the measurement and the reason.

| # | Gate condition | Measured against |
| --- | --- | --- |
| 1 | Explicit product, privacy, and architecture approval recorded | **met 2026-07-29** — PLAN.md handoff |
| 2 | Provider-neutral embedding interface, with `NoEmbeddingProvider` as default and the deterministic path never requiring any provider | contract tests over the interface; all Phase 0–6 gates pass with providers disabled |
| 3 | Content-hash embedding cache: a one-symbol edit embeds only changed unique content hashes; unchanged content reuses vectors | incremental-embedding tests reusing the Phase 2 one-symbol-edit fixtures |
| 4 | LanceDB base/delta namespaces with SQLite snapshot membership authoritative: physically retained stale vectors never appear in active results | stale-vector filtering tests (vector present, membership absent → excluded) |
| 5 | Deterministic fallback: provider disablement, failure, timeout, or budget exhaustion each produce a useful deterministic result — and a provider-disabled evaluation run scores **identically** to the deterministic baseline | fallback test matrix; baseline comparison |
| 6 | Privacy governance: per-repository provider opt-in (default off for any transmitting provider), secret detection/redaction before transmission, budgets/timeouts/retries/cancellation, and telemetry that records counts/tokens/latency/outcome but never source, prompts, evidence, or answers | security suite + telemetry schema review + redaction tests |
| 7 | Semantic uplift: measured improvement over the deterministic baseline on the evaluation corpus — primary-evidence Recall@10 against the Section 19.3 ≥ 90% target, reported with containing/exact evidence rates and abstention behavior | `docs/evaluation/baseline-phase-7.{json,md}`; new conceptual cases are declared with gold answers **before** measurement and never edited after (ADR-0003) |
| 8 | Shadow embedding migration: shadow namespace, asynchronous backfill, dual-write, independent evaluation of both namespaces, atomic cutover, retained rollback, zero retrieval downtime; raw scores never compared across models | migration cutover/rollback tests; the `/v1/models/embedding-migrations` endpoints |
| 9 | Bounded reranking: intent-gated, top-N in one structured call, digest-keyed cache — **admitted only on measured uplift**; otherwise declined with the measurement recorded | rerank A/B evaluation on declared ambiguous/conceptual cases |
| 10 | Evidence-grounded explanation: evidence-only prompts, schema-constrained output, claim re-validation (pipeline steps 14–15) — **admitted only on measured uplift** with 100% citation validity; otherwise declined with the measurement recorded | explanation evaluation + claim-validation suite |
| 11 | Evidence and snapshot contracts preserved: all Phase 0–6 gates exit 0 unchanged; `contract_version` stays `"1.1"` (additive only); active-snapshot leakage stays 0 | `check_phase0..6.ps1` |
| 12 | Performance and packaging: Section 19.3 targets still hold with embeddings enabled (embedding never blocks deterministic activation), and the packaged build's size and cold start are re-measured with torch and recorded honestly | `scripts/measure_phase7_perf.py` on the packaged artifact; packaging report |

## Global Constraints

Phase 0–6 constraints all still apply. Additions and emphases:

- **Deterministic before probabilistic (Section 4.3).** Exact, lexical, graph,
  and Git retrieval MUST NOT depend on the semantic layer. A model score MUST
  NOT promote a probabilistic candidate to deterministic evidence: relevance
  discovered semantically carries `semantic_candidate` derivation until
  independent deterministic or static evidence supports the claim.
- **Local-first privacy (Section 4.4).** Nothing leaves the machine unless the
  user explicitly enables a transmitting provider **for that repository**.
  Source, prompts, retrieved evidence, and model output are never logged.
- **Semantic never blocks deterministic (Section 16).** Deterministic snapshot
  activation never waits on embeddings; coverage is tracked separately and
  reported; stale vectors are excluded by authoritative SQLite membership, not
  by deletion races.
- **The generation seam is steps 14–15 only.** Generated narrative receives
  verified evidence, relation paths, deterministic findings, and warnings —
  nothing else — and every claim is re-validated before persistence. Streaming
  text stays provisional; the persisted answer stays authoritative.
- **Additive contracts only.** `contract_version` stays `"1.1"`. Any breaking
  change requires an ADR and explicit approval (Section 25).
- **Evaluation precedes sophistication.** Corpus additions for conceptual
  queries are declared with gold answers before measurement begins and never
  edited to fit the engine afterward (ADR-0003's rule).
- Migrations remain forward-only and additive. `0001`–`0009` MUST NOT be
  edited.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement.

## Non-Goals (explicitly deferred)

| Deferred item | Reason |
| --- | --- |
| GPU requirement or GPU tuning | CPU-only operation is the product profile |
| TypeScript compiler API enrichment | Unrelated to semantic retrieval; separate benchmarked decision |
| Reranking deterministic resolutions (exact, graph, Git, rules) | Explicitly rejected by blueprint 15.6 |
| Whole-repository re-embedding after normal edits | Blueprint 15.8; cost contract forbids it |
| New programming languages | Section 25 |
| Automatic embedding-model upgrades | User-initiated only, through the migration endpoints |
| WebSockets | SSE remains sufficient (Section 6.2) |
| New MCP tools | `ask` answers may carry labeled semantic candidates; provider settings stay REST/CLI |
| Multi-user, network exposure, any mandatory cloud | Out of MVP scope (Section 25) |

## Phase Architecture Decisions

Fixed so tasks compose. Deviation requires an ADR and user approval. ADR-0009
(P7-SETUP) records these, including the sentence-transformers packaging
measurement the user required.

### 1. One provider-neutral interface, deterministic default

```python
class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `NoEmbeddingProvider` (default), `LocalSentenceTransformerProvider`
(pinned model, CPU), `OpenAIEmbeddingProvider` (per-repository opt-in only).
The deterministic path never constructs a real provider.

### 2. Content-hash embedding identity

`embedding_key = hash(content_hash, model_id, dimensions, normalization_version)`.
A normal file edit embeds only changed unique chunk content; unchanged chunk
versions reuse vectors across snapshots and branches. Whole-corpus re-embedding
happens only through an explicit model migration.

### 3. LanceDB behind a narrow interface; SQLite membership is authoritative

`VectorStore` interface with base and delta namespaces under
`%LOCALAPPDATA%\CodeAtlas\vectors\`. Every candidate is filtered against active
snapshot membership in SQLite: a physically retained stale vector is never
eligible. Compaction is threshold-driven and validated before any base switch.

### 4. sentence-transformers + torch for local embeddings (user decision)

Model pinned with its version recorded on every embedding record. ADR-0009
carries the measured installer size before/after and the package remains
functional; if packaging proves unworkable, that fact comes back to the user
with measurements rather than a silent runtime swap.

### 5. Privacy governance before any transmission

Per-repository provider setting: `none | local | openai`, default `none`.
`local` transmits nothing by construction. `openai` requires explicit
per-repository opt-in and passes every outbound payload through secret
detection and redaction, per-run and monthly budgets, timeouts, bounded
retries, and cancellation. Telemetry records counts, tokens, latency, and
outcome — never content.

### 6. Semantic is a discovery channel, never an authority

Semantic retrieval runs only for intents where evaluation justifies it
(conceptual, ambiguous), is fused as candidates, and its evidence is validated
against the active snapshot like any other. Claims supported only by semantic
discovery are labeled `semantic_candidate`. Coverage and partial freshness are
surfaced in the envelope's existing `semantic_coverage` field and the new
`semantic-status` endpoint.

### 7. Shadow migration protocol

Shadow namespace → asynchronous backfill of active unique content hashes →
dual-write new/changed chunks → independent evaluation of old and new →
coverage and consistency checks → atomic cutover → previous namespace retained
for rollback → removed after the rollback window. Raw scores are never
compared across models; if both rankings are used transiently, ranks are
fused, not scores.

### 8. Measurement admits the optional features

Reranking (local cross-encoder or opted-in OpenAI, one structured top-N call,
cache keyed by normalized query + ordered candidate content hashes + policy +
model + prompt version) and explanation (`AnswerProvider` interface:
`NoAnswerProvider` default, `OllamaAnswerProvider`, `OpenAIAnswerProvider`;
evidence-only schema-constrained prompts; claim re-validation) are built
behind flags. Each is admitted only on measured uplift over the deterministic
baseline; otherwise it is declined and the measurement is recorded at the
gate.

## Task Board

Live status is `docs/plans/PLAN.md`; this table carries the deliverables.

| Task | Deliverable | Dependencies | Status |
| --- | --- | --- | --- |
| P7-SETUP | ADR-0009, optional dependency extras (sentence-transformers, lancedb, openai), `check_phase7.ps1` skeleton, deterministic comparison baseline re-run, packaging-size baseline | Phase 6 | `complete` |
| P7-01 | Semantic domain model, migration `0010` (embedding records, namespaces, repository provider policy, provider usage — no content columns), stores, migration tests | P7-SETUP | `complete` |
| P7-02 | `EmbeddingProvider` interface + `NoEmbeddingProvider` + pinned local sentence-transformers provider + content-hash cache | P7-01 | `pending` |
| P7-03 | `VectorStore` interface, LanceDB adapter, base/delta namespaces, membership-authoritative filtering | P7-01 | `pending` |
| P7-04 | Index-time embedding pipeline: changed-chunk-only queue, coverage tracking, deterministic activation never blocked, crash-safe embedding jobs | P7-02, P7-03 | `pending` |
| P7-05 | Semantic retrieval channel in `AnswerPipeline`: intent-gated, candidate-only fusion, coverage surfaced (`semantic_coverage` no longer hardcoded, `semantic-status` endpoint), deterministic fallback matrix | P7-04 | `pending` |
| P7-06 | **Uplift evaluation:** corpus re-run semantic-on vs the deterministic baseline, conceptual cases declared before measurement, `baseline-phase-7` recorded, admission decision for the semantic channel | P7-05 | `pending` |
| P7-07 | Privacy governance + `OpenAIEmbeddingProvider`: per-repository opt-in, secret detection/redaction, budgets/timeouts/retries/cancellation, usage telemetry without content | P7-02, P7-05 | `pending` |
| P7-08 | Settings surface (Section 12.5 spec gap): `GET/PATCH /v1/settings`, `GET /v1/models`, `POST /v1/models/test`, CLI `settings`/`models` commands, web settings page (opt-in, coverage, model test) with component tests | P7-07 | `pending` |
| P7-09 | Shadow embedding migration: shadow namespace, backfill, dual-write, independent evaluation, atomic cutover, rollback retention, the three `/v1/models/embedding-migrations` endpoints | P7-03, P7-04 | `pending` |
| P7-10 | Optional bounded reranking: intent-gated top-N single call, digest-keyed cache, A/B uplift evaluation, admission decision | P7-06 | `pending` |
| P7-11 | Optional evidence-grounded explanation: `AnswerProvider` interface + `NoAnswerProvider` + Ollama/OpenAI providers, evidence-only prompts, pipeline steps 14–15 claim re-validation, uplift evaluation with 100% citation validity, admission decision | P7-06, P7-07 | `pending` |
| P7-12 | Performance and packaging re-validation on the artifact with embeddings enabled (`measure_phase7_perf.py`), security sweep incl. provider transmission paths, threat-model Phase 7 section, `docs/operations/semantic-search.md`, README, phase gate | P7-06, P7-08, P7-09, P7-10, P7-11 | `pending` |

Sequencing rationale: the embeddings vertical slice lands first (P7-01 →
P7-05), and uplift is measured **immediately** (P7-06) — before the OpenAI
surface, settings, and migration work — so a negative measurement stops the
phase before its most expensive parts are built. Evaluation precedes
sophistication.

## Verification Approach

- Test-first per task: unit, integration against real SQLite and a real local
  model, contract, security, and evaluation layers as applicable. The OpenAI
  provider is tested against a fake transport; no test requires network or a
  real API key.
- Fallback matrix: disabled, failing, slow (timeout), and budget-exhausted
  providers each yield the deterministic answer; the provider-disabled
  evaluation run must equal the deterministic baseline.
- Stale-vector and snapshot-isolation tests extend the Phase 2 suites to the
  vector store.
- Migration cutover/rollback tested mid-backfill and post-cutover.
- Redaction tests prove secrets never reach a provider payload; telemetry
  schema review proves no content fields exist.
- `check_phase0..6.ps1` must exit 0 at every task boundary; `check_phase7.ps1`
  grows per task and is the gate.
- Performance re-measured on the packaged artifact with embeddings enabled,
  with installer size and cold start recorded next to the Phase 6 numbers.
