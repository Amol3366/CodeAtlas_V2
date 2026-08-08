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

- [x] CLI impact UX (2026-08-08): `codeatlas impact` now prints a verdict by
      default — a `text` rendering shaped for a terminal, with findings
      risk-ordered and gaps carrying their reasons. Added `--fail-on <severity>`
      (new exit code `7`, deliberately not `EXIT_POLICY_FAILURE`, so CI can tell
      a risky change from a bad path) and `--since <ref>`, which analyses from a
      real merge base. `contract_version` `1.1`; no migration.

      **It opened by fixing a defect the previous slice shipped and pushed:**
      `--format pr` was advertised in both commands' `--help` and rejected by
      their guards, because that slice updated the help strings and
      `_print_report` and left two allow-lists spelling
      `{"json", "markdown", "sarif"}`. Its cross-adapter test covered REST and
      MCP and never invoked the CLI. Both guards now check one
      `ADVERTISED_FORMATS` set that a parameterised test iterates — when `text`
      was added, its coverage appeared automatically, which is the point.

      Three things worth remembering. **`--since main` is not `--base main`**: a
      two-dot diff against a moved trunk reports the trunk's own commits as your
      changes, inverted, so it needed a real `merge_base` on the Git adapter.
      **The merge-base resolution lives in `ChangeAnalysisService.analyze_since`,
      not the CLI** — resolving a root and invoking Git is repository logic, and
      an adapter doing it would leave REST and MCP unable to offer the same
      capability. And **`_SEVERITY_ORDER` had been duplicated across two
      renderers** by the PR-export slice — the same slice that carefully
      extracted the *escaping* to avoid exactly that. It now lives once, in
      `contracts.py`, where `--fail-on` also reaches it.

      Deliberately unchanged: `impact` still exits `4` when there are no
      findings, so a clean change returns non-zero. It is surprising and it is
      documented in the command's own docstring; redefining it silently would be
      a breaking change dressed as an improvement. `--fail-on` gets its own code
      instead.

- [x] PR-ready Markdown export (2026-08-07): a second renderer beside
      `render_markdown`. Verdict first, findings and test gaps expanded,
      supporting detail in `<details>`, bounded at 60,000 characters with any
      cut declared rather than silently dropped. Available identically through
      REST, CLI, and MCP. `contract_version` stays `1.1`; no migration.

      **It also closed a defect worth remembering.** Neither existing renderer
      showed the `GapReason` data from ADR-0016 — so the work that most
      distinguishes CodeAtlas was visible *only* in the web Preflight screen,
      and every CLI, REST, and MCP consumer saw bare gap names with no
      explanation. Shipping a feature to one surface and assuming the others
      followed is the recurring shape of this class of bug; the same pattern
      was flagged for `related_tests` and is still open.

      **SARIF deliberately unchanged.** A test gap is explicitly not a finding,
      so emitting gaps as SARIF results would assert exactly what ADR-0016
      refuses. Verified by an empty `git diff` on `sarif_report.py`.

      The Markdown escaping moved to `delivery/markdown_text.py` first, shared
      by both renderers, with a parity test that fails if they ever stop
      sharing it. Two copies of security-relevant escaping is one that gets
      reviewed and one that does not.

      ~~Follow-up recorded: `_print_report` falls through to JSON for an
      unknown `--format`, so `--format prr` prints JSON and reports success.~~
      **Wrong, corrected 2026-08-08.** Both `impact` and `analysis` validate
      the format *before* reaching `_print_report`, so its `else` branch is
      unreachable from either and no such leniency exists.

      **The real defect went the other way and was not recorded at all:
      `--format pr` was advertised in both commands' `--help` and rejected by
      their guards.** The slice updated the help strings and `_print_report`
      and left two allow-lists spelling `{"json", "markdown", "sarif"}`. Its
      cross-adapter test asserted REST and MCP returned identical `pr` output
      and never invoked the CLI, which is exactly why the guard was never
      exercised. Fixed 2026-08-08: both guards now check one
      `ADVERTISED_FORMATS` set that a parameterised test iterates, so a format
      added without a guard fails in the suite rather than in a terminal.

      The lesson is not "check the guards". It is that a capability claimed
      across N adapters needs a test that exercises N adapters — the same
      one-surface-missed shape that hid the `GapReason` data in the first
      place.

- [x] Preflight promoted to a first-class web screen (2026-08-07): `/preflight`
      launches an analysis and `/preflight/:analysisId` loads the persisted
      report, so an audit record survives a reload instead of living in
      component state. The screen renders what the API always sent and the old
      147-line embedded component discarded — changed symbols and files, impact
      edges **with their derivation**, and the `test_gaps` / `GapReason` pairs
      from ADR-0016. Frontend-only: nothing under `src/codeatlas/` changed.

      Three things worth remembering. **Evidence renders inline without an
      excerpt**, because `GET /v1/evidence/{id}` re-verifies *stored*,
      snapshot-scoped evidence while analysis evidence carries a `side` — the
      base side of a working tree has no snapshot, only a commit, and routing
      one through the other would erase that distinction. **The e2e harness
      serves `apps/web/dist` via `vite preview`**, so the Playwright spec failed
      against a stale bundle until `npm run build` was re-run — the same class
      of trap as the 2026-08-05 Settings incident, now on the e2e path. And a
      run of component tests that failed *including a negative assertion* turned
      out to be a shell whose working directory had drifted out of `apps/web`,
      so vitest ran without `vite.config.ts` and therefore without jsdom; when
      everything fails, including what cannot be wrong, suspect the harness.

      Follow-up recorded: `ChangeAnalysisRequiresGitError` is declared
      `retryable = True` (`src/codeatlas/domain/errors.py:155`), which is wrong
      for a condition that cannot change on retry. The screen suppresses retry
      for that code rather than changing the backend flag.

