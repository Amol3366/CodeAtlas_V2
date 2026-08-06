# Memory — session log

Append-only working memory for coding agents. Update this at the end of every
task. **This is a convenience log, not evidence.** The authoritative task status
and handoff record is `docs/plans/PLAN.md`; where they differ, that file wins.

Last updated: 2026-08-07

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
      `per-repository-embedding-model` (`f76e1ff`), so `CLAUDE.md` sent every
      agent to five files that were not in the worktree. Recovered file-by-file
      and corrected on 2026-08-06 — see below.

- [x] `documentation/` recovered and corrected (2026-08-06): the five missing
      files restored from `f76e1ff` **without merging that branch**, and
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

- [x] Frontend OpenAI credential entry (ADR-0015), 2026-08-06: the key is
      entered in Settings and stored in the Windows Credential Manager,
      machine-wide, precedence store → `.env`. No migration; `SCHEMA_VERSION`
      stays 14 and `contract_version` stays `1.1`. Gate green: 1926 passed.

## In Progress

**Nothing.** Verified 2026-08-07 rather than assumed.

~~**Ephemeral session mode** awaiting approval of the `AGENTS.md` §8.2
amendment.~~ **Closed 2026-08-07.** The amendment is present in §8.2, ADR-0013
is accepted, and `serve --ephemeral` is in `main`. The entry had outlived the
work by three days.

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
- **A credential is never published to `os.environ`** (ADR-0015). Git runs as a
  subprocess and inherits the parent environment, so a key placed there is
  handed to every Git invocation for the life of the server.
  `resolve_openai_api_key()` returns the value to the caller that needs it and
  writes nothing back. `load_env_file` already has this weakness for the `.env`
  path — that is the thing not to copy.
- **A response never carries a credential, not even part of one.** No masking,
  no last-4: a suffix is still key material, and a response body is logged by
  intermediaries and pasted into bug reports. The contract test asserts the
  exact response key set so a masked field added later fails the suite.
- **An absence test that never executes the leak path proves nothing.** The
  first credential security test passed against a deliberately leaking
  resolver, because a stored key made `status()` take a branch that never
  called it. Mutate the invariant and watch the test fail before believing it.
- **`.env` refills a deleted environment variable.** `create_app` calls
  `load_env_file`, which fills any key the environment lacks — so a test that
  deletes `OPENAI_API_KEY` gets the developer's real key back before the first
  request. Set it *empty* instead; the file cannot override a key that is
  present.
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
  on every run since `ff08d1e` because the gate passed `--semantic-baseline` to
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
- **Five Playwright tests skipped on Chromium, across four spec files** —
  `onboarding-to-citation`, `restart-persistence`, `settings`, and
  `stream-reconnection` all use the skip helper. Upstream renderer defect, not
  application code; Firefox runs every one of them.

  **Correction (2026-08-07):** this used to read "four conversation-route tests
  … on `/conversations/{id}`". The defect has since been hit on more routes, so
  the route-specific wording understated it. `AGENTS.md` Section 20 still
  describes the Phase 6 gate state and is deliberately not edited.
- No pid-reuse detection in crash recovery — a reassigned pid keeps a repository
  blocked from reindexing. `codeatlas doctor` makes it visible, not automatic.
- Packaged semantic tree is 1.05 GB (torch), accepted at the Phase 7 activation
  gate.
- **`POST /v1/models/test` success branch is still untested.** Both tests that
  reach it assert `ok is False`; nothing asserts `ok is True`.

  **Correction (2026-08-07):** the 2026-08-06 work claimed to close this. It did
  not. It made the *failure* deterministic — the test had been passing only
  because no provider was installed, and it issued a real billable OpenAI
  request the moment one was — which was worth doing, but is not the success
  branch. Improving a nearby test is not the same as closing the gap it sits
  next to.
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

  If the feature is ever wanted, `git show 63c57cd` has the implementation.

- ~~**`renderWithProviders` accepts a `client` option nothing passes.**~~
  **Not true as of 2026-08-07.** `SemanticSettings.test.tsx:147` passes one, to
  prove the route waits for fresh settings instead of rendering cached route
  data. The option is a used extension point, not a dead one.

- [x] Pushed to GitHub (2026-08-06). `main` is synced with `origin/main`.
      Push protection blocked it on a placeholder Slack token in
      `test_secret_redaction.py`; the allowlist did not take effect, so the
      commit was rewritten (104 commits, no force-push — the remote tip was one
      commit behind the rewrite point). 29 commit hashes cited as evidence were
      remapped, 57 references repaired. Full account in `docs/plans/PLAN.md`.

- [x] Status pass (2026-08-07): corrected two claims this log had wrong — the
      `POST /v1/models/test` success branch was **not** closed, and the
      `renderWithProviders` known issue was false. See Known Issues.

## Next Up

No assigned work. Candidates, in the order they'd most likely be picked up:

1. **Close the untested `POST /v1/models/test` success branch.** Now the
   cheapest item on the list: both semantic extras are installed in this
   environment, so a test can finally reach `ok is True` — that was the blocker
   when the item was carried from the Phase 7 gate. Note the trap found on
   2026-08-06: a test that reaches the success branch with a real key configured
   will issue a **real billable request**, so it must stub the provider rather
   than call it.
2. **Investigate Recall@10** (0.6667 against a ≥0.90 target). The stopword
   finding suggests lexical quality, not embedding quality, is where the
   remaining headroom is: that one fix was worth +0.53 recall while the entire
   semantic layer on top of it was worth +0.07.
3. **Decide on code signing** — a purchasing decision, not an engineering one.
   Until then the packaged executable is unsigned and SmartScreen warns.
4. **Consider deleting the five stale local branches** whose content is in
   `main` but which point at pre-rewrite commit objects, so `git branch`
   stops implying unmerged work. `backup-before-rewrite` can go with them once
   the rewrite is trusted.

Closed since this list was written:

- ~~Rebuild the package whenever the web app changes.~~ **Delivered.** The
  guard exists: `test_the_packaged_web_assets_match_the_source_build`
  (`tests/end_to_end/test_packaged_build.py:198`) compares digests and failed
  the gate twice on 2026-08-06, each time correctly, which is exactly the
  self-reporting the item asked for.
- ~~Decide the fate of branch `per-repository-embedding-model`.~~ **Merged
  2026-08-06** as ADR-0014. The lesson stands: it sat unmerged for two days,
  took the `documentation/` folder with it, and its merge silently resurrected
  a feature `main` had deliberately deleted. A feature branch left to rot does
  not stay still; it drifts against decisions made after it.
- ~~ADR-0015: frontend OpenAI API-key entry.~~ **Merged 2026-08-06.** Built
  against the Windows Credential Manager rather than a DPAPI blob in SQLite:
  keeping the secret out of the database makes the Section 12.5 export and
  bundle clauses structurally true rather than a redaction step to remember.
