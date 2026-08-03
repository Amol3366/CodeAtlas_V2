# Memory — session log

Append-only working memory for coding agents. Update this at the end of every
task. **This is a convenience log, not evidence.** The authoritative task status
and handoff record is `docs/plans/PLAN.md`; where they differ, that file wins.

Last updated: 2026-08-04

## Current Phase

**None.** Phases 0–7 are all `complete` with user-approved gates. The Section 20
development order is finished. A new phase requires an explicit user decision.

## Completed

- [x] Phase 0 — contracts, fixtures, evaluation runner, ADR process
- [x] Phase 1 — registration, scanning, Python symbols, exact lookup (2026-07-25)
- [x] Phase 2 — snapshots, stable chunks, FTS5, incremental (2026-07-26)
- [x] Phase 3 — TS/JS parsing, relation graph, REST/CLI/MCP contracts (2026-07-26)
- [x] Phase 4 — change assurance, impact, risk ordering, JSON/MD/SARIF (2026-07-27)
- [x] Phase 5 — persistent web app, SSE, citations, evidence drawer (2026-07-28)
- [x] Phase 6 — watcher, recovery, packaging, upgrade, backup/restore (2026-07-29)
- [x] Phase 7 — semantic uplift, providers, budgets, redaction (2026-07-31)
- [x] Post-gate: configurable embedding models (ADR-0011), `.env` provider
      configuration, governed answer-provider policy (ADR-0012), answer
      generation measured against a real model (2026-08-02)
- [x] `documentation/` folder — PRD, architecture, rules, phases, design,
      memory (2026-08-03)
- [x] Post-gate UX/provider polish (2026-08-04): Settings visual redesign,
      known warning messages rendered in plain language, embedding dimension
      auto-detection for known OpenAI models, Ollama answer-model download from
      Settings, and packaged shell cache headers for `serve --web --open`.

- [x] Ephemeral session mode (ADR-0013), 2026-08-04: `serve --ephemeral` starts
      from empty storage and discards it on exit. Default unchanged.

## In Progress

**Ephemeral session mode** on branch `ephemeral-session-mode` — code complete
and verified; the `AGENTS.md` §8.2 amendment is awaiting user approval.

**Stale Settings view (Part B)** — deliberately not fixed. Root cause is not
established, three prior workarounds already failed, and the diagnosis needs one
user observation (open `/settings` in a fresh tab rather than the restored one).
Specified in `docs/superpowers/specs/2026-08-04-ephemeral-session-and-stale-shell-design.md`.

## Decisions Made

Full rationale lives in `docs/adr/`. The ones that shape day-to-day work:

- **Local, deterministic, modular monolith** (ADR-0001). SQLite is the system of
  record. No microservices, no second database.
- **Evidence granularity is `containing_evidence_rate`** (ADR-0003). Graph
  answers cite every supporting edge, so a call-site line rarely equals a gold
  range describing a definition. The evaluation corpus was **not** edited to
  make the number look better.
- **Accept-then-stream message submission** (ADR-0008) — the only
  `contract_version` bump so far, 1.0 → 1.1. Everything through Phases 0–5 was
  deliberately additive so the version could stay put.
- **Repository-scoped embedding namespaces** (ADR-0010); SQLite membership is
  authoritative over LanceDB contents.
- **Governed answer-provider policy** (ADR-0012). Generated prose sits on top of
  evidence already gathered; citations, lines, and confidence never change.
- **`.env` is read from the project folder, not the working directory.** A
  repository you index must never be able to configure the tool indexing it.
- **uvicorn runs with `access_log=False`.** One log line per request on the
  event-loop thread means a server whose stdout nobody drains blocks forever.
  This looked like a crash for a while; the wrong original diagnosis is kept in
  `docs/evaluation/phase-6-baseline-environment.md`.
- **Reranking and generated explanations were built, measured, and declined** —
  neither improved a metric over the admitted semantic baseline.
- **`AGENTS.md` and `CLAUDE.md` are one contract.** `AGENTS.md` holds the
  maintained body. Historical citations to either name were deliberately not
  rewritten — rewriting evidence a gate was approved on is not a rename.
- **Known warning codes should be explained to users.**
  `EVIDENCE_EXCERPT_TRUNCATED` and `LEXICAL_QUERY_RELAXED` are still real
  machine-readable warning codes, but the web answer view now renders them as
  plain-language notes. Lexical search means word/text matching against the
  active snapshot; it is evidence of wording, not proof of behavior.
- **Embedding dimensions follow the selected model where possible.** Known
  OpenAI embedding widths are resolved automatically; unknown OpenAI models
  still require an explicit dimension. Local model widths are detected when the
  model loads.
- **Ollama model download is separate from saving settings.** Settings can call
  `POST /v1/models/ollama/pull`, but a failed or slow pull must not silently
  change a repository's provider configuration.

## Known Issues

- **The explanation A/B is no longer a gate step** (fixed 2026-08-04). It threw
  on every run since `2d7e511` because the gate passed `--semantic-baseline` to
  a script rewritten to take `--dataset`. Removed rather than re-pointed: the
  rewrite measures a live `llama3.2:3b`, and `--check` measures first and
  compares afterwards, so any invocation needs Ollama running. Making the gate
  depend on an optional provider is exactly what §4.3 forbids. Refreshing the
  artifact is now a documented manual command at the call site.
- `test_a_genuinely_killed_process_is_recovered_and_can_reindex` flakes under
  full-suite load on Windows with `sqlite3.OperationalError: disk I/O error` —
  a genuinely killed process can leave its SQLite handle briefly held. Passed
  4/4 in isolation and on the next full run. Not investigated further.

Carried into gate approvals as declared work rather than dropped:

- Unsigned packaged executable → SmartScreen warns on first run. Needs a
  purchased certificate.
- Four conversation-route Playwright tests skipped on Chromium (renderer crashes
  on `/conversations/{id}`; upstream browser defect). Firefox proves all seven.
- No pid-reuse detection in crash recovery — a reassigned pid keeps a repository
  blocked from reindexing. `codeatlas doctor` makes it visible, not automatic.
- Packaged semantic tree is 1.05 GB (torch), accepted at the Phase 7 activation
  gate.
- `POST /v1/models/test` success branch untested — needs an installed provider
  extra; only `PROVIDER_DISABLED` is exercised.
- Primary evidence Recall@10 = 0.6667 vs a ≥0.90 target. Missed with *and*
  without the semantic layer, so not a regression. Never cite the uplift without
  `docs/evaluation/phase-7-baseline-environment.md`: the lexical stopword fix
  was worth +0.53, the semantic layer +0.07.
- Changed-symbol precision = 0.9375 vs ≥0.95. Structural — c020–c022 split one
  physical diff into three single-symbol cases that count each other's symbols
  against them. The other 21 cases score 1.0.
- User still observed the older Settings view until a manual reload after the
  cache/navigation fix. The exact command path
  `uv run codeatlas serve --web --open` was probed successfully on 2026-08-04:
  the running server returned non-cacheable shell responses, served the new
  bundle, and a browser probe confirmed the Settings link performs a document
  navigation. No further debug was requested.

## Next Up

No assigned work. Candidates, in the order they'd most likely be picked up:

1. Close the untested `POST /v1/models/test` success branch by installing an
   optional extra in a gate environment.
2. Investigate Recall@10 — the stopword finding suggests lexical quality, not
   embedding quality, is where the remaining headroom is.
3. Decide on code signing (a purchasing decision, not an engineering one).
