# ADR-0009 — Measured Semantic Uplift: Provider-Neutral Embeddings, LanceDB, and Privacy Governance

- Status: accepted
- Date: 2026-07-29
- Decision owners: user/product and implementing agent
- Supersedes: none
- Related: `AGENTS.md` Sections 4.3, 4.4, 6.1, 10, 16, 25;
  `docs/plans/phases/phase-07-measured-semantic-uplift.md`;
  ADR-0001 (local deterministic modular monolith),
  ADR-0003 (evidence granularity), ADR-0004 (relation model)

## Context

Phases 0–6 shipped a complete deterministic product: exact, lexical, graph, and
Git retrieval; change assurance; a persistent web application; and a packaged,
hardened Windows build. Every gate passed without embeddings, a reranker, or an
LLM, exactly as the blueprint required. The deterministic baseline is recorded
and reproducible (`docs/evaluation/baseline-phase-*.json`).

Two facts motivate this decision now:

1. **A measured recall gap exists.** Per ADR-0003, the deterministic engine's
   retrieval gate reports `containing_evidence_rate` 0.6250 and
   `exact_evidence_rate` 0.4167 against the Section 19.3 primary-evidence
   Recall@10 target of ≥ 90%. The gap is concentrated in conceptual questions,
   where no exact symbol or path anchor exists. Semantic retrieval is the
   blueprint's designated channel for that gap — but it is admitted only on
   *measured* uplift, which is why the evaluation harness comes first in the
   phase plan.
2. **The seams for an optional semantic layer already exist.** The response
   envelope carries `semantic_coverage` (hardcoded `0.0` today); the controlled
   derivation enum carries `semantic_candidate` and `model_generated`;
   `SnapshotFreshness.PARTIAL` covers the embeddings-pending state; and
   `AnswerPipeline` names pipeline steps 14–15 (generation and claim
   re-validation) as Phase 7's. `AGENTS.md` Section 6.1 approves "LanceDB only
   when optional vector retrieval is admitted." This ADR is that admission.

The user granted Phase 7's activation gate (product, privacy, and architecture
approval) on 2026-07-29 and approved the phase plan the same day; both are
recorded in `docs/plans/PLAN.md`. Four scoping decisions were made there and
are binding on this ADR:

1. Provider scope: **local + OpenAI opt-in**, behind one provider-neutral
   interface.
2. Local runtime: **sentence-transformers + torch**, accepting the installer
   growth (~1–2 GB against the 44 MB Phase 6 artifact), with the measured size
   recorded here before and after.
3. **One phase, measurement admits**: reranking and explanation are built last
   and admitted only on measured uplift over the deterministic baseline.
4. The deterministic product remains complete with every provider disabled.

## Decision

Eight decisions, fixed so the phase's tasks compose. Deviation requires a new
ADR and user approval.

### 1. One provider-neutral embedding interface, deterministic default

```python
class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...
```

Implementations: `NoEmbeddingProvider` (the default), a pinned local
sentence-transformers provider (CPU), and an OpenAI provider (per-repository
opt-in only). The deterministic code path never constructs a real provider, and
no adapter imports a provider package eagerly — an installation without the
optional extras behaves identically to Phases 0–6.

### 2. Content-hash embedding identity

`embedding_key = hash(content_hash, model_id, dimensions, normalization_version)`.
A normal file edit embeds only changed unique chunk content; unchanged chunk
versions reuse vectors across snapshots and branches. Whole-corpus re-embedding
happens only through an explicit, user-initiated model migration.

### 3. LanceDB behind a narrow interface; SQLite membership is authoritative