- [x] CodeAtlas V2 working guide (2026-08-07): added
      `documentation/codeatlas-v2-working-guide.md` as a human-readable overview
      of what CodeAtlas is, how it works, its main operating scenarios, change
      preflight, semantic/hybrid retrieval boundaries, and how it differs from
      IDEs, code search, AI PR review, static analysis, and generic codebase
      chat. `README.md` now points to it from the docs list. Documentation
      only; no product contract, schema, or code change.

- [x] Derivation-tiered test edges and gap reasons (ADR-0016), 2026-08-07:
      ten-task feature. `SymbolKind.FIXTURE` (declared since Phase 0) is now
      emitted for `@pytest.fixture`-decorated functions; `conftest.py`
      classifies as test code; `RelationKind.CONSUMES_FIXTURE` is a new
      stored, citable, intermediate relation kind excluded from impact
      expansion; `TESTS` is now derivation-tiered
      (`high_confidence_heuristic` direct, `low_confidence_heuristic`
      fixture- or helper-mediated); `GapReason`/`GapReasonCode` explain every
      remaining `test_gaps` entry with its strongest near-miss. Governing
      principle: a weak edge explains a gap, it never closes it — finding a
      fixture- or helper-mediated path never removes the symbol from
      `test_gaps`. `RESOLVER_VERSION` moved `1.1.0` → `1.2.0`;
      `contract_version` stayed `"1.1"`; `SCHEMA_VERSION` stayed `14`
      (additive fields, no migration). Full gate green: `ruff check`,
      `mypy --no-incremental src`, and `pytest -q` all passed (1974 passed, 3
      skipped) after fixing two pre-existing lint findings in
      `tests/unit/test_impact.py` (an unused import and a line-length
      violation left over from Task 9's end-to-end test, unrelated to this
      task's own changes but caught by this task's gate run).
      **Evaluation surprise:** the re-measured Phase 4 corpus
      (`docs/evaluation/test-mapping-2026-08-07.md`) came back **byte-for-byte
      identical** to `docs/evaluation/baseline-phase-4.json`/`.md` — every
      metric unchanged (changed-symbol recall 1.0000, direct-impact recall
      1.0000, changed-symbol precision 0.9375, unsupported-claim rate
      0.0000). The task brief anticipated this feature would make
      `scripts/check_phase4.ps1`'s Phase 4 baseline `--check` step fail and
      instructed that the failure be documented rather than silenced by
      regenerating the baseline. Instead, running `check_phase4.ps1` in full
      (frozen sync, tests, lint, types, dataset validation, all three
      baselines including Phase 4 with `--check`) **passed end to end**,
      because `tests/evaluation/cases` does not contain a case whose expected
      findings depend on fixture- or helper-mediated `TESTS` edges or on
      `GapReason` content — the new derivation paths are real and covered by
      unit/integration tests from Tasks 1–9, just not by this particular
      corpus. Per the project owner's ruling, the Phase 4 baseline files were
      not touched regardless of this outcome. See ADR-0016 and
      `docs/evaluation/test-mapping-2026-08-07.md` for the full record.

- [x] Evaluation fixture gate corrected (ADR-0017), 2026-08-08: the
      `exact_symbol_resolution` investigation this file listed as candidate 1
      found a **harness defect, not an engine defect.**
      `SUPPORTED_FIXTURES` in `evaluation/engine_adapter.py` was written in the
      Phase 1 commit (`b2ea98e`) and never revisited, so `tsjs_app` (TypeScript,
      Phase 3) and `git_changes` (Git, Phase 4) were gated out of the
      measurement. A gated case is answered with `_abstention` and scores
      **`False`, not `None`** — `exact_symbol_resolved` is `None` only when a
      case has no expected symbols — so 16 of 39 scored query cases counted as
      misses the engine never saw. Widening the tuple moved
      `exact_symbol_resolution` 0.3846 → 0.6154, `abstention_correctness`
      0.5250 → 0.7500, `mean_reciprocal_rank` 0.3846 → 0.6154, and
      Recall@10 0.5556 → 0.6508. Every change-side metric is unchanged, so the
      Phase 4 gate approval is unaffected. `baseline-phase-3` and
      `baseline-phase-4` were regenerated; **`baseline-phase-1` and
      `-2` deliberately were not** — their gate scripts are marked SUPERSEDED
      and document that re-running them exits 5 by design, so regenerating them
      would overwrite the record those gates were approved on. The corpus was
      not edited (ADR-0003 holds). Full gate green: 2081 passed, 3 skipped,
      ruff clean, mypy clean on 337 files, all baselines reproduce, exit 0.

      **The target is still unmet — 0.6154 against 0.98.** This corrected a
      measurement error; it did not close the gap, and it must not be cited as
      though it did.

      Two things worth remembering. **A test that derives its expectation from
      the constant it tests cannot detect that the constant is wrong** —
      `test_unsupported_intents_abstain_rather_than_guess` builds its
      expectation by reading `SUPPORTED_FIXTURES`, so it passed for four phases
      against a stale value. The replacement guard derives from the *corpus*
      instead. And the constant directly above it, `SUPPORTED_INTENTS`, *was*
      maintained, with comments recording its Phase 2 and Phase 3 widenings —
      one gate tracked the engine and its neighbour did not, while both fed the
      same scoring path.

