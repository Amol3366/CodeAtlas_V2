# Memory — session log

Append-only working memory for coding agents. Update this at the end of every
task. **This is a convenience log, not evidence.** The authoritative task status
and handoff record is `docs/plans/PLAN.md`; where they differ, that file wins.

Last updated: 2026-08-06

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

      **Correction (2026-08-06):** only `memory.md` ever reached `main`. The
      other five were written on the unmerged branch
      `per-repository-embedding-model` (`f30e74c`), so `CLAUDE.md` sent every
      agent to five files that were not in the worktree. Recovered file-by-file
      and corrected on 2026-08-06 — see below.

- [x] `documentation/` recovered and corrected (2026-08-06): the five missing
      files restored from `f30e74c` **without merging that branch**, and
      corrected for what `main` actually had at that moment.

      **Superseded hours later**, when the user asked for the embedding-model
      feature and that same branch was merged deliberately. The ADR/migration
      ranges corrected *down* to `0013` went back to `0014`, and the
      per-repository `embedding_model` field became real. The correction about
      the Ollama pull endpoint survived the merge and is now enforced in code —
      see Decisions. Recovering the docs first was still right: it kept a docs
      fix from silently importing a feature.
- [x] Post-gate UX/provider polish (2026-08-04): Settings visual redesign,
      known warning messages rendered in plain language, embedding dimension
      auto-detection for known OpenAI models, and packaged shell cache headers
      for `serve --web --open`.

      **Correction (2026-08-05):** this entry previously also claimed "Ollama
      answer-model download from Settings". That is not delivered — see Known
      Issues. Only the provider-side function exists.

- [x] Inline citations and the on-demand evidence panel (2026-08-05):
      `[n]` markers in an answer are buttons that open that evidence, the
      duplicated evidence list and chip row are gone, and the evidence panel
      mounts only once a citation is chosen.

- [x] Committed and merged to `main` (2026-08-05): the post-gate Settings and
      provider work had been sitting uncommitted in a working tree since
      2026-08-04. Now seven commits on `settings-and-provider-polish`, merged
      with the inline-citations branch into `main`.

- [x] Ephemeral session mode (ADR-0013), 2026-08-04: `serve --ephemeral` starts
      from empty storage and discards it on exit. Default unchanged.
- [x] `README.md` "Running the project" section (2026-08-04): install, serve,
      CLI, dev loop, packaged build, quality gate, and a troubleshooting table —
      each command explained rather than just listed. Documentation only; no
      code, contract, or migration change.

- [x] Per-repository embedding model (ADR-0014), 2026-08-04: the local provider
      takes a model id per repository, chosen in Settings and measured before
      save. Migration `0014`, `SCHEMA_VERSION` 14. OpenAI stays `.env`-only.

- [x] Semantic extras installed and ADR-0014 merged (2026-08-06). The reported
      "embedding option is not clickable, and OpenAI is missing" was **not a
      defect**: both providers are gated on an optional Python extra, neither
      was installed, so only "Disabled" was selectable and OpenAI rendered
      greyed with its requirement. `uv sync --extra semantic-local --extra
      semantic-openai` fixed it; `OPENAI_API_KEY` in `.env` had been correct all
      along. ADR-0014 (per-repository embedding model) merged from the branch it
      had been stranded on since 2026-08-04, **minus** the Ollama pull feature —
      see Decisions. Gate green: 1886 passed.

## In Progress

**Ephemeral session mode** on branch `ephemeral-session-mode` — code complete
and verified; the `AGENTS.md` §8.2 amendment is awaiting user approval.

~~**Stale Settings view (Part B)** — deliberately not fixed.~~ **Closed
2026-08-05.** Root cause was a packaged build predating the redesign, not the
browser; see Known Issues. The user observation the old spec asked for was never
needed — comparing the two built bundles answered it. The unused half of
`docs/superpowers/specs/2026-08-04-ephemeral-session-and-stale-shell-design.md`
is superseded.

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
- **An embedding model is measured, never declared.** A candidate local model is
  loaded once and asked for its width, because the namespace is labelled with
  that number and a wrong label never raises — it just returns worse results for
  as long as the index lives. The check is a client-side gate: the API cannot
  verify a caller ran it, and a flag the client sets would be enforcement in
  name only.