A `VectorStore` interface with base and delta namespaces, stored under the
configured data directory (`%LOCALAPPDATA%\CodeAtlas\vectors\` by default).
Every semantic candidate is filtered against active snapshot membership in
SQLite: a physically retained stale vector is never eligible for retrieval.
SQLite remains the system of record; LanceDB holds derived, rebuildable data
only. Compaction is threshold-driven and validated before any base switch.

### 4. Local embeddings via sentence-transformers + torch (user decision)

The local model is pinned by name and revision, and the model ID, dimensions,
and normalization version are recorded on every embedding record. The user
accepted the packaging consequence: the PyInstaller bundle grows from ~44 MB
by roughly 1–2 GB. The measured pre-torch baseline is recorded in this ADR
(below); the post-torch measurement is a Phase 7 gate condition, and if
packaging proves unworkable that fact returns to the user with measurements
rather than a silent runtime swap.

**Packaging-size baseline (pre-torch, measured 2026-07-29 in this
environment):** `dist/codeatlas-win64` folder **42.7 MB**,
`dist/codeatlas-win64.zip` **20.0 MB**, from the Phase 6 artifact rebuilt at
`f9a7812`. The post-torch measurement is compared against these figures at the
phase gate.

### 5. Privacy governance before any transmission

Per-repository provider setting: `none | local | openai`, default `none`.
`local` transmits nothing by construction. `openai` requires explicit
per-repository opt-in, and every outbound payload passes through secret
detection and redaction, per-run and monthly budgets, timeouts, bounded
retries, and cancellation. Telemetry records counts, tokens, latency, and
outcome — never source, prompts, evidence, prompts, or answers. Provider
secrets never appear in GET responses, logs, browser storage, exports, or
diagnostic bundles (Section 12.5).

### 6. Semantic is a discovery channel, never an authority

Semantic retrieval runs only for intents where evaluation justifies it
(conceptual, ambiguous questions), is fused as candidates, and its evidence is
validated against the active snapshot like any other. Claims supported only by
semantic discovery are labeled `semantic_candidate`; a model score never
promotes a candidate to deterministic evidence (Section 4.3). Coverage and
partial freshness surface through the existing `semantic_coverage` envelope
field and the previously unimplemented `semantic-status` endpoint (Section
12.1 — a spec gap closure, not an addition).

### 7. Shadow migration protocol for model upgrades

Shadow namespace → asynchronous backfill of active unique content hashes →
dual-write new/changed chunks → independent evaluation of old and new
namespaces → coverage and consistency checks → atomic cutover → previous
namespace retained for rollback → removed after the rollback window. Raw
scores are never compared across embedding models; if both rankings are used
transiently, ranks are fused, not scores. Migration is user-initiated through
the Section 12.5 endpoints, never automatic.

### 8. Measurement admits the optional features

Bounded reranking (one structured top-N call, intent-gated, cache keyed by
normalized query + ordered candidate content hashes + policy + model + prompt
version; never applied to deterministic resolutions) and evidence-grounded
explanation (`AnswerProvider` interface with `NoAnswerProvider` default;
evidence-only, schema-constrained prompts; claim re-validation at pipeline
steps 14–15) are built behind flags. Each is admitted **only** on measured
uplift over the deterministic baseline; otherwise it is declined and the
measurement is recorded at the gate. "Optional" in the phase checklist means
exactly this.

## Alternatives

1. **sqlite-vec (or SQLite-vss) instead of LanceDB.** Keeps one storage
   technology and a smaller dependency footprint. Rejected for the stated
   scope: `AGENTS.md` Section 6.1 names LanceDB as the approved vector store
   once admitted; the blueprint's base/delta namespace and compaction design
   (Section 4.7.5) assumes an append-friendly columnar store; and the
   `VectorStore` interface keeps a later substitution possible if measurements
   ever justify it.
2. **ONNX-runtime embeddings (e.g. fastembed) instead of
   sentence-transformers.** Far smaller installer (~hundreds of MB vs ~1–2 GB)
   and simpler PyInstaller packaging. Presented to the user at the activation
   gate and **not selected**: the user chose the blueprint's named option,
   sentence-transformers + torch, with the size consequence measured and
   recorded rather than estimated. This ADR carries that measurement duty.
3. **Embeddings enabled by default.** Rejected: Section 4.3 requires the
   deterministic path to be the default; a provider is opt-in per repository,
   and any transmitting provider requires explicit per-repository opt-in.
4. **Defer shadow-migration tooling to a later phase.** Rejected: the first
   embedding model upgrade without it would be an in-place overwrite of the
   active vector index — the failure blueprint Section 15.5 exists to prevent.
   Building it before the second model exists is precisely when it is cheap.
5. **A single global provider setting instead of per-repository.** Rejected:
   Section 4.4's boundary is per repository ("unless the user explicitly
   enables a provider for that repository"). A global switch would let one
   opt-in transmit another repository's content.

## Consequences

- **Dependencies:** new optional extras `semantic-local`
  (sentence-transformers, lancedb) and `semantic-openai` (openai, lancedb).
  They are optional so an installation can exclude them and lose nothing
  deterministic. Version ranges are pinned in `pyproject.toml` and locked in
  `uv.lock`.
- **Schema:** migration `0010` (P7-01) adds embedding records, namespaces,
  per-repository provider policy, and provider-usage tables. Additive and
  forward-only; `SCHEMA_VERSION` moves 9 → 10.
- **Contracts:** `contract_version` stays `"1.1"`; every Phase 7 surface is
  additive (the `semantic_coverage` field already exists). The Section 12.1
  `semantic-status` and Section 12.5 settings/models endpoints are spec gap
  closures, not new surface.
- **Packaging:** installer grows substantially when the local extra is
  bundled; size and cold start are re-measured on the artifact and recorded at
  the gate. Whether the packaged build bundles the local extra by default is a
  P7-12 decision the user sees with measurements attached.
- **Operations:** embedding work is asynchronous and never blocks
  deterministic snapshot activation; coverage is reported, and the embeddings-
  pending state is `PARTIAL` freshness, visible rather than silent.
- **Section 25 basis, stated for audit:** no item on the Section 25 list is
  triggered by default — LanceDB is a derived, replaceable store behind an
  interface, not a new primary database; no cloud dependency is mandatory;
  repository content transmission is disabled by default and per-repository
  opt-in; no breaking contract change exists. The activation approval and this
  ADR are the recorded governance for the admission itself.

## Security and Privacy

- **Trust boundary:** the only new outbound path is the OpenAI provider, and
  it exists only for repositories explicitly opted in. Every payload is
  secret-scanned and redacted before transmission; redaction failure blocks
  transmission.
- **Untrusted content:** repository text remains untrusted input; explanation
  prompts carry verified evidence only, with fixed schemas, and generated
  claims are re-validated before persistence (steps 14–15).
- **Secrets and logging:** provider keys live outside repository configuration
  and never appear in responses, logs, exports, browser storage, or diagnostic
  bundles. Telemetry carries counts, tokens, latency, and outcome only.
- **Budgets:** per-run and monthly token budgets with deterministic fallback
  on exhaustion; disablement, failure, and timeout degrade identically.
- **Local artifacts:** LanceDB files live under the configured data directory,
  subject to the same path-safety rules as the database; deleting the vectors
  directory loses only rebuildable derived data.

## Migration and Rollback

- **Forward:** migration `0010` is additive; the upgrade workflow (P6-07)
  checkpoints before applying it, and a prior-version upgrade fixture gains a
  successor at the version before `0010` in the task that lands it.
- **Rollback of the feature:** set every repository's provider to `none` and
  remove the extras — the system is byte-for-byte the Phase 6 product. The
  vector store is derived data and can be deleted and rebuilt from SQLite
  membership and chunk content hashes at any time.
- **Rollback of a model migration:** the previous namespace is retained until
  the rollback window closes; cutover is atomic and reversible through the
  same endpoints.
- **Rollback of this ADR:** revert; no default behavior changes.

## Approval

Approver: **user**, 2026-07-29, in two recorded steps: the Phase 7 activation
gate (product, privacy, and architecture approval) and approval of the Phase 7
plan, both logged in `docs/plans/PLAN.md`. Exact scope approved: the eight
decisions above, the provider scope (local + OpenAI opt-in), the
sentence-transformers + torch runtime with its measured packaging consequence,
and the measurement-admits rule for reranking and explanation.