- [x] Graph cases declare their subject (ADR-0018), 2026-08-08: follow-on from
      ADR-0017, and it **corrects a claim ADR-0017 made.** `_query_term` fed
      `expected_symbols[0]` as the thing being asked about, but for a graph
      query `expected_symbols` is the *answer* and the subject is not in it —
      "Who calls `total`?" expects `render` and is about `total`, so the harness
      asked who calls `render` and scored the correct answer to that different
      question as a miss. `QueryCase` gained an optional `query_subject`
      (absent = `expected_symbols[0]`, so all 40 cases stayed valid); six cases
      declare it. `exact_symbol_resolution` 0.6154 → 0.6667, Recall@10
      0.6508 → 0.6984. Gate green: 2084 passed, 3 skipped, exit 0.

      **Evidence precision fell while recall rose** — exact/valid
      0.6618 → 0.6400, containing 0.7353 → 0.7067 — because the correct subject
      returns more evidence (the supporting edges) and per ADR-0003 a call-site
      line rarely equals a gold definition range. Quoting either number alone
      misrepresents the change.

      **ADR-0017 was wrong** to call the remainder a TypeScript capability gap:
      three of the six affected cases are Python, and the engine answers all of
      them when asked properly. ADR-0017's body is left as written with a
      pointer to ADR-0018, which carries the correction.

      **q007 deliberately still fails.** Its honest subject is
      `PaymentService.capture`; declaring `PaymentService` instead would have
      made it pass by tuning the corpus to current engine behaviour, which is
      what ADR-0003 forbids. It is now a precise finding instead of a shrug.

      **Three consecutive investigations have found the measuring apparatus at
      fault rather than the engine** (`exact_symbol_resolution`,
      `valid_evidence_rate`, this). The harness has had far less scrutiny than
      the code it measures, and it is the only thing between a reader and a
      false account of the product. Probe the service directly before calling
      anything an engine gap.