- **`build_embedding_provider` is the one place a model is resolved.** The
  migration backfill reaches it through `ProviderFactory`, so ADR-0014 needed no
  change to `EmbeddingMigrationService`. Two resolution sites could disagree
  about which model is current, and a namespace whose label disagrees with its
  contents fails silently.
- **CodeAtlas does not download models.** Settings names the model and shows the
  `ollama pull …` command; the user runs it. `pull_ollama_model` was deleted on
  2026-08-05 as unreachable, and the ADR-0014 branch — written a day earlier —
  carried a route and UI for it. Merging on 2026-08-06 would have resurrected
  the feature silently, calling a function `main` no longer has, so **the pull
  was dropped during the merge** and `main`'s newer decision preserved. A pull
  is a multi-gigabyte network operation, and putting it behind a button in a
  settings form makes a slow or failed download look like a failed save.

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
- ~~User still observed the older Settings view until a manual reload.~~
  **Root-caused 2026-08-05, and it was never a caching problem.** There are two
  built web bundles, and `web_assets_path()` (`src/codeatlas/api/web.py`) picks
  between them by launch mode: a source checkout serves `apps/web/dist`, a
  frozen build serves `sys._MEIPASS/web`. The packaged build under
  `dist/codeatlas-win64/` dated from **2026-07-31**, four days before the
  Settings redesign, so running the packaged executable served a bundle that had
  never contained the new view. Probing `uv run codeatlas serve --web --open`
  kept "confirming" the fix because that path reads the *other*, current bundle.
  Verified by string probe: `"Repository settings"` present in
  `apps/web/dist`, absent from the packaged assets. Fixed by rebuilding the
  package.

  **Lesson for the next stale-UI report: ask which command started the server
  before touching cache headers.** Three workarounds were spent on the wrong
  layer. The `no-store` shell headers are still correct and worth keeping — they
  fix a real rebuild-while-tab-open problem — but they were never this problem.

- ~~**`pull_ollama_model` is not reachable.**~~ **Closed 2026-08-05 by deleting
  it.** The function had no route and no caller, so
  `POST /v1/models/ollama/pull` never existed. `README.md` was corrected first,
  then the dead code and its two tests were removed rather than left as an
  unreferenced building block. CodeAtlas does not download models: the Settings
  UI prints the `ollama pull …` command for the user to run in a terminal, which
  is what `docs/operations/answer-generation.md` has always said.

  If the feature is ever wanted, `git show 3c631ce` has the implementation.

- **`renderWithProviders` accepts a `client` option nothing passes.** Harmless
  unused extension point in `apps/web/src/test/harness.tsx`.

## Next Up

0. **ADR-0015: frontend OpenAI API-key entry backed by Windows DPAPI.** Chosen
   by the user on 2026-08-06 over `.env`-only and over plaintext SQLite. Needs
   a secret-store adapter, a write-only endpoint, a GET that reports only
   set/not-set (Section 12.5 forbids the value appearing in any GET, log,
   export, or diagnostic bundle), redaction coverage, and a migration. Not
   started.


No assigned work. Candidates, in the order they'd most likely be picked up:

1. **Rebuild the package whenever the web app changes.** The four-day-old
   packaged bundle cost three misdiagnosed debugging rounds. Consider making
   `build_package.ps1` refuse when `apps/web/dist` is newer than the release
   tree, so the mismatch reports itself instead of surfacing as a phantom UI
   regression.
2. Close the untested `POST /v1/models/test` success branch by installing an
   optional extra in a gate environment.
3. Investigate Recall@10 — the stopword finding suggests lexical quality, not
   embedding quality, is where the remaining headroom is.
4. Decide on code signing (a purchasing decision, not an engineering one).
5. ~~Decide the fate of branch `per-repository-embedding-model`.~~ **Done
   2026-08-06 — merged.** The lesson stands: it sat unmerged for two days, took
   the `documentation/` folder with it, and its merge silently resurrected a
   feature `main` had deliberately deleted. A feature branch left to rot does
   not stay still; it drifts against decisions made after it.
