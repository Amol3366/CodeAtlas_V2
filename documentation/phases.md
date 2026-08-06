# Phases — CodeAtlas

Status: **Phases 0–7 are complete, every gate approved by the user.**
There is no Phase 8. A new phase requires an explicit user decision.

Live task status is `docs/plans/PLAN.md` — never this file. This is the build
order and what each phase actually delivered.

The rule that produced this order: every phase ships a **runnable vertical
slice**, not a layer. Never "backend, then frontend".

---

## Phase 0 — Product contract and evaluation ✅

Versioned domain/error/evidence contracts, representative fixture repositories,
an evaluation runner, a deterministic baseline, the ADR process, and reproducible
local commands.

**Done when:** metrics are reproducible, forbidden claims are tested, and the
baseline is recorded.
Approved. Evidence: `docs/evaluation/baseline-phase-0.{json,md}` (a deliberate
null baseline), ADR-0001, `scripts/check_phase0.ps1`.

## Phase 1 — Repository truth vertical slice ✅

Windows-safe registration and scanning, ignore rules and limits, Git-state
capture, migration `0001`, Python symbol extraction via Tree-sitter + `ast`,
exact symbol lookup with validated evidence, status API, minimal CLI.

**Done when:** a local repository can be registered, indexed, and queried for an
exact Python symbol through the application service, REST, and CLI — with valid
snapshot-bound evidence.
Approved 2026-07-25. Evidence: ADR-0002, `scripts/check_phase1.ps1`.

## Phase 2 — Snapshots, stable chunks, lexical retrieval ✅

Snapshot staging/validation/activation/rollback, logical chunk identity and
versions, syntax-aware chunking, FTS5 search, incremental one-symbol edits.

**Done when:** unrelated chunks stay reusable after a one-symbol edit, an
interrupted index preserves the previous active snapshot, and stale entities
cannot appear in active results.
Approved 2026-07-26. Evidence: migrations `0002`–`0004`,
`tests/integration/test_incremental_indexing.py`,
`tests/integration/test_snapshot_isolation.py`,
`tests/end_to_end/test_crash_recovery.py`,
`docs/operations/chunking-and-search.md`.

## Phase 3 — Polyglot graph and delivery contracts ✅

TypeScript and JavaScript parsing, imports/calls/relations, bounded SQLite graph
traversal, complete versioned REST and CLI adapters, initial MCP adapters,
cross-adapter contract suites.

**Done when:** Python, TS, and JS symbols and relations resolve consistently
through shared services, and REST, CLI, and MCP pass the same evidence-contract
tests.
Approved 2026-07-26, all seven conditions proven. Evidence: migrations
`0005`–`0006`, ADR-0003, ADR-0004, `tests/contract/test_cross_adapter.py`,
`docs/operations/relations-and-graph.md`.

> Measured on `containing_evidence_rate` (0.6250), reported alongside the
> stricter `exact_evidence_rate` (0.4167). Graph answers cite every supporting
> edge, so a call-site line rarely equals a gold range describing a definition —
> a granularity disagreement, not an inaccuracy.

## Phase 4 — Change assurance ✅ *(the core wedge)*

Working-tree and commit-range diff analysis, changed-symbol and public-contract
detection, direct and bounded transitive impact, related tests/docs/config/
schemas, architecture rules, risk ordering, JSON/Markdown/SARIF reports.

**Done when:** the change-analysis fixtures meet the precision, recall,
evidence-validity, snapshot-isolation, and performance targets.
Approved 2026-07-27 **with one target accepted as missed.** Changed-symbol
recall 1.0000, direct-impact recall 1.0000, unsupported-claim rate 0.0000,
finding precision 1.0000 across 24 cases, warm preflight p95 5.151 s, refresh
p95 1.426 s.

> **Changed-symbol precision is 0.9375 against ≥0.95.** Structural, not a defect:
> c020–c022 split one physical `git_changes` diff into three single-symbol
> cases, so the engine — correctly reporting both affected symbols each run —
> has each case count the other's symbol against it. The other 21 score 1.0. The
> corpus was not edited (ADR-0003). Full explanation:
> `docs/evaluation/phase-4-baseline-environment.md`.