- [x] Export evidence labelling (ADR-0019), 2026-08-08: the first **engine**
      defect of this series, and it was narrower than ADR-0018's description of
      it. `GraphQueryService` labelled every evidence item with the edge's
      *source*. That is right for almost every relation kind, which cites a
      reference site (a call, an import, a name use) living inside the source.
      `EXPORTS` is the exception: it cites the **exported symbol's own
      definition**, so `orders.ts:1-3` — which is `export interface Order` —
      was labelled `src.orders`. The evidence named one symbol and showed
      another: exactly the ADR-0016 defect on a new surface.

      Fixed by `_cited_symbol`: label with the symbol whose definition the range
      covers. `exact_symbol_resolution` 0.6667 → 0.6923 and **nothing else
      moved** — the correct signature for a pure relabel. Gate green: 2086
      passed, 3 skipped, exit 0.

      **The `IMPORTS` counterpart is pinned by its own test.** An import range
      is the import statement, inside the importing module, so that label must
      not flip along with `EXPORTS`; a test asserting only the new behaviour
      would have allowed fixing exports by breaking imports.

      Why it survived since Phase 3: the integration tests asserted **claim text
      only**, never an evidence label. The claims were always correct —
      `_claims` resolves the other party by direction — so `src.orders exports
      Order` read fine beside mislabelled evidence.

      **ADR-0018 recorded the symptom as the diagnosis** ("returns `src.client`
      at rank 1"). Reading each evidence item against the source lines it cites
      is what separated the real defect from the harness issue; run output alone
      could not.

- [x] Relations in every graph answer (ADR-0020), 2026-08-08: closing the other
      half of ADR-0018's finding #1 turned out to require a **product** change,
      not a harness one. The answer to an outbound relation question existed
      only as English — `Claim` has `text` but no structured subject/object, and
      evidence labels name the containing symbol, which is the subject for an
      outbound query. So there was nowhere in the response to read the answer
      from. An MCP client (a named PRD user) asking "who calls X" got prose and
      evidence and nothing machine-readable between them.

      `RelationStep` already existed for exactly this, and
      `BoundedGraphTraversal.expand` **already computed the paths for every
      graph query** — `_respond` discarded them for everything but `trace`. The
      fix is "stop throwing away data we already have": `include_paths` removed,
      `relation_paths` populated always. Additive per ADR-0004;
      `contract_version` stays `1.1`.

      `exact_symbol_resolution` 0.6923 → 0.7436, and
      **`relation_path_correctness` 0.0000 → 0.2083.** That metric had been
      structurally incapable of being non-zero since Phase 3: ten of the twelve
      cases with `expected_relations` got an empty list, and the harness
      rendered a path as `" -> ".join(step.target …)` while the corpus writes
      `"render CALLS total"`. It also has **no gate target**, so nothing caught
      it — six baselines carried a dead number twelve corpus expectations were
      feeding.

      **The product change alone moved no metric**, measured before the harness
      changes. That is the honest ordering: the response gained data, then the
      harness could read it.

      **0.2083 is not a good score and is not presented as one.** The residual is
      largely naming convention — the corpus writes `orders EXPORTS Order`, the
      engine emits `src.orders`. The corpus was **not** edited to close that
      (ADR-0003); whether to qualify the corpus or compare suffixes is an open
      decision.

      `TRACE_FLOW` is deliberately excluded from `GRAPH_ANSWER_END`: a flow
      answer includes its origin, a relation answer never does. Collapsing them
      would have traded two fixed cases for several broken ones.

      All three harness tests passed on first write, so each was
      **mutation-checked** — a test never observed failing is a comment.

- [x] Method-level TESTS edges (ADR-0021), 2026-08-09: `_derive_test_edges`
      checked the import against the *target symbol*, and **a method is never
      imported** — you import the class and call the method. So no method
      anywhere could carry a `TESTS` edge, which in Python/TS is most of the
      code. Three surfaces were wrong; only the first was on the backlog:
      `related_tests(method)` returned nothing, **`test_gaps` reported every
      changed method as untested** (verified by running the real engine:
      `PaymentService.capture` was listed as a gap while a test calls it
      directly), and `CALLED_NOT_IMPORTED` claimed the call "may resolve to a
      different symbol" when `_Adjacency.build` drops everything not `RESOLVED`,
      so every edge behind that reason is resolved by construction.

      The stored `CALLS test → PaymentService.capture` edge was `static_resolved`
      — **above** `high_confidence_heuristic` on the ladder. CodeAtlas was
      accepting the weaker signal as coverage and rejecting the stronger one.

      Fixed at extraction time (`static_resolved`), `_QUALIFYING_COVERAGE`
      widened to `{static_resolved, high_confidence_heuristic}`, reason text
      corrected. `RESOLVER_VERSION` 1.2.0 → **1.3.0**; existing snapshots are
      stale until re-indexed and `change_analysis.py` already refuses a stale
      resolver rather than mixing derivations. `exact_symbol_resolution`
      0.7436 → 0.7692, `relation_path_correctness` 0.2083 → 0.2917,
      `abstention_correctness` 0.8500 → 0.8750. Gate exit 0, 2097 passed.

      **The ADR-0016 invariant corpus caught a real over-reach in my first
      implementation**, and this is the thing to remember. Accepting any owner
      included *modules*, so `import orders` + `orders.Order()` qualified — one
      module import vouching for every symbol inside it, which would have closed
      the two gaps ADR-0016 exists to keep open. The corpus failed with
      "i001: Order was expected to remain a gap but was not reported". The rule
      now requires the owner to be a **CLASS** and the target a **METHOD**. The
      tracked invariant artifact is byte-for-byte unchanged, which is the
      evidence that coverage widened without the invariant weakening.

      That corpus was written four weeks earlier, fired on the first change that
      threatened it, and was right against an author who believed the change was
      safe. It earned its keep.

- [x] Phase 7 harness audit; corpus line endings (ADR-0022), 2026-08-09: the
      audit found `changed_symbol_precision = 0.2000` was **not an engine
      defect and not a corpus defect**. One variant file
      (`semantic_cases/variants/.../pricing.py`) held **CRLF** in the working
      tree while every other file in all three corpora is LF, so all 42 lines
      differed and all five functions in it reported as changed against a case
      declaring one. The engine was right — the change engine hashes bytes.

      `.gitattributes` already prevents this (`* text=auto eol=lf`, with a
      comment naming this exact failure) and the committed object *is* LF. The
      file had been rewritten locally and never restored.
      `rm` + `git checkout --` gave LF and precision **1.0000**, matching the
      declared expectation exactly. No engine code and no expectation changed.

      **The serious part: `baseline-phase-7` encoded that drift.** It is gated
      byte-for-byte by `check_phase7.ps1`, and `--check` on a correctly
      checked-out tree exits **5**. The tracked artifact did not reproduce on a
      fresh clone. Regenerated; `changed_symbol_precision` now drops out of
      `unmet_targets` in both columns, so **Phase 7 has three unmet targets, not
      four**.

      **Git cannot show you this drift**, two ways: when the working file's stat
      still matches the index, git skips the content check and reports a
      *completely clean tree* (the state this repo was in all session); once the
      stat changes it reports ` M` but `git diff` is **empty**, because
      `text=auto` normalises CRLF away when comparing. Guarded now by
      `test_every_corpus_file_has_lf_endings_in_the_working_tree`, which reads
      bytes and is mutation-checked.

      Query-side audit results, so they are not re-derived: `exact_symbol_resolution`
      0.2857 is a **ranking** result, not retrieval — the expected symbol is in
      the top 10 for **11 of 14 cases** (`symbol_recall_at_10` 0.7857). Several
      expected answers are document headings rather than code symbols, and
      `_unmet_targets` applies **one dataset-agnostic target table** to both
      corpora, so a 0.98 written for `EXACT_SYMBOL` lookup is applied to
      conceptual search. One real weakness: s003 "When does a customer avoid
      paying for delivery?" returns `OrderRepository.for_customer`, matched on
      the word "customer" — the same family as the P7-06 stopword defect.
      **`predict_conceptual` has none of the defects found in
      `predict_exact_symbols`** — no fixture gate, verbatim questions by design,
      correct projection for conceptual intent.

      Process note: `check_phase7.ps1` was **not run during the five earlier
      merges this session**, and it gates `baseline-phase-7`. It happened to
      pass, because the corpora are disjoint — luck, not diligence. Run it when
      touching anything `predict_conceptual` reaches.

- [x] Target profiles and metric scope (ADR-0023), 2026-08-09: the ruling that
      had been open across four sessions. `_unmet_targets` applied **one target
      table to every dataset**, so the 14-case conceptual corpus was held to a
      0.98 top-1 rule written for exact symbol lookup, and two of the resulting
      "unmet targets" were carried here as engine defects for months.

      Three user rulings, all implemented:
      1. **`exact_symbol_resolution` is scoped to symbol-shaped intents**
         (`EXACT_SYMBOL` + graph) and a new **`lexical_resolution`** gates
         `CONFIG_LOOKUP`/`DOCUMENT_LOOKUP`. The decomposition that justified it:
         `EXACT_SYMBOL` 15/15 and every graph intent 12/12 are **perfect**; the
         0.7692 aggregate came entirely from lexical lookups, where "did the
         right *symbol* rank first" asks something other than what was posed.
      2. **A dataset declares a `target_profile`** (`retrieval` default,
         `conceptual` for `semantic_cases`). The conceptual profile drops top-1
         and gates `symbol_recall_at_10`.
      3. **The evidence gate reads `containing_evidence_rate`**, threshold
         **still 1.0** — "all evidence must be valid" is unchanged, only what
         *valid* means is corrected (ADR-0003). Inventing a lower number would
         have been the quiet relaxation.

      Main corpus: `exact_symbol_resolution` **1.0000 (met)**,
      `lexical_resolution` **0.3000 (new gate, fails)**. Phase 7: four unmet
      targets → **two** (`primary_evidence_recall_at_10` 0.6667,
      `symbol_recall_at_10` 0.7857); `exact_symbol_resolution` reports **not
      applicable** rather than scoring zero. Gate green: 2105 passed.

      **The unmet count fell and that is not the point — no engine behaviour
      changed here.** Scoping a metric until it reads 1.0000 is how a number
      gets gamed, which is exactly why the lexical gate is not optional: it is
      the condition that keeps the scoping honest, and it fails today.

      The intent vocabulary now lives once, in `dataset.py`, with
      `engine_adapter` importing it and a test asserting
      `GRAPH_INTENTS ⊆ SYMBOL_INTENTS` — two definitions of one set is how the
      `--format pr` defect happened.

      `symbol_recall_at_10` was added to the Phase 7 uplift table because
      `exact_symbol_resolution` now reads "not applicable" there. It carries the
      same signal, **0.7143 → 0.7857 (+0.0714)** — the identical magnitude the
      old row reported — so the Phase 7 admission record is unchanged in
      substance.

      One test was changed, deliberately and not to make a build pass: the
      rerank A/B asserted every delta equalled `0.0`; a not-applicable metric
      reports `None`, which is also "not moved". It now rejects any non-zero
      delta **and** requires at least one metric to have been compared, so it
      cannot pass vacuously.

      Provisional: `lexical_resolution >= 0.90` is the one threshold not derived
      from an existing decision — chosen to match the recall family, open to
      revision. `containing_evidence_rate >= 1.0` may need to be argued down
      with evidence rather than convenience.

- [x] Unmeasured is not wrong (ADR-0024), 2026-08-09: step one of the lexical
      retrieval work. `engine_adapter`'s docstring has promised since Phase 1
      that **"not implemented" and "answered wrongly" are different facts and
      the baseline must not blur them**. The adapter kept that promise; the
      **scorer broke it** — a case the adapter declined to run scored
      `exact_symbol_resolved=False` and landed in the denominator as a wrong
      answer.

      ADR-0017 fixed half of this by widening `SUPPORTED_FIXTURES`, but
      `malicious_unsupported` is excluded **on purpose** (prompt-injection
      text), and its cases kept scoring as misses. So `lexical_resolution` had
      two of ten cases that could never pass: **maximum 0.80 against the 0.90
      gate I set hours earlier in ADR-0023.** No engine could clear it. The
      lesson is not the number — it is that a metric containing structurally
      unpassable cases cannot be reasoned about at all.

      `QueryPrediction.measured` (default `True`, so old artifacts parse
      unchanged) now carries the distinction, and unmeasured cases leave every
      accuracy aggregate. **`abstention_correctness` too, which reduces credit**:
      an unmeasured case abstained because the adapter declined to run it, not
      because the engine judged evidence insufficient — q040 had been scoring as
      a correct abstention and no longer does. A test pins the other side: an
      engine abstention is **still** a miss, or the metric could be improved by
      refusing to answer.

      `lexical_resolution` 0.3000 → **0.3750** (3/8); `symbol_recall_at_10`
      0.6923 → 0.7714; MRR 0.7692 → 0.8571; `abstention_correctness`
      0.8750 → 0.9714; `exact_symbol_resolution` unchanged at 1.0000 (all its
      cases were measured). **No engine behaviour changed** — numbers rose
      because cases the engine was never shown stopped counting against it.

      Done **first, deliberately**: the actual lexical defect is that nested
      config keys (`service.port`, `features.audit`) are computed by
      `_nested_paths` then flattened into a display string, so they never become
      addressable symbols and a config lookup can only return the parent key.
      Fixing that moves `lexical_resolution` again, and it must be measured
      against an honest denominator or the two causes are inseparable.

      Open: with **eight** scorable cases every value is a multiple of 0.125, so
      a 0.90 gate means "8 of 8" and nothing else. The threshold needs setting
      to a value the metric can take — after the nested-key work, from real
      per-case evidence rather than guessed a second time.

- [x] Nested configuration keys are symbols (ADR-0025), 2026-08-09: step two of
      the lexical work, and **the actual defect**. `_nested_paths` has always
      computed `service.port`, `features.audit`, `scripts.test`, `server.host`;
      `_config_symbols` joined them into the `container` display string and
      emitted a symbol for the **top-level key only**. So a nested key was
      searchable *prose* but not an addressable *symbol* — nothing could cite
      it, and search returned the parent because the parent was all there was.

      Third instance this week of the same shape: **data already computed, then
      not surfaced as the thing a caller needs** (ADR-0020 discarded
      `relation_paths`, ADR-0019 labelled evidence with the wrong end).

      Each leaf now cites **its own line**, found by matching the leaf name
      inside its parent's block. That is a text match, not a parse position —
      JSON/TOML paths come from a parsed structure with no line info — so a leaf
      whose line cannot be found keeps its **parent's range** rather than a
      guessed one, and sibling leaves skip already-claimed lines so
      `service.port` and `admin.port` cannot collapse onto one citation. Both
      pinned by tests. `PARSER_BUNDLE_VERSION` 1.2.1 → **1.3.0**; snapshots need
      re-indexing.

      `lexical_resolution` 0.3750 → **0.6250**, `symbol_recall_at_10`
      0.7714 → 0.8857, MRR 0.8571 → 0.9429. **Evidence rates fell** —
      exact/valid 0.6316 → 0.5647, containing 0.6974 → 0.6588 — because more
      symbols means more evidence items whose spans do not match gold ranges
      exactly (the ADR-0018 trade). Quote them together or not at all.

      **It did not reach the predicted 0.8750, and that prediction was wrong for
      an instructive reason: there are two defects, not one.** q021/q022 still
      fail on **ranking** — an exact qualified-name match loses to its own
      parent when the parent's block is short enough to score higher on term
      density (`'features.audit'` → `['features', 'features.audit', ...]`).
      Verified directly against the index: the symbols exist. Deliberately not
      fixed here, and it touches a documented invariant — `search_text`'s
      docstring records that the relaxed-fallback design was chosen so "a query
      that finds results today finds exactly the same results", which promoting
      exact matches breaks on purpose.

      ~~Watch: index volume unmeasured beyond the fixtures.~~ **Measured
      2026-08-09:** on this repository (11,420 chunks) nested config keys are
      **689 chunks = 6.03% of the index**; `config_key` chunks went ~1.5% →
      7.5%, a 5x rise *within* that category for ~6% overall growth. Per file
      the multiplier is larger — `apps/web/package.json` 8 symbols → 50, and
      this project's three config files 14 → 118 (8.4x). The bound holds: 200
      nested keys yield 41 symbols, not 201. **Modest; no further capping
      needed.** Boundary of that claim: this is a code-heavy project where
      symbols and documents are 87% of chunks — a config-heavy repository
      (Kubernetes, Helm) would invert the proportions and is unmeasured. Two
      chunking tests were updated (strict equality kept, nested entries and leaf
      lines added) because this record deliberately makes their "and nothing
      else" assertion false.

- [x] Exact name match outranks a lexical one (ADR-0026), 2026-08-09: the
      second defect ADR-0025 exposed, and the reason its 0.8750 prediction fell
      short. `search_chunks` ordered by `bm25(chunk_search)` alone, and BM25
      scores by term density — so the **two-line** `features:` block out-scored
      the `features.audit` chunk, while the **three-line** `service:` block
      diluted and lost to its leaf. **Whether a caller got the key they asked
      for or its parent depended on how many other lines the parent happened to
      contain.**

      `_exact_first` promotes a chunk whose `qualified_name` *is* the query, in
      `LexicalSearch` rather than the SQL — ranking policy belongs in retrieval,
      FTS syntax stays in the store. Two bounds written into the code, not left
      implicit: it reorders **only within the window the query already
      returned** (`limit` is applied by SQL, so an exact match below the cutoff
      never arrives — this is *not* a guarantee that exact always wins), and it
      is a **stable partition**, so a query with no exact match returns exactly
      as before. A test pins the latter; without it this would be a general
      retrieval change wearing a bug fix's clothes.

      **It breaks a documented invariant on purpose.** `search_text`'s docstring
      says the relaxed-fallback design was chosen so "a query that finds results
      today finds exactly the same results". Membership is preserved; *order* is
      not. Called out rather than silently amended — that note exists to make a
      future author think before reordering, which is what happened.

      `lexical_resolution` 0.6250 → **0.8750** (7/8), MRR 0.9429 → 0.9714, ndcg
      0.8840 → 0.9051, evidence rates **unchanged** — the correct signature for
      a pure reorder. Across the whole lexical thread: **0.3000 → 0.3750 →
      0.6250 → 0.8750**, one attributable cause per commit.

      **The last failure is not an engine defect.** q019 expects `README.Health`
      while extraction emits bare `Health`; q027/q031 expect a bare `Order flow`
      and pass. The corpus uses **two naming conventions** for document
      sections. Needs a ruling; expectations must not be edited to move a number
      (ADR-0003). The `lexical_resolution` threshold should be set after that
      ruling — on eight cases every value is a multiple of 0.125, so the current
      0.90 means "8 of 8" and can express nothing else.

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
- ~~**`POST /v1/models/test` success branch is untested.**~~ **Closed
  2026-08-07**, for real this time — the claim on 2026-08-06 was premature and
  is corrected in the handoff log.

  Two tests were added and, because the behaviour already existed, both passed
  immediately. That makes them worthless unless they would catch a regression,
  so each was **mutation-checked**: dropping the empty-vector guard fails the
  no-vector test, and flipping the success branch to `ok=False` fails the
  success test. Both pass again with the source restored.

  The item had been carried since the Phase 7 gate on the reasoning that it
  "needs an available provider". It never did — it needed something that
  returns a vector. Waiting for a real provider is what kept it open for a
  week, and once one *was* installed, the naive version of the test would have
  issued a real billable request on every run.
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

Two follow-ups were raised by the ADR-0016 whole-branch review and deliberately
**not** folded into that branch, so they are recorded here rather than lost:

1. ~~**The evaluation corpus cannot see derivation-tiered test edges.**~~
   **CLOSED 2026-08-08** by a separate invariant corpus
   (`tests/evaluation/invariant_cases/` + `scripts/check_invariants.py`,
   gated in `check_phase4.ps1`).

   The original suggestion — "add two change cases to the Phase 4 corpus" —
   turned out to be blocked, and finding out *why* is the reusable lesson.
   `ChangeCase` is a `ContractModel` with `extra="forbid"`, so a case cannot
   carry a gap expectation until the model carries the field; and adding a gap
   metric to the evaluation report would change `baseline-phase-4.json`'s
   shape, breaking the byte-for-byte `--check` that the project owner ruled
   must keep passing. The two constraints together made extending that corpus
   impossible without violating a standing ruling.

   So the fix was a **second surface**, not a bigger first one: a corpus that
   asserts a boolean rather than measuring accuracy, with its own committed
   result artifact. Weakening the invariant now takes two visible acts in one
   diff — editing corpus data and regenerating an artifact. Phase 4's corpus,
   dataset models, runner, report model, and baseline are untouched, proven by
   an empty `git diff --stat` against `main` on those paths.

   Verified by mutation, not by assertion: making `LOW_CONFIDENCE_HEURISTIC`
   qualify in `_test_gaps` makes the checker exit 7 naming `Order` and `total`.

   **Standing rule:** this corpus does not grow into an accuracy corpus. A case
   about how *well* something is detected belongs in the Phase 4 corpus.

2. ~~**`related_tests` is a second surface the invariant was never applied
   to.**~~ **CLOSED 2026-08-08** by `claim_text()` in
   `application/graph_queries.py`, guarded by `tests/unit/test_claim_text.py`.

   The contract was never wrong: the `Claim` already carried the edge's
   `derivation` and `confidence`. The defect was entirely in the prose — a
   fixture-mediated edge read "test_total tests Order" while citing the fixture
   parameter line, which never names `Order`. A reader was told a fact and
   shown evidence that could not support it.

   Decided: keep the edge, change the wording. Filtering weak edges out would
   return "no tests recorded" for a symbol several tests do reach, and the
   caller could not tell "none exist" from "none strong enough" — silence worse
   than a hedge. A mediated edge now reads "may exercise X indirectly, through
   a fixture".

   **Detection is by `module_hint`, not `derivation`** — a derivation is a
   strength and cannot name the path an edge came from, and any future edge
   assigned the same strength for an unrelated reason would be swept in.

   The weak citation was accepted rather than fixed: pointing at the fixture
   definition needs the resolver to store the intermediate hop, which bumps
   `RESOLVER_VERSION` and makes every snapshot stale until re-indexed.

   All six call sites route through the one application service, so a single
   change reached REST, CLI, MCP, conversations, and evaluation — the opposite
   of the `--format pr` defect, where each adapter held its own copy of a guard.

   **Both tracked baselines still reproduce byte-for-byte.** That is a
   limitation, not a reassurance: the corpus has no fixture- or helper-mediated
   case, so it cannot see this fix either. Same blind spot the invariant corpus
   (`tests/evaluation/invariant_cases/`) was built to work around.

   ORIGINAL NOTE: **`related_tests` is a second surface the invariant was never applied to.**
   `application/graph_queries.py` queries `kinds=(RelationKind.TESTS,)` with no
   derivation filter, so it now returns fixture- and helper-mediated candidates
   beside genuine coverage and renders each as flat prose. The claim does carry
   `derivation` and `confidence` — the designated mechanism — so this is not a
   correctness bug. But the cited line for a fixture-mediated edge is the
   *fixture parameter*, which never names the target, so the prose reads like a
   fact while its evidence line does not show the relationship. ADR-0016's
   consequences section discusses `impact` only and never mentions this surface.
   Worth an explicit decision rather than an accident.

No other assigned work. Candidates, in the order they'd most likely be picked up:

1. **Investigate the Phase 7 semantic baseline — four unmet targets, not one.**
   Verified 2026-08-08 against `docs/evaluation/baseline-phase-7.json` and the
   target table in `evaluation/runner.py:609-637`:

   | Metric | Actual | Target |
   | --- | ---: | ---: |
   | `exact_symbol_resolution` | 0.2857 | 0.98 |
   | `valid_evidence_rate` | 0.0563 | 1.00 |
   | ~~`changed_symbol_precision`~~ **met** | ~~0.2000~~ **1.0000** | 0.95 |
   | `primary_evidence_recall_at_10` | 0.6667 | 0.90 |

   ~~**Start with `exact_symbol_resolution`, not Recall@10.**~~ **Partly
   resolved 2026-08-08 — see ADR-0017, and read the two corpora separately.**

   The table above is the **semantic corpus** (`tests/evaluation/semantic_cases`,
   14 cases, all `CONCEPTUAL`, run through `predict_conceptual`).
   `predict_conceptual` has **no fixture gate**, so ADR-0017 does not move these
   numbers. But on that corpus `exact_symbol_resolution` is top-1 precision on
   14 deliberately fuzzy natural-language questions, asked verbatim by design,
   scored against a 0.98 target built for exact symbol lookup. That is a
   **target problem before an engine problem** — the same conclusion already
   reached for `valid_evidence_rate` below, and it needs the same owner ruling.

   On the **main corpus** (`tests/evaluation/cases`, 40 cases,
   `predict_exact_symbols`) the same metric was 0.3846 and is now 0.6154,
   because the fixture gate had been discarding 16 of 39 cases. Still short of
   0.98.

   ~~**The real engine gap the harness was hiding: TS/JS graph intents
   abstain.**~~ **Wrong — corrected 2026-08-08 by ADR-0018.** Not TS/JS-specific
   (three of six affected cases are Python: q005, q007, q010) and not a
   capability gap (the engine answers all of them when asked about the right
   subject). Main-corpus `exact_symbol_resolution` is now **0.6667**.

   Two real findings survive from that investigation, both deferred on purpose
   so a measurement correction stays attributable:

   - ~~**Module-scoped graph queries rank the module's own symbol first.**~~
     **Split and half-closed 2026-08-08 by ADR-0019.** The framing was
     imprecise. The `EXPORTS` half was a real engine defect (evidence labelled
     with the module while citing the exported symbol's own definition) and is
     fixed. The `DEPENDENCIES` half is **not** an engine issue: for an outgoing
     query the evidence correctly cites the reference site inside the subject,
     and the answer lives in the *claim*. ~~What is wrong there is the
     evaluation harness projecting `ranked_symbols` from evidence labels.~~
     **CLOSED 2026-08-08 by ADR-0020** — and it was a *product* gap, not a
     harness one: there was nowhere in the response to read an outbound answer
     from, because `Claim` has no structured subject/object and
     `relation_paths` was populated only for `trace`. q010 and q015 now pass.
   - ~~**`related_tests` does not resolve a method subject to its class-level
     edge.**~~ **CLOSED 2026-08-09 by ADR-0021**, and it was far larger than
     `related_tests`: no method anywhere could carry a `TESTS` edge, so
     `test_gaps` reported every changed method as untested. The edge was not
     moved — import-and-call is applied one level down (imported class, resolved
     call to its method).

   **Read every number here against the corpus size: 14 query cases and 1 change
   case.** `changed_symbol_precision = 0.20` is computed from that single change
   case — one prediction in five correct, once. It is an anecdote with a decimal
   point. The semantic layer's whole Recall@10 gain (+0.0667) is about one
   case's worth of movement, and semantics *lost* evidence precision to buy it
   (exact evidence rate 0.0752 → 0.0563, containing 0.1278 → 0.1080).

   So the first question is not "why is metric X low" but **whether this corpus
   can distinguish a real fix from one tuned to three specific queries.** Same
   failure mode as the two ADR-0016 corpus gaps closed on 2026-08-08: a metric
   that cannot see what it claims to measure.

   **`valid_evidence_rate` resolved 2026-08-08 — do not read it as "94% of
   evidence is invalid".** It *equals* `exact_evidence_rate` by definition
   (ADR-0003, `runner.py:164-167`), retained under the old name so historical
   numbers keep their meaning. Confirmed in the artifact: both are exactly
   0.0563 in the semantic column. So it measures **exact span match**, and
   0.0563 means 5.6% of evidence items land on precisely the expected span. The
   looser `containing_evidence_rate` — evidence that *contains* the expected
   span — is 0.1080.

   That reframes it as a **target problem before an engine problem**: the unmet
   rule demands `valid_evidence_rate >= 1.0`, i.e. every evidence item matching
   its expected span exactly. Whether that is achievable, or whether the gate
   should be reading `containing_evidence_rate`, is a decision for the project
   owner — ADR-0003 requires any claim to name which of the three rates it used,
   and the gate currently names the strictest. Settle that before treating
   0.0563 as an engine defect.

   The stopword precedent still stands and is still the best lead on *lexical*
   headroom: that one fix was worth +0.53 recall while the entire semantic layer
   above it was worth +0.07. But the per-case results needed to act on it are
   not in the artifact — it stores aggregates only, so diagnosing requires an
   evaluation run with per-case output.

2. **Decide on code signing** — a purchasing decision, not an engineering one.
   Until then the packaged executable is unsigned and SmartScreen warns.
3. **Consider deleting the five stale local branches** whose content is in
   `main` but which point at pre-rewrite commit objects, so `git branch`
   stops implying unmerged work. `backup-before-rewrite` can go with them once
   the rewrite is trusted.

Closed since this list was written:

- ~~Close the untested `POST /v1/models/test` success branch.~~ **Already
  delivered 2026-08-07**, and this list was stale for a day. The test is
  `test_a_working_provider_is_reported_as_ok`
  (`tests/contract/test_settings_api.py:241`), and it avoided the billing trap
  exactly as the note warned: it stubs `ProviderFactory.build` rather than
  calling a provider. `docs/plans/PLAN.md` recorded it as done the same day.

  The lesson is about this file, not that endpoint. PLAN.md is the authority and
  memory.md is a summary; when they disagree the summary is the bug (CLAUDE.md).
  A candidate list that is not reconciled against the handoff log will hand
  someone finished work — which is what happened here.

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