Evidence: ADR-0005, migration `0007`, `docs/operations/change-analysis.md`.

## Phase 5 — Persistent ChatGPT-style web application ✅

Eight slices: repository onboarding → conversation schema and history API →
sidebar CRUD → submit/retrieve/persist → typed SSE with cancel, retry, reconnect
→ inline citations and evidence drawer → change-preflight experience → settings,
accessibility, responsive, end-to-end.

**Done when:** history survives frontend and backend restarts; streaming is
idempotent, cancellable, reconnect-safe; citations keep their historical
snapshot; critical workflows pass component, a11y, responsive, and Playwright
tests.
Approved 2026-07-28 **with conditions 1, 2, and 7 reported as only partly met** —
all for one reason: no Playwright suites existed yet. The gap was declared and
carried into Phase 6 rather than dropped. P6-01 paid most of it; the remainder
was owned by P6-STREAM.

Evidence: ADR-0006, migration `0008`, `apps/web/`,
`docs/operations/web-application.md`, `docs/operations/end-to-end-tests.md`.

## Phase 6 — Continuous freshness and hardening ✅

Reconciled and debounced watcher, crash recovery and `codeatlas doctor`, native
packaging and no-elevation install, upgrade/migration workflow with a mandatory
pre-migration checkpoint, backup/restore/deletion/retention, performance,
security, and Windows release validation.

**Done when:** a packaged Windows build passes upgrade, recovery,
backup/restore, deletion, security, performance, and release tests without
losing the last valid active snapshot or chat history.
Approved 2026-07-29. **All nine conditions met.** The packaged build upgrades a
database written by a real earlier build, refuses one from a *newer* build,
loses no snapshot and no conversation. Performance holds **on the artifact**:
refresh p95 1.295 s, preflight p95 3.103 s.

Notable: P6-STREAM introduced accept-then-stream (ADR-0008) and the first
`contract_version` bump in six phases, **1.0 → 1.1**. P6-08 found two defects
and fixed them — snapshots accumulated forever because `prune` had existed since
Phase 2 and nothing ever called it, and an unknown `/v1` path returned a bare
404 instead of the contract envelope.

Evidence: ADR-0007, ADR-0008, migration `0009`,
`scripts/check_phase6.ps1 -Package -Perf`,
`docs/operations/release-validation.md`.

## Phase 7 — Measured semantic uplift ✅ *(gated on explicit approval)*

Provider-neutral embedding interface, content-hash cache, LanceDB base/delta
namespaces with authoritative SQLite membership, shadow migration with atomic
cutover and rollback, budgets/timeouts/retries/cancellation, secret detection and
redaction, per-repository opt-in, content-free telemetry, deterministic fallback.
Reranking and generated explanations were **built and then declined** — their
implemented defaults improved no metric over the admitted semantic baseline.

**Done when:** every admitted semantic feature shows measurable uplift over the
deterministic baseline and passes privacy, fallback, and rollback tests.
Approved 2026-07-31: ten conditions met, two satisfied as recorded declines,
one missed.

> **Missed condition 7: primary evidence Recall@10 is 0.6667 against ≥0.90.**
> The uplift is real (0.6000 → 0.6667) but the target is missed *with and
> without* the semantic layer, so it is not a regression — no earlier phase
> measured conceptual retrieval at all. **Never cite the uplift without
> `docs/evaluation/phase-7-baseline-environment.md`**, which records that the
> lexical stopword defect fixed during P7-06 was worth **+0.53** recall while
> the entire semantic layer on top of it is worth **+0.07**.

Packaged performance holds with embeddings on — refresh p95 0.975 s, preflight
p95 2.298 s, coverage 1.0 — at a 1.05 GB package tree (the torch cost accepted
at the activation gate). Evidence: ADR-0009, migrations `0010`–`0011`,
`docs/evaluation/baseline-phase-7.{json,md}`,
`docs/operations/semantic-search.md`.

---

## Post-Gate Work (no phase)

Delivered after Phase 7's gate, recorded in the handoff log rather than as
reopened tasks:

- Configurable embedding models (ADR-0011) and `.env`-based provider
  configuration.
- Governed answer-provider policy (ADR-0012): Ollama and OpenAI answer
  generation, per-repository, budget-bounded, with the citations unchanged.
- Answer generation measured against a real model.
- 2026-08-04 UX/provider polish: warning codes render as plain-language notes;
  Settings was redesigned around provider cards, summary panels, and
  diagnostics; known OpenAI embedding dimensions auto-resolve from the selected
  model; and the packaged `serve --web --open` shell path was made
  non-cacheable.
- Ephemeral session mode (ADR-0013): `serve --ephemeral` starts from empty
  storage and discards it on exit. It never opens the real database, an
  explicit `--db` outranks it, and the default is unchanged.
- 2026-08-05 inline citations and the on-demand evidence panel: `[n]` markers
  in an answer are buttons that open that evidence; the duplicated evidence
  list and chip row are gone; the panel mounts only once a citation is chosen.
- 2026-08-05: the post-gate Settings and provider work — uncommitted in a
  working tree since 2026-08-04 — was committed as seven commits and merged to
  `main` along with the inline-citations branch.
- 2026-08-05: `pull_ollama_model` was **deleted**. It had no route and no
  caller, so `POST /v1/models/ollama/pull` never existed. CodeAtlas does not
  download models; Settings prints the `ollama pull …` command for the user to
  run. `git show 63c57cd` retains the implementation.
- Per-repository embedding model (ADR-0014), merged 2026-08-06: the local
  provider takes any sentence-transformers model id per repository, chosen in
  Settings. `POST /v1/models/embedding/validate` loads the candidate and
  reports its **measured** width before Save is enabled, because the namespace
  is labelled with that number and a wrong label never raises — it just returns
  worse results for as long as the index lives. Migration `0014`,
  `SCHEMA_VERSION` 13 → 14. OpenAI embedding identity stays `.env`-only.

  The branch had been unmerged since 2026-08-04 and was found only because the
  `documentation/` files were stranded on it. Merging it resurrected the Ollama
  pull route it had built a day before `main` deleted the underlying function;
  **that feature was dropped during the merge** rather than reversing `main`'s
  newer decision. The embedding-model selection it existed for was kept.

## Still Open

Carried into approvals as declared work, with no later phase to absorb them:

1. **The packaged executable is unsigned** — SmartScreen warns on first run.
   Needs a certificate, which is a purchasing decision.
2. **Four conversation-route browser tests are skipped on Chromium**, whose
   renderer crashes navigating to `/conversations/{id}`. A browser defect,
   unresolved upstream. Firefox proves all seven.
3. **No pid-reuse detection in recovery** — if a dead run's pid is reassigned
   before the next start, that repository stays blocked from reindexing.
   `codeatlas doctor` names the run and its pid, so it is visible, not silent.
4. **The packaged semantic tree is 1.05 GB.**
5. **`POST /v1/models/test`'s success branch is untested** — it needs an
   available provider, and no optional extra is installed in the gate
   environment, so only the `PROVIDER_DISABLED` branch is exercised.
6. **Recall@10 is 0.6667 against a ≥0.90 target** (Phase 7, condition 7).
7. **Changed-symbol precision is 0.9375 against ≥0.95** (Phase 4, structural).

**Closed 2026-08-05 — the stale Settings view.** It was carried here as an open
item and was never a caching problem. `web_assets_path()`
(`src/codeatlas/api/web.py`) picks a bundle by launch mode: a source checkout
serves `apps/web/dist`, the packaged executable serves its own copy under
`dist/codeatlas-win64/`. That package was built four days before the Settings
redesign, so it served a bundle that had never contained the new view — while
every probe through `uv run codeatlas serve --web --open` read the *other*,
current bundle and kept "confirming" the fix. Proven by string probe
(`"Repository settings"` present in `apps/web/dist`, absent from the packaged
assets) and fixed by rebuilding the package.

> **Next stale-UI report: ask which command started the server before touching
> cache headers.** Three workarounds were spent on the wrong layer. The
> `no-store` shell headers are still correct and worth keeping — they fix a real
> rebuild-while-tab-open problem — but they were never this problem.

Two of the original seven Phase 7 carry-overs closed on 2026-08-01: the web
settings page is routed at `/settings` and covered by
`apps/web/e2e/settings.spec.ts`, passing on both browser engines.
