# Memory — session log

Append-only working memory for coding agents. Update this at the end of every
task. **This is a convenience log, not evidence.** The authoritative task status
and handoff record is `docs/plans/PLAN.md`; where they differ, that file wins.

Last updated: 2026-08-20

## Current Phase

**None, and the project is closed out.** Phases 0–7 are all `complete` with
user-approved gates, the Section 20 development order is finished, and the
2026-08-10 closeout gave the open tail a terminal state. A new phase requires
an explicit user decision.

**The open-item list lives in one place: the Deferred Register in
`docs/plans/PLAN.md`.** Do not restate it here or in `phases.md` — two copies
of a status list is how they drift, which is the `--format pr` and
`_SEVERITY_ORDER` lesson applied to documentation.

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

- [x] Packaged build refreshed and both repositories deleted (2026-08-09):
      `build_package.ps1 -SemanticLocal` took the artifact from parser 1.2.1 /
      resolver **1.1.0** to **1.3.0 / 1.3.0**, closing the open item carried
      since ADR-0026. `-SemanticLocal` was chosen by inspecting the outgoing
      artifact — it carried `torch` and `lancedb`, so omitting the flag would
      have silently dropped the semantic layer and still looked like a
      successful rebuild.

      **Verified behaviourally, because exit 0 only proves PyInstaller ran.**
      The `python_app` fixture was indexed *with the packaged exe*: the snapshot
      came back stamped 1.3.0/1.3.0, and
      `tests PaymentService.capture` returned
      `test_capture_uses_idempotency_store` at `tests/test_service.py:5`
      `[static_resolved]` — ADR-0021 running inside the artifact, where the
      outgoing package returned nothing. That fixture was picked because
      ADR-0021's handoff already records it as the case verified against the
      real engine.

      **`dist/` is gitignored, so this closed nothing for anyone else.** No
      tracked file changed; a fresh clone still has no package. Treating this as
      repository state would be wrong.

      Both registered repositories (`projects/Prelegal`,
      `projects/curser_kanban`) were then deleted as residue at the user's
      instruction — backup first, then `repo remove --cascade` twice, then an
      audit showing zero rows everywhere with integrity and foreign-key checks
      clean. `--cascade` was confirmed with the user first because the two
      carried **22 conversations and 70 messages**: the index was regenerable,
      the chat history was the one thing here a re-index could not rebuild.

      **A planned re-index was investigated and abandoned** — see Known Issues
      for the reason, which is the useful part of this entry.

- [x] Evidence recall measured by containment (ADR-0027), 2026-08-09: the task
      was "fix the s003 recall gap" and **the premise was wrong** — s003 already
      scores evidence recall 1.0 and contributes nothing to Recall@10. ADR-0022
      recorded s003 as a *ranking* weakness (finding 3) and Recall@10 as a
      separate missed target; a later summary welded them together.

      Investigating per-case found the real distribution.
      `primary_evidence_recall_at_10` compares `snapshot:path:start:end` for
      **exact equality**, so four of Phase 7's five misses return the right
      evidence and score zero: s001 and s012 at **rank 1**, s008 at rank 2,
      s013 at rank 4. s012 expects `runbook.md:3-6` and gets `3-7`. Only
      **s007** is a genuine retrieval miss.

      ADR-0003 had already ruled containment the right granularity and written
      `_contains`; ADR-0023 moved the evidence *gate* to it and left the recall
      metric behind — the same one-surface-missed shape as ADR-0017's
      `SUPPORTED_FIXTURES`. Fixed by adding
      `containing_evidence_recall_at_10` and gating on it at the unchanged 0.90,
      **retaining** the exact-match number so none of six baselines changes
      meaning (ADR-0003's own precedent with `valid_evidence_rate`).

      Phase 7: 0.6000 → **0.8667** deterministic, 0.6667 → **0.9333** semantic.
      **Condition 7 passes**, and the deterministic side does not — the semantic
      layer carries the last 0.0667. Phase 3 (0.4068) and Phase 4 (0.8136) rise
      and still miss, which is the signature of a corrected definition rather
      than a loosened one.

      **No engine behaviour changed and this must never be cited as uplift.**
      Nothing outside `evaluation/` was touched.

      Two things worth remembering. **Running `check_phase7.ps1` found its
      rerank artifact stale for three ADRs** — still carrying the CRLF-era
      `changed_symbol_precision` 0.2 that ADR-0022 fixed in its sibling, plus
      ADR-0023's shape changes. Proven pre-existing by regenerating on a
      stashed tree, and committed separately so it stayed attributable;
      `baseline-phase-7` reproduced fine, so the staleness was specific. That is
      ADR-0022's finding 5 recurring: **`check_phase7` gates more than
      `check_phase4` and is the one that goes unrun.** And the "clipping"
      guard test is what keeps containment from drifting into overlap, which
      would reward a citation that omits part of the answer.

- [x] Both retrieval channels fused by rank (ADR-0028), 2026-08-09: the task was
      "fix s007" and **retrieval was not what failed**. The semantic channel
      already ranked `OrderService.cancel` **8th**; fusion put it 16th, because
      `augment` appended candidates after every deterministic item and dropped
      any the deterministic half had already cited. A chunk both channels found
      kept its lexical position and gained nothing — the code's own comment said
      "the two channels finding the same chunk is the point of fusing them" and
      then discarded exactly that.

      **Two separately-recorded engine defects were one fusion defect.** s003's
      ranking weakness — ADR-0022's "one genuine engine weakness", blamed on
      lexical matching of the word "customer" — was the same cause: semantic
      ranked `shipping_for` **1st**, fusion buried it at 5th.

      Fixed with reciprocal-rank fusion (`application/rank_fusion.py`), ranks
      only and never scores, because a BM25 score and a cosine distance are not
      comparable quantities. Recall@10 0.9333 → **1.0000**, MRR 0.4429 →
      **0.6875**, nDCG 0.5271 → **0.7292**, symbol recall 0.7857 → 0.8571, and
      **the evidence rates did not move** — the signature of a pure reorder.

      Three things worth remembering. **A documented invariant was overturned on
      purpose**: a test asserted the deterministic prefix survived byte-for-byte
      because reordering it would be the semantic layer "deciding relevance,
      which is the authority it does not have". Order is not authority, and
      §4.3 forbids promoting a *derivation*, which fusion never touches — the
      test now asserts that instead, and its docstring records that it used to
      say the opposite. **My first implementation built the channel order before
      reranking**, so fusion re-sorted the reranked items back and threw the
      reranker's whole output away — the same "computed, then not surfaced"
      shape as ADR-0019/0020/0025, caught by a test. And **RRF rewards coarse
      chunks**: a whole-file chunk matches most queries, appears in both
      channels, and gets credit for being unspecific. No granularity penalty was
      added — that is a tuning knob needing its own evidence — but it will
      resurface.

- [x] A memberless container carries its body (ADR-0029), 2026-08-10: the
      `OrderStatus` question ADR-0028 left open. **Extraction and chunking were
      both correct** — the symbol exists as a `CLASS` at 6–12 and has its own
      chunk at those lines. The chunk's *text* was the defect, in full:
      `SYMBOL: OrderStatus / TYPE: CLASS / LINES: 6-12 / CODE: class
      OrderStatus(Enum):`. `DRAFT`, `PLACED`, `SHIPPED`, `CANCELLED` and the
      docstring were **absent from the index**, so no ranking change could ever
      have retrieved it — which is why ADR-0028 moved every other case and not
      this one.

      A class chunk is an outline naming its members instead of repeating their
      bodies, which is right because each member is chunked separately. An enum
      has no member *symbols* — its values are assignments — so the outline
      reduced it to a declaration line. Rule now: **a container with no members
      is a leaf, and leaves carry their code.** One condition; the existing leaf
      path handles size.

      `CHUNKER_VERSION` **1.0.0 → 1.1.0**, its first move since Phase 2, so
      every existing snapshot must be re-indexed.

      Semantic side: `symbol_recall_at_10` 0.8571 → **0.9286**, evidence
      Recall@10 0.7333 → 0.8000, nDCG 0.7292 → 0.7530. **Phase 7's conceptual
      corpus now reports `targets_met: true` with no unmet targets** while the
      deterministic side still misses two — the gap between the columns is what
      makes it uplift rather than redefinition.

      **Three cautions on that claim.** It took three changes and only two
      changed the engine: ADR-0027 corrected the metric (**no engine change**),
      ADR-0028 fixed fusion, ADR-0029 fixed indexing. Citing "Phase 7 meets
      every target" without ADR-0027 overstates the engine. **The deterministic
      side got slightly worse** — MRR 0.3714 → 0.3619, nDCG 0.4557 → 0.4476 —
      because enum bodies match more queries; that cost is real and unoffset.
      And **`baseline-phase-3`/`-4` are byte-for-byte unchanged**, because the
      retrieval fixtures contain no enum: the main accuracy corpus is
      structurally blind to this rule, the same shape ADR-0016 recorded.

      Rejected: wiring the docstring instead. `SymbolRecord` has no docstring
      field and all four `build_symbol_retrieval_text` call sites pass
      `docstring=None`, so that `DOCSTRING:` line is unreachable today and
      supplying it means parser, domain, schema, and a
      `PARSER_BUNDLE_VERSION` bump. Carrying the body picks the docstring up
      anyway. The dead parameter is left as the right seam for
      member-carrying containers later.

- [x] s001 investigated and **deliberately not fixed** (ADR-0030), 2026-08-10:
      the last conceptual miss is a granularity disagreement, not a defect. The
      relaxed query is `"stop" OR "two" OR "shoppers" OR "buying" OR "last" OR
      "one" OR "something"`; the **module** chunk matches on `two` because its
      docstring is *"Keeping two customers from being sold the same unit"*,
      which paraphrases the question, while `InventoryLedger.reserve` matches
      **nothing** — its docstring talks about holding units and negative
      reservations. Both channels rank the module first and are right to. The
      corpus declares the method that implements the concept.

      **The metric tension is the part to remember.**
      `containing_evidence_recall_at_10` is already satisfied **at rank 1**,
      because the module chunk `1-36` contains the expected `20-28`;
      `symbol_recall_at_10` misses because the method is 12th by name. The
      obvious lever — ADR-0028's untuned coarse-chunk penalty — would demote the
      very chunk providing that rank-1 containment hit. **Fixing the symbol
      number risks the evidence number**, the ADR-0018/0025 trade appearing in
      ranking policy. It needs corpus-wide measurement, not one case.

      Nothing fails: `symbol_recall_at_10` 0.9286 against 0.90, Phase 7
      `targets_met: true`. Open ruling left behind, same shape as q019: **when a
      concept is documented at module level, does the module satisfy a
      conceptual question?**

- [x] Document sections are named by their bare heading (ADR-0031), 2026-08-10:
      the q019 ruling, open since ADR-0024. The corpus used **two conventions** —
      q019 declared `README.Health` while q027/q031 declared bare headings, and
      extraction emits bare headings everywhere (`Sample Service`, `Health`,
      `Order flow`) with no file-stem qualification anywhere in the engine.

      **`expected_symbols[0]` is the query the harness issues**, not just the
      string it compares against (`_query_term`). So q019 was asking the engine
      for `README.Health` — a symbol nothing can produce — and the engine's
      correct abstention was scored as a wrong one on a case declaring
      `expected_abstention: false`. The corpus was posing an unanswerable
      question, the same shape as ADR-0018 and ADR-0024.

      One line: `lexical_resolution` 0.8750 → **1.0000** (8/8) and out of
      `unmet_targets`, MRR 0.9714 → 1.0000, `abstention_correctness` 0.9714 →
      **1.0000**, nDCG 0.9051 → 0.9337, symbol recall 0.8857 → 0.9143.

      **A one-line corpus edit moving five metrics is precisely the leverage
      ADR-0003 restrains, and the size of the movement is not evidence the
      change was right.** The justification is that the corpus contradicted
      itself, not that the numbers improved. The test to reapply: *if the engine
      emitted `README.Health` and the corpus said `Health`, changing the corpus
      would be gaming.* Here the corpus disagreed with itself and with the only
      convention the engine can produce.

      Cost recorded: **bare headings are ambiguous** — two files with `## Health`
      would both emit `Health`. This corpus has no collision, so the ruling is
      safe here and is *not* a general claim that bare headings are sufficient
      identifiers.

- [x] `lexical_resolution` gated at 1.0 (ADR-0032), 2026-08-10: the threshold
      open since ADR-0023. **The metric scores eight cases** — ten declare a
      lexical intent, `q037`/`q039` sit on `malicious_unsupported` and are
      excluded by ADR-0024 — so it moves in steps of 0.125, and the provisional
      **0.90 already required 8/8 with zero failures tolerated.** 0.90 and 1.0
      selected exactly the same pass/fail set; the gate read as though a miss
      were acceptable and never was.

      Set to 1.0. **Both baselines reproduce byte-for-byte**, which is the
      evidence this is a restatement rather than a tightening. Absolute is also
      the right shape: a config key or document heading either resolves or it
      does not, and Section 19.3's other deterministic targets are already
      absolute.

      Three tests pin the *reasoning*, not the constant. The important one
      asserts that 0.90 and 1.0 still select the same set — **it fails
      deliberately if the corpus grows**, at which point the threshold becomes a
      real decision again instead of a spelling choice. A third rejects any
      invented value between 0.875 and 1.0, so a future 0.95 that looks like a
      considered relaxation and changes nothing is caught here.

      **`exact_symbol_resolution` has the same illusion and is NOT fixed:** 27
      scored cases against 0.98 requires 27/27, tolerating zero failures. It is
      a Section 19.3 target cited in approved phase gates, so correcting it is a
      larger decision, left open on purpose.

- [x] `exact_symbol_resolution` keeps 0.98 (ADR-0033), 2026-08-10: the second
      granularity illusion ADR-0032 recorded. 27 scored cases against 0.98
      requires **27/27 with zero failures tolerated**, because 27 cases produce
      only 1.0000, 0.9630, 0.9259 … and 0.98 falls between the first two.

      **Deliberately NOT restated as 1.0, and the difference from ADR-0032 is
      the point.** `lexical_resolution`'s 0.90 was an internal provisional value
      with no product meaning, so restating it cost nothing. **0.98 is a
      declared release target in `AGENTS.md` §19.3**, cited in approved phase
      gates, and it becomes expressible at ~50 cases (where it tolerates one
      miss). Setting the gate to 1.0 would either make the implementation
      quietly disagree with the contract — what ADR-0013 refused — or force
      amending §19.3 to 100%, which tightens a *product promise* to match an
      artifact of corpus size.

      **The number is not wrong; the corpus is too small to express it.** Being
      stricter than the target is safe — nothing violating 98% can pass. The
      defect was that the strictness was undocumented.

      Documented at the constant, pinned by two tests. One asserts 0.98
      tolerates no failures at 27 cases; the other **fails deliberately once the
      corpus grows enough for 0.98 and 1.0 to separate**, at which point the
      record stops applying. `AGENTS.md` was **not** edited. The real fix —
      growing the symbol corpus toward fifty cases — is now a recorded open item.

- [x] A flow follows routes (ADR-0034), 2026-08-10: the last unexamined metric.
      **`relation_path_correctness` 0.3182 averages four unrelated causes**,
      which is why it never had a gate target — a threshold over four different
      things cannot be reasoned about (the ADR-0023 lesson again).

      Fixed one. Neither q026 nor q032 was a retrieval failure: the expected
      `loadOrder ROUTES_TO get_order` edge is extracted, resolved and **stored**.
      **`trace` never traversed `ROUTES_TO`** — its kinds were CALLS, MAY_CALL,
      IMPORTS — so a flow question could not cross the HTTP boundary that
      relation exists to model, which is the cross-language capability the
      `mixed_app` fixture demonstrates. And an answer with edges but no buildable
      path reported "loadOrder has 2 flow", rendered claims, and returned an
      **empty `relation_paths` with no warning** — the ADR-0020 gap still open
      for unresolved targets, invisible because an empty list looks like "no
      relations".

      0.3182 → **0.5000**; q026/q032 to 1.0000 exactly. **No other metric moved**
      and both Phase 7 artifacts still reproduce byte-for-byte.

      **My first implementation was wrong and a test caught it**: I warned only
      when *no* path could be built, which stopped firing the moment ROUTES_TO
      produced one — leaving two unrepresented edges silent again. It now
      compares counts, because `_paths` withholds all of a path's steps when one
      loses its evidence, so a missing edge cannot be named individually.

      **Not fixed, and recorded so 0.5000 is not read as engine weakness:**
      lexical intents emit no relation paths though their edges are stored
      (q027/q029 — a design decision); module naming `orders` vs `src.orders`
      (q010/q015/q017 — a q019-style ruling); and **precision penalising truth**
      (q005 — the engine emits two correct edges, the corpus declares one, and
      ADR-0020 deliberately mandates emitting every supporting edge, so this
      metric punishes what another record requires). Precision may be the wrong
      instrument, exactly as exact-match was in ADR-0027.

- [x] Relation endpoints use qualified names (ADR-0035), 2026-08-10: the second
      of the four `relation_path_correctness` causes ADR-0034 decomposed. The
      corpus declared `orders EXPORTS Order`, `client IMPORTS total`,
      `service IMPORTS idempotency` — and **none of those bare names is a
      symbol.** The module symbols are `src.orders`, `src.client`,
      `src.payments.service`.

      Unlike q019 the corpus was **internally consistent** (it wrote every
      module bare), which is why this needed its own ruling rather than
      following ADR-0031 automatically. What makes the edit legitimate is
      narrower and checkable: **an expectation must reference an identifier the
      system can produce**, or it is unsatisfiable by construction. The corpus
      already qualifies a method by its class (`PaymentService.capture`);
      qualifying a module by its package is the same rule one level up.

      0.5000 → **0.6364**; q017 to 1.0000, q015 to 0.5000. No other metric moved.

      **q010 is deliberately half-fixed.** Its source was qualified; its target
      was not. `from .idempotency import IdempotencyStore` — the corpus claims
      the edge targets the **module**, the engine records the **class** actually
      bound, and ADR-0021's import-and-call rule depends on the engine's
      reading. That is a modelling question, not a spelling, so q010 still
      scores 0 for one stated reason instead of two.

      **q015 reaching only 0.5 is the lesson**: its expectation now matches and
      precision still halves it, because the engine emits a second *true* edge
      the corpus did not declare. Naming was never going to fix that — it is the
      remaining ADR-0020-versus-precision conflict.

- [x] Expectations must name real symbols (ADR-0036), 2026-08-10: the validator
      ADR-0035 suggested. ADR-0031 and ADR-0035 each found this class **by
      hand**; no metric can catch it, because a metric only scores what it is
      given and an expectation naming a nonexistent thing produces a
      plausible-looking zero. Now three assertions in the suite, run against the
      engine's own `SymbolStore.find_exact`.

      **It immediately found q024 still carrying the pre-ADR-0031 convention** —
      `README.Sample Service` and `README DOCUMENTS service.port`. I had applied
      that ruling by searching for `README.Health` specifically rather than for
      the convention. **No metric would ever have flagged it**: q024's intent is
      `CONCEPTUAL`, unsupported by the adapter, so it is `measured=False` and
      excluded from every aggregate by ADR-0024. Corrected; no baseline moved,
      which is exactly why it survived.

      **The rule is "resolvable", not "equals a qualified_name", and I got that
      wrong first.** `find_exact` has four tiers — qualified, module-qualified,
      short name, case-insensitive — so `orders` legitimately resolves to
      `src.orders`. My first probe reported seven failures, five of them its own
      fault, including splitting relation strings on whitespace which mis-parses
      `Order flow DOCUMENTS get_order`. Using the engine's resolver also keeps
      the rule honest as the resolver evolves.

      Mutation-checked by reintroducing `README.Health` and `orders EXPORTS
      Order`: both fail the validator. Does **not** check that a resolvable name
      is the *right* answer — that is what the metrics are for — nor evidence
      paths, line ranges, or change cases.

- [x] **Project closeout (2026-08-10)** — four substantial items settled and
      every remaining one dispositioned. Plan:
      `docs/superpowers/plans/2026-08-10-project-closeout.md`.

      **ADR-0037, pid-reuse detection.** The only closed item a *user* of the
      packaged build feels: a reassigned pid left a repository permanently
      blocked from reindexing. It had been open since the Phase 6 gate on a
      stated blocker — "no portable source without a new dependency" — that
      was **half right, and the wrong half kept it open twelve days.** There
      is no *portable* source; `GetProcessTimes` sits in `kernel32` beside the
      `OpenProcess` this very module already called through `ctypes`. Scoping
      a requirement to "portable" when the product is Windows-first is the
      reusable mistake here. Mutation-checked both directions.

      **ADR-0038, relation paths scored by recall.** `relation_path_correctness`
      used precision, so every true edge the engine emitted that the corpus did
      not declare lowered it — and **ADR-0020 requires emitting every supporting
      edge.** The measurement punished obedience to an accepted decision.
      ADR-0034 and ADR-0035 each described the symptom (q005, q015 capped at
      0.5) without naming the instrument. This is the **fifth** time an
      investigation found the apparatus at fault rather than the engine
      (0017, 0018, 0024, 0027, 0038). 0.6364 precision → 0.7273 recall,
      precision retained, **deliberately ungated**.

      **ADR-0039, `IMPORTS` targets the bound symbol.** The modelling question
      ADR-0035 deliberately left half-fixed. The decisive fact was not in its
      framing: **q010 contradicted itself**, already naming `IdempotencyStore`
      in `expected_symbols` while its relation string said `idempotency`. That
      moves it from ADR-0035's territory to ADR-0031's — an expectation that
      disagrees with itself, which is a stronger justification. Both relation
      metrics +0.0909, nothing else moved.

      **ADR-0040, ephemeral scope is the server.** Closed as won't-fix *with
      reasoning*, and recorded because "we looked and the current behaviour is
      correct" deserves a record as much as a change does. A CLI command exits
      immediately, so a session database would make every invocation an island
      and `repo add` would be invisible to `index`. Two mutation-checked tests
      now pin both sides, so the ruling is enforced rather than merely written.

      **Pushed and branches cleaned (2026-08-10).** `main` pushed to
      `origin/main` at `8ebdf4c`, 11 commits, no push-protection block this
      time. The five `closeout-*` branches were then deleted with `-d` (the
      safe form, which refuses anything unmerged), and `backup-before-rewrite`
      with `-D`. `git branch` now shows `main` alone.

      **The measured fact that made the backup safe to delete, recorded
      because nobody knew it before and it is not recoverable now.** That
      branch was the last reference to the pre-rewrite objects from the
      2026-08-06 secret-scanner incident — 104 commits, local only, on no
      remote. Comparing its tip against its *counterpart* commit in `main`
      (same message and timestamp, `67c7b84`) rather than against `main`'s
      head — which is four days of features ahead and produces a 144-file
      diff that means nothing — showed the entire rewrite changed **exactly
      one line in one file**: the Slack placeholder in
      `tests/security/test_secret_redaction.py`, split from a single literal
      into a concatenation so the scanner would not match it. Everything else
      was byte-identical with different hashes.

      So the only content the backup uniquely held was the string that caused
      the problem. Tip was `854bea6`, recorded here in case a reflog entry
      outlives this note.

      **The reusable part is the comparison, not the outcome.** "Is this
      branch's content already in main?" is not answered by diffing against
      `main`'s head once `main` has moved on. Find the counterpart commit
      first, or the diff will show progress and read like loss.

      **Two process notes worth keeping.** My own mutation-check script
      reintroduced the **ADR-0022 CRLF hazard** — Python's `open(p,'w')` writes
      CRLF on Windows, and `git` warned on commit. Fixed by ADR-0022's own
      prescription (`rm` + `git checkout --`) and avoided afterwards with
      `newline=''`. And the plan I wrote named a test file that does not exist
      (`test_runner_metrics.py`) with helpers I invented; the executing-plans
      review step caught it before any code was written, which is the argument
      for that step existing.

- [x] **Package rebuilt and release validation run (2026-08-10)** — the same
      day as the closeout, and it found more than it fixed.

      **The rebuild's stated premise was wrong and the rebuild was still
      right.** The request was "rebuild with the new resolver"; `RESOLVER_VERSION`
      had not moved, and probing the *outgoing* artifact showed it already
      matched source on all three versions (parser 1.3.0 / chunker 1.1.0 /
      resolver 1.3.0), read from a database that binary itself wrote. But
      **ADR-0037 carries no version stamp**, so a version comparison says
      "current" while a real product fix is missing. *A version-only staleness
      check cannot see an unversioned fix* — that is the reusable part.

      Verified behaviourally, because exit 0 only proves PyInstaller ran: a
      controlled experiment against the new binary with a guaranteed-live child
      process. Correct start time → run left alone; wrong start time → run
      stranded. **The control mattered as much as the treatment** — without it,
      "failed" could have meant recovery strands everything.

      **`docs/operations/release-validation.md` had never been executed end to
      end, and three of its steps were broken.** In order of nastiness:

      1. **Step 3 returned 0 having measured nothing.** It combined `-SkipWeb`
         with `-Perf`, and `-SkipWeb` *exits the script* (it means "backend
         only, then stop"), never reaching the perf block. A green run that
         measured nothing is worse than a red one.
      2. **`check_phase7.ps1 -Package` could never bind its arguments.**
         PowerShell **array** splatting passes elements *positionally*, and a
         `[switch]` is never positional, so every argument failed to bind.
         Hashtable splatting passes named parameters and works. It regressed
         when the flags became conditional; `check_phase6.ps1` passes the
         switch literally and works. The confusable case, deliberately allowed:
         `Invoke-Checked` array-splats into `uv`, and splatting into a **native
         executable** is correct because no parameter binder is involved.
         Guarded by `tests/unit/test_gate_script_invocations.py`.
      3. **Step 4 told a releaser to run two gates designed to fail.**
         `check_phase1/2.ps1` are marked `# SUPERSEDED` on line 1 and their
         baselines are frozen history ADR-0017 deliberately never regenerated,
         so they always report "baseline artifacts are stale".

      **The lesson is not the three defects. A validation checklist is itself
      untested code** — and this one documented what each step "proves" while
      two steps could not do what they claimed.

      **CRLF in tracked artifacts, twice.** `measure_phase7_perf.py` used
      `write_text` without `newline=""`, which emits CRLF on Windows into a
      *byte-gated* artifact — ADR-0022's exact mode. Fixed at the writer.
      `baseline-phase-6.json` had been sitting CRLF in the working tree with
      **git reporting a clean tree**, found only because the release run wrote a
      second CRLF file and I checked its neighbours. Restored by ADR-0022's own
      remedy (`rm` + `git checkout --`); no tracked evaluation artifact carries
      CRLF now.

      **Two corrections to my own claims.** I reported the package tree as
      "0.98 GB" — that was **GiB**; `package_tree_size_bytes` is 1,052,540,446 =
      **1.05 GB**, so the register's long-standing figure was right and mine was
      mislabelled. And the closeout **missed two Phase 7 artifacts**
      (`baseline-phase-7`, `rerank-phase-7`, which cascades from it) that needed
      ADR-0038's new key, because the closeout's `check_phase7` run did not pass
      `-Semantic` and so skipped the step gating them. I quoted that exact
      lesson — *"`check_phase7` gates more than `check_phase4` and is the one
      that goes unrun"* — in the same handoff where I committed it.

      Perf on the 2026-08-10 semantic artifact: refresh p95 **1.560 s**
      (target 2.0), preflight p95 **3.174 s** (target 10.0), coverage 1.0, tree
      1.05 GB. Both targets met. **Slower than the 2026-07-30 figures**
      (0.975 / 2.298) on a heavily loaded machine; the regression is stated
      rather than explained away, and was not investigated.

- [x] **Release validation completed end to end, step 5 included (2026-08-10)**
      — after the gate fixes above, the whole sequence was re-run and every
      step exited 0: deterministic gate + package, semantic gate + semantic
      package, packaged performance, and the earlier gates (0, 3, 4, 5, 6 —
      1 and 2 excluded as frozen by design).

      Perf on the final artifact, unloaded: refresh p95 **0.799 s**, preflight
      p95 **2.243 s**, cold start 1.060 s, coverage 1.0. These supersede the
      1.560 / 3.174 taken earlier the same day while builds and gates ran
      concurrently. **Both met their targets and the difference is load, not
      the product** — nothing changed between them. The artifact also wrote
      with zero CRLF, which is the first confirmation the
      `measure_phase7_perf.py` fix works in a real run.

      **Step 5 — the manual install round trip — had never been run.** It is
      the one step no test asserts, because asserting it means editing the
      developer's environment. It passed: one PATH entry added (16 → 17),
      `codeatlas` resolving from a fresh shell, `doctor` exit 0 at schema 14,
      `serve --web` answering 200 on both `/v1/repositories` and `/` with the
      `no-store` shell headers and **refused off-loopback on a real socket**,
      then uninstall exit 0.

      **The reusable part is the method, not the result.** The claim being
      checked is ADR-0007 decision 6 — that the installer "reverses exactly"
      its two changes — and that cannot be checked without a baseline captured
      *before* installing. Recording the user PATH first and running
      `Compare-Object` after gave **zero differences**; the app directory was
      gone and `codeatlas.db` untouched. Until 2026-08-10 that decision was an
      assertion rather than a measurement, and an installer nobody has watched
      uninstall is one users are right to distrust.

      Deviations, both harmless and stated rather than hidden: port 8123 so the
      probe could not collide with a running server, and no `--open`, because
      launching a browser proves nothing that probing `/` and `/v1` does not.

- [x] README rewritten as the project's front door (2026-08-19). It now covers
      the problem, the trust contract and derivation ladder, a quick start, a
      full feature catalogue, the indexing/answer/preflight pipelines, the
      architecture and stack, all four surfaces, provider configuration,
      operations, the security model, measured results with their caveats, and
      a documentation map.

      **It opened by finding two documented commands that cannot run.** The
      README's first code block — the one a new user copies — advertised
      `codeatlas graph callers ...` and `codeatlas search text <id> "..."`.
      There is **no `graph` command group** (the graph verbs are top level:
      `callers`, `callees`, `deps`, `exports`, `tests`, `trace`), and `search`
      takes `<repository_id> <query> --kind text|files|symbols`, so the
      documented form consumed the query as the repository id and died with
      `Got unexpected extra argument(s)`. Both were wrong in
      `codeatlas-v2-working-guide.md` too, and both are fixed in both files;
      no code or script ever used the broken form.

      **The lesson is the ADR-0060 lesson on a different surface: a name was
      trusted instead of the thing it named.** `graph callers` reads exactly
      like a Typer sub-app and never was one. Every command, route, tool name,
      exit code and version in the new README was read out of the source or the
      tracked artifacts — `codeatlas --help`, the router prefixes, the MCP
      registry, `baseline-phase-4.json` — rather than copied from prose, which
      is how the two broken commands survived being in the README twice.

      Two figures were corrected against the artifacts while writing: the
      `exact_symbol_resolution` denominator is not restated (the baseline
      records the value, not the case count), and Phase 7's evidence recall is
      given as **0.80 strict / 1.0000 containment** today beside its 0.6667
      gate figure, rather than implying the gate number still stands.

- [x] README corrected against source after the ADR-0065 slices (2026-08-19).
      Documentation only; no source, contract, schema, migration, or corpus
      change. `SCHEMA_VERSION` stays `14`, `contract_version` stays `1.1`.

      **The previous entry's own rule was not applied to the ADR-0065 edits it
      later received, and that is the lesson.** That rewrite read every command,
      route, tool name and version out of the source. The four language slices
      then edited the README four times *by hand*, and every defect found today
      is in text those edits touched — while the parts derived from source were
      still correct. **A file is only as verified as its most recent edit.**

      **The worst of it was a paragraph in three drafting layers welded
      together.** The language-coverage limit simultaneously claimed Java, Go,
      Rust and Scala "yield zero symbols and zero relations", announced they had
      shipped, and then said *"If accepted, it would give those four…"* — the
      conditional from when ADR-0065 was still `proposed`. It also repeated "no
      test edges and no route detection" twice within itself. Any reader would
      have concluded the opposite of the truth about a feature that shipped.

      **Five figures had gone stale, none caught by any gate**, because no test
      reads `README.md`:

      | Claim | Was | Source of truth |
      | --- | --- | --- |
      | Parser bundle / resolver | `1.4.0` / `1.4.0` | **`1.5.0` / `1.5.0`** — `registry.py`, `resolution.py` |
      | MCP tools | 21, `trace_flow` missing | **22** — `build_registry().names` |
      | Corpus fixtures | 7 | **8** — `run_evaluation.py validate` (`java_app`) |
      | Changed-symbol precision | 0.9375 | **0.9464** — `baseline-phase-4.json` |
      | Packaged refresh / preflight p95 | 0.975 s / 2.298 s | **0.799 s / 2.243 s** — `baseline-phase-7-perf.json` |

      **`trace_flow` is the `graph callers` defect again**, one surface over.
      The list was transcribed rather than derived, so the single MCP tool built
      from a loop comprehension — instead of a literal `name=` — was the one
      that fell out. The CLI table documented `trace` correctly the whole time.
      Counted now with `build_registry()`, the way the routes already were.

      **The precision figure is the instructive one.** It rose 0.9375 → 0.9464
      with **no engine change**: WS-1's three added change cases widened the
      denominator. Quoting it as an improvement would be exactly the arithmetic
      -as-progress error this project keeps recording, so the README states the
      cause beside the number.

      **Branch state was deliberately kept out of the README.** ADR-0065 is
      unmerged, but `documentation/rules.md` puts live status in
      `docs/plans/PLAN.md` and keeps policy and product documents free of it —
      the same split that governs `AGENTS.md`. A README that said "unmerged"
      would be wrong the hour it merged.

      Content added, not just corrected: the two-stage reference → relation
      split and the six-step resolution trust order; what is deliberately never
      emitted (dynamic calls, computed members, type inference) and why that is
      measurable rather than invisible; traversal bounds and the refuse-don't
      -clamp rule; `GapReason` and the ADR-0016 invariant; what preflight will
      not tell you (ADR-0043/0044/0045, and the non-atomic working tree); and
      three gate traps — phases 1/2 always fail by design, `-Semantic` gates
      artifacts nothing else reaches, and read the log rather than the exit code.

      A `valid_evidence_rate` note was added because the metric is a documented
      trap: it equals `exact_evidence_rate` by definition (ADR-0003) and reads
      0.6544, which a reader lands on as "35% of evidence is invalid". The table
      row above it is the §4.1 invariant, which is a different statement.

      **CRLF drift in nine tracked Markdown files, and it predates this
      session.** `git ls-files --eol` reports `i/lf w/crlf` against a
      `.gitattributes` declaring `* text=auto eol=lf`. The nine are exactly the
      files the ADR-0065 session edited — several of which this session never
      opened for writing, which is what proves the drift was inherited rather
      than introduced. **This is the ADR-0022 hazard landing where the guard
      does not reach**: `test_every_corpus_file_has_lf_endings_in_the_working_tree`
      is scoped to `tests/evaluation`, so it protects the corpus and not the
      documentation — the same "a rule enforced by a file only the fixtures live
      under does not cover the product" shape ADR-0043 recorded.

      The three files edited here were normalized to LF, each verified by
      `git diff --stat` being identical before and after, so only endings moved.
      Six remain and are listed in the handoff rather than fixed — they
      normalize on commit and corrupt nothing.

      **`SECURITY.md` is untouched GitHub boilerplate** — "5.1.x ✅ / 4.0.x ✅",
      "Tell them where to go" — against a 206-line threat model. Found while
      reading, out of scope for a README task, recorded rather than fixed.

- [x] **Java is measured: the first evaluation cases for a query-backed
      language (P1-1, 2026-08-19).** Corpus **65 -> 69 query cases**;
      `java_app` admitted to `SUPPORTED_FIXTURES`. No `src/` behaviour change
      (the only source edit is the fixture tuple), no version bump, no
      migration. Gate green: **2313 passed, 2 xfailed, exit 0**.

      **Java only, deliberately.** Go, Rust and Scala ship on the same engine
      but each carries an undecided limit, and **a corpus case is the wrong
      instrument for an open ruling** — it would either encode the limit as
      correct or fail for a reason already known and declared. Java has no such
      limit, which is what made it the honest first slice; the same
      Java-first discipline ADR-0065 itself used.

      **q069 was wrong when I wrote it, and the way it was wrong is the
      lesson.** I asked the `DEPENDENCIES` view for a `CALLS` edge. That view
      traverses **`IMPORTS` and `REFERENCES` only**, so a method has neither and
      the engine correctly returned nothing — an expectation **unsatisfiable by
      construction**, the ADR-0031/0035 shape one level up: not a name the
      system cannot produce, but a *kind the view does not traverse*.

      **The ADR-0036 validator passed it.** That validator checks the declared
      symbols resolve through `find_exact`; it cannot know which *view* the case
      invokes. So it is not the guard for this class, and that is now a stated
      limit rather than an assumed cover. Rewritten as a genuine `IMPORTS` case
      against `OrderService`, it passes and pins the ADR-0065 resolver fix.

      **Two metrics broke before it was fixed, and both were the corpus telling
      the truth**: `exact_symbol_resolution` 1.0000 -> 0.9818 (54/55 — still
      clearing 0.98, but the entire margin), and **`relation_path_recall`
      1.0000 -> 0.9630, which is gated at 1.0 absolutely** (ADR-0058). ADR-0058
      wrote that gate saying an ungated threshold the corpus already satisfies
      is decoration until you make it fail. **It failed here, on the first new
      case that declared a relation, and it caught a real authoring error.**

      **Mutation-checked with three mutations, because three of the four cases
      passed on their first run:**

      | Mutation | Caught by |
      | --- | --- |
      | `_DECLARED_MODULE_LANGUAGES` emptied (undoes the ADR-0065 resolver fix) | **q069 only** |
      | Java `qualified_name` drops its owning class | q067, q068, q069 |
      | Java parser unregistered | all four |

      **q068's `CALLS` still resolved under mutation A**, so it does *not* cover
      the resolver fix — it resolves through a different tier. **q069 is the
      only case pinning the thing the ADR-0065 checkpoint existed to verify.**
      Worth knowing before anyone edits it.

      Every restore was **from a file copy, never `git checkout --`** (ADR-0022,
      ADR-0042 both record that command cutting wider than intended).

      **The denominator tripwire fired and that is it working.**
      `test_threshold_granularity` asserts the exact scored count so a
      denominator cannot move unnoticed — 51 -> 55. **The margin is unchanged**:
      one miss scores 0.9818 at 55 against 0.9804 at 51, both clear 0.98; two
      misses fail at both sizes.

      **Baselines moved for arithmetic and for genuinely better evidence.** The
      evidence *rates* rose — containing 0.7500 -> 0.7571, exact 0.6544 ->
      0.6643 — because Java's declared ranges match the engine exactly, which is
      unusual: most corpus growth lowers them (ADR-0018, ADR-0025). Two small
      dips (`ndcg` -0.0013, `symbol_recall_at_10` -0.0016) are the known cost of
      the q055-q058 convention that declares both ends of a relation while
      `ranked_symbols` carries one. **Quote them together or not at all.**

- [x] **Java changed-symbol detection is measured (c029, 2026-08-19).** The
      first *change* case for a query-backed language. Corpus **28 -> 29 change
      cases**. No `src/` change at all, no version bump, no migration.

      **The classifier decides what a Java change case can honestly expect, and
      reading it removed all the guesswork.** `statement_diff` dispatches on
      language — Python via `ast`, TypeScript/JavaScript via tree-sitter — and
      **every other language falls through to `PUBLIC_BEHAVIOR_CHANGED`**. So
      Java body changes are **not classified at statement level**, by
      construction, for all four query-backed languages.

      c029 was designed to *measure that limit rather than avoid it*: it adds a
      `throw` guard clause, which on the Python path would classify as
      `ERROR_BEHAVIOR_CHANGED` and on Java reports `PUBLIC_BEHAVIOR_CHANGED`.
      The limit is declared in the case's own `limitations`, so the corpus
      states it rather than a reader inferring it.

      **Every expectation matched on the first run** — changed symbol, finding
      code, and the impact path `PaymentService.charge -> OrderService.capture`,
      which is the useful part: **Java impact analysis works through the inbound
      `CALLS` edge even though Java has no test edges.** The absence of a test in
      that impact list is the ADR-0065 limit made visible in data.

      **Mutation-checked, and the first mutation taught more than it was meant
      to.** Making the query-backed symbol hash constant, I compared
      `changed_symbols` alone and read **"NOT DETECTED"** — the symbol still
      reported as changed. Comparing what the case *actually declares* showed it
      **is** detected: the finding flips `PUBLIC_BEHAVIOR_CHANGED` ->
      `DEPENDENCY_CHANGED` and the impact path empties.

      Two things follow. **Changed-symbol detection does not rest on the content
      hash alone**, which nobody had written down. And **a mutation check must
      compare everything the case asserts, not the one field you had in mind** —
      a narrower proxy reports a false negative, which is the same shape as
      ADR-0052's "assert against the one claim under test, never the joined
      text", inverted.

      | Mutation | Detected by |
      | --- | --- |
      | query-backed symbol `content_hash` made constant | findings **and** impact paths (not `changed_symbols`) |
      | `reference.call -> CALLS` mapping removed | impact paths |

      **`changed_symbol_precision` 0.9464 -> 0.9483 and that is not an
      improvement.** A perfect case widened the denominator; the engine did not
      change. It is still the sole unmet target and still short of 0.95. Same
      arithmetic-is-not-progress caution as the 0.9400 -> 0.9464 move.

      **The first full gate run FAILED and was right to** — `2 failed, 2311
      passed`, both `test_every_declared_case_is_covered_by_this_table`, in
      `test_findings.py` and `test_impact_cases.py`. **These are not count
      guards**, which is why updating the five `28 -> 29` literals did not
      satisfy them: each asserts the corpus's case set equals the set its own
      *rule table* models, so a change case nothing models is refused outright.

      The earlier lesson recorded "adding one corpus case touched nine hardcoded
      counts across five files -- next time find them in one pass". I did find
      the counts in one pass and **still missed these two, because they are a
      different kind of guard**: coverage, not cardinality. Grepping for the old
      number cannot find a guard that never mentions it. **Look for what
      *models* a case, not only for what counts one.**

      The impact row needed a new `_JAVA_APP` graph whose only expansion is the
      inbound `CALLS` — writing it is what made the no-test-edge limit concrete.
      **Both tables are position-indexed elsewhere in their own files, so a new
      row goes last**; their comments say so and c025-c028 are already ordered
      that way.

- [x] **The Chromium e2e failure reproduced and its mechanism named (P1-4,
      2026-08-19).** Investigation only — **no source, test, corpus, or
      contract change**. The register row's reopening condition was "someone
      reproduces it from a clean state and names the mechanism"; both are done,
      and **the row's own prime suspect was wrong**.

      **The mechanism.** Chromium's renderer *crashes* — `Protocol error
      (Runtime.callFunctionOn): Page crashed` — while rendering the Settings
      **Embedding provider** fieldset for a repository whose policy transmits.
      The trace shows `goto /settings` completing and the `settings-repository`
      assertion **passing** first, so the page mounts and the header renders
      before the renderer dies. It is a crash, not a failed assertion, which is
      the fact the row's framing missed.

      **Four hypotheses ruled out by measurement rather than argument:**

      | Hypothesis | Ruled out by |
      | --- | --- |
      | Residue (the row's prime suspect: a persisted repository policy) | reproduces with `.e2e-tmp` deleted |
      | A stale `dist` bundle (a trap hit twice before) | reproduces against a freshly built bundle |
      | A flake | **five runs, five failures**, isolation and full suite |
      | The Playwright headless shell | `--headed` crashes identically |

      **Firefox renders the same tree correctly**, twice — so it is a browser
      defect, not application logic.

      **The register's residue guess is the third time a written-down diagnosis
      has been wrong here** (the 2026-08-15 entry records two more, one of which
      named a fix that would have been wrong). *A remedy written into the
      register is still a hypothesis*, and the cost of following one is a
      session spent on the wrong layer — the same cost as the 2026-08-05 stale
      Settings incident.

      **It also falsified a documented claim that shaped the test.**
      `docs/operations/end-to-end-tests.md` said "the identical tree renders
      correctly on a full page load on both engines", which is *why*
      `settings.spec.ts:248` was written with `page.goto` and left unskipped.
      It is false: the crash reaches it through a full document navigation too.
      Corrected there, with the measurement beside it.

      **Ruled by the user the same day: skip it like the other seven.**
      `rules.md` forbids skipping a test to make a build pass, which is why it
      was left failing until the owner ruled rather than tidied away — the rule
      makes this a decision, and the decision was made with the reproduction in
      front of it.

      **Applied through a separate helper, `skipChromiumSettingsCrash`, not the
      existing one.** The existing reason string reads "conversation-route
      navigation", and that text reaches the test report — reusing it would have
      named one thing while showing another, which is the ADR-0019 mistake on a
      new surface. Two triggers, two accurate labels.

      **After the ruling: chromium 8 skipped / 3 passed / 0 failed (exit 0);
      firefox 11 passed / 0 skipped / 0 failed (exit 0).** The Firefox number is
      the one that matters — it is the whole justification, and it was measured
      rather than assumed: no assertion was lost, only the engine it is proven
      on.

      **I manufactured a false RED gate, which is the mirror of this project's
      usual failure.** Running `check_phase7.ps1` through
      `*>&1 | Tee-Object`, the gate reported exit 1 at the web component tests.
      Nothing had failed: **vitest wrote one benign line to stderr**, and
      PowerShell 5.1 wraps a *native command's* stderr in a `NativeCommandError`
      record when streams are redirected, flipping `$?` to false at exit 0. Run
      directly, `vitest run` gives **22 files / 205 tests / exit 0**.

      Three earlier `check_phase4` runs used the same wrapper and passed — **not
      because the wrapper is safe, but because nothing wrote to stderr in
      them.** The hazard is documented for this shell and I hit it anyway.

      This project has recorded false *greens* repeatedly (`$?` after a pipe, a
      gate whose log and exit code disagree). **A false red is the same class
      and costs the same way**: the next reader believes a clean tree is broken.
      **Do not merge streams when invoking a gate** — tee stdout only and let
      stderr through.

      **A hypothesis was offered for how both accounts can be honest**, and
      labelled as one: the Settings page gained a per-repository embedding-model
      field (ADR-0014) and credential entry (ADR-0015) after those eight probes,
      so the tree rendered under a transmitting policy today is not the tree they
      tested. **Not measured**, and the Chromium build is unchanged — so it is
      written as a hypothesis rather than a conclusion.

- [x] **CRLF drift is wider than documentation — it is in source too
      (2026-08-19).** The earlier entry recorded nine Markdown files. The full
      count is **18**: twelve `.py` files plus the six remaining `.md`, and the
      pattern is again decisive — `query_backed/*`, `resolution.py`,
      `registry.py`, `classification.py`, `query_relations.py`,
      `engine_adapter.py` and the four ADR-0065 test files. All from that
      session.

      **One `i/crlf` entry is not drift and proves the mechanism works**:
      `variants/python_app/crlf-only/target/.../service.py` is the deliberate
      ADR-0043 fixture, held CRLF by an explicit `-text` attribute. Declared
      CRLF survives; undeclared CRLF is what drifts.

      Files touched by this session are normalized; the rest are recorded in the
      Deferred Register rather than rewritten. **The durable fix is widening the
      LF guard beyond `tests/evaluation`**, which is why it is a P2 item and not
      a cleanup.

- [x] **ADR-0065 merged to `main` (2026-08-19).** 26 commits, 66 files, 6,424
      insertions — Java, Go, Rust and Scala on the shared query-backed engine,
      plus the first evaluation cases for a query-backed language. Merged
      `--no-ff`, this repository's convention. **`SCHEMA_VERSION` stays 14, no
      migration, `contract_version` stays `1.1`; `PARSER_BUNDLE_VERSION` and
      `RESOLVER_VERSION` are both `1.5.0`, so every snapshot is stale and every
      user reindexes once.**

      **The merged tree is byte-identical to the branch tip** (`git diff`
      returned empty), so the branch's green gate transferred rather than being
      assumed to. The gate was still re-run on `main`, because a merge to `main`
      is the worst place to accept "it passed over there".

      **The first post-merge gate failed, and chasing it was right.** e2e came
      back **13 passes instead of 14**: `restart-persistence` on Firefox expected
      its own question `IdempotencyStore.claim` and the locator resolved five
      times to **`PaymentService.capture`** — another suite's question. **Not a
      timeout and not a timing flake**: the page showed a conversation the test
      never created, which is a cross-suite leak in the shared `.e2e-tmp`
      database. Three clean runs afterwards were 14 passed / exit 0, and the
      second gate on `main` is green.

      **Two things worth carrying.** The failure text *named its own mechanism*
      — the previous occurrence of this family lost which tests failed to a
      truncating pipe, so capturing the whole log is what turned an anonymous
      flake into a register row with evidence. And **nothing was pushed on
      "probably a flake"**: the push waited for a green gate, which is the only
      thing that distinguishes a judgement from a hope.

      **The packaged artifact is now stale against `main`** — it predates
      ADR-0065, is stamped `1.4.0`, and cannot index the four new languages.
      Rebuilding it is the next item, and it must carry `-SemanticLocal` or it
      silently becomes a deterministic-only package.

- [x] **The packaged build was completely broken by ADR-0065, and rebuilding it
      is what found out (P1-2, 2026-08-19).** Two data files were missing from
      the artifact; **the fix is in `build_package.ps1`, and no product code was
      wrong.**

      **It was not a Java-only degradation — the binary could not run at all.**
      `build_registry()` constructs every parser eagerly, so the first command to
      build services died with `FileNotFoundError: tree_sitter_java ships no
      tags.scm`. **`doctor` failed. `repo add` failed. Only `--help` worked.**

      **Two omissions, surfacing one after the other**, which is the part worth
      remembering — fixing the first *revealed* the second:

      | Missing | What it is |
      | --- | --- |
      | each grammar's `queries/tags.scm` | grammar package **data**; `load_tags_source` reads it with `os.walk` |
      | `parsing/query_backed/queries/*.imports.scm` | **our own** authored queries, read relative to `__file__` |

      **The cause is a category error that this repository already had the
      answer to.** PyInstaller finds modules by analysis — the grammar imports
      are static, so `tree_sitter_java` itself was bundled — and it never finds
      *data*. That is precisely why the migrations and the web assets are carried
      explicitly, with a comment saying a frozen build without them "fails on a
      user's **first** run, which is the worst time to find out". ADR-0065 added
      two more data sets and nobody extended the list.

      **The build's own verification could not catch it**: it checks the
      executable answers `--help`, and `--help` was the one command that still
      worked. **A smoke check that avoids constructing services proves less than
      it looks.**

      **The gate would have caught it — nobody ran it.** `check_phase7 -Package`
      registers and indexes a repository, which crashes on this. `-Package` is
      opt-in, and four ADR-0065 slices shipped without it. That is the recorded
      "`-Semantic` / `-Package` gate artifacts nothing else reaches" lesson
      producing a **critical** defect on `main` rather than a stale artifact.

      **Guard added:** `test_the_packaged_build_parses_a_query_backed_language`
      indexes a Java file through the binary and asserts the **resolved symbol**,
      not exit 0 — "the process did not crash" and "the grammar loaded" are
      different facts. No mutation was synthesised for it because the real one
      already happened: the pre-fix binary returned non-zero from `repo add`, and
      the test asserts that returncode.

      **Verified on the final semantic artifact**, not on a proxy: 7/7 packaged
      tests, torch/lancedb/sentence_transformers present, all four `tags.scm` and
      all four `imports.scm` bundled, and the packaged exe indexing `java_app` to
      **4 symbols — identical to source mode** — with
      `OrderService IMPORTS PaymentService` resolving, which is ADR-0065's
      resolver fix running inside the frozen build.

      **Guarded at gate level afterwards (2026-08-19).** The packaged test only
      runs behind opt-in `-Package` -- the flag that let this reach `main` --
      so two unit tests now derive the requirement from the **adapters**: what
      they pass to `load_tags_source` must be `--collect-data`'d, and the
      authored query directory must be `--add-data`'d. They need no build and
      run in every gate. Adapters are found by **glob**, so a new language is
      covered without anyone extending a list -- which is the failure one level
      up from the one being guarded.

      **My own first guard was weak, and mutation is what caught it.** The
      authored-query test asserted only that `"query_backed/queries"` appeared
      somewhere in the script -- and it **passed with the `--add-data` line
      deleted**, because the `$importQueries = Join-Path ...` definition
      contains the same substring. Now matched against the `--add-data`
      argument itself. **Defining a path is not bundling it**, and a
      substring search cannot tell the two apart.

      **A cheap deterministic build was used to find the defect before spending
      a torch build on it.** The grammar-data question is independent of the
      semantic stack, so the fast build answered it twice for a fraction of the
      cost. Worth repeating whenever a packaging question is not about the heavy
      dependencies.

- [x] **ADR-0065's two declared limits are ruled and closed (2026-08-19).**
      ADR-0066 (Go) and ADR-0067 (Scala). **They were ruled in opposite
      directions, and what separates them is the reusable part.**

      **Go: declined, permanently.** A Go import stays `external`. The module
      prefix lives in `go.mod`, which a single-file parse cannot read, so
      closing it needs a *matching policy* rather than more parsing — and the
      cost is asymmetric: trimming too far makes a third-party
      `github.com/foo/payments` resolve onto a local `payments`, **inventing** a
      relationship §4.1 forbids. A miss is safe; an invention is not.

      **Scala: closed.** `LanguageProfile` gained an optional
      `references_query`; Scala authors `scala.references.scm` capturing the
      `field_expression`'s **`field`** — `payments.charge(id)` now emits a
      `CALLS` edge.

      **The distinction is where the missing information lives.** Go's is in a
      file the parser is not permitted to read. Scala's was in the syntax tree
      the whole time and only a *query* was missing. Declaring a limit that nine
      lines of query closes would record an absence of work as a property of the
      language — which is why "both are declared limits of the mechanism" would
      have been the comfortable answer and the wrong one.

      **Both xfails handled the same way, deliberately: inverted, not deleted.**
      The Go test now pins *both* halves — the import is recorded, and it is not
      resolved — so a future matching policy cannot land without the ADR that
      governs it. ADR-0045's precedent: inverting a pinning test is not deleting
      it. **The corpus now carries no xfails at all.**

      **The grammar was measured before the query was written.** A member call's
      `function` is a `field_expression` whose `field` is the method name;
      capturing `value` instead would target the *receiver* and assert that a
      variable was called — a different and false claim. Chained `a.b.c(x)`
      matches once, on `c`.

      **Two guards, for the two ways a supplementary query goes wrong.** One
      asserts a bare call **and** a member call both survive — together in one
      test, because separately each passes while the other is broken — so a
      supplementary query cannot silently *shadow* the shipped one. The other
      asserts a member call is stored **once**, because `parts` spans both
      queries and a doubled `CALLS` edge would inflate impact analysis, which is
      the product's core claim. Mutation-checked: blinding the extractor to the
      supplementary query fails the Scala test.

      **`PARSER_BUNDLE_VERSION` 1.5.0 -> 1.6.0; `RESOLVER_VERSION` deliberately
      unchanged.** Only the *set* of references changed; resolution draws the
      same conclusions from a reference as it always did. **Second forced
      reindex in one day** — not combined with ADR-0065's because the ruling
      came after that change had already shipped and merged.

      **Java, Go and Rust verified unaffected**, not assumed: their profiles
      report `references_query=None` and their suites are unchanged. The slot
      being optional is what makes that true by construction.

- [x] **Package rebuilt at parser 1.6.0 (2026-08-19).** Verified behaviourally:
      7/7 packaged tests, the semantic stack present, the snapshot written *by
      the exe* stamping **parser 1.6.0 / resolver 1.5.0 / chunker 1.1.0** exactly
      as source does, and the packaged binary resolving
      `OrderService.capture CALLS PaymentService.charge` on Scala — **ADR-0067's
      ruling, made hours earlier, working cross-package inside a frozen build.**

      **The build fix held in a way that was not planned for.** The authored
      queries are bundled as a **whole directory**, so `scala.references.scm` —
      which did not exist when that `--add-data` was written — was carried with
      nobody touching the build script. Naming files individually would have
      produced an artifact that started, parsed Java, and **silently lost Scala
      member calls**. Bundle the directory, not its contents.

      Still stale: the zip (`-SkipZip`), and packaged performance was not
      re-measured. Go and Rust were not exercised through the binary — they
      share the engine and loader with Java and Scala, which is an argument
      rather than a measurement.

- [x] **Scala is measured; ADR-0067 now has evaluation coverage (2026-08-19).**
      Corpus **69 -> 73 query cases**, `scala_app` admitted. The only source
      edit is `SUPPORTED_FIXTURES`; no behaviour change, no version bump.

      **q072 is the point of the slice.** ADR-0067 shipped Scala member calls
      that morning, and until now a **unit test was the only thing pinning
      them** — no metric could see the capability at all. Mutation-checked:
      blinding the extractor to the supplementary query fails **q072 alone**,
      while q070/q071/q073 correctly stay green. That is the case doing exactly
      the job it was written for.

      **I nearly "fixed" a correct case, and the check that saved it is the
      lesson.** My probe compared `ranked_symbols[0]` against
      `expected_symbols[0]` and called q073 a failure. Before touching it I
      compared against its Java twin **q069** and its Python analogue **q058** —
      both have the *identical* shape (expected `[subject, target]`, ranked
      `[target]`) and both pass today. So the metric does not score what my
      probe scored. Running the real scorer confirmed
      `exact_symbol_resolution` **1.0000 at 59 cases**.

      **Check what the harness measures before believing a hand-rolled
      comparison of it** — the same family as the earlier false negative from
      comparing `changed_symbols` alone, and the reason this corpus has a
      documented history of "the instrument was wrong, not the engine".

      **Evidence rates rose again** — containing 0.7589 -> 0.7655, exact
      0.6667 -> 0.6759 — because Scala's declared ranges match the engine
      exactly, as Java's did. Two small dips (`ndcg` -0.0012,
      `symbol_recall_at_10` -0.0014) are the known cost of the q055-q058
      convention that declares both ends while `ranked_symbols` carries one.

      **The denominator tripwire fired for the second time in a day** (55 ->
      59) and the margin is *still* unchanged: one miss scores 0.9831 and
      clears 0.98, two score 0.9661 and fail. **The corpus has grown 51 -> 59
      without ever buying slack**, which is the property worth stating whenever
      it grows.

      Go and Rust remain unwritten — **not blocked**, since ADR-0066 declined
      Go's import policy rather than deferring it. They are the next slice.

- [x] **All four ADR-0065 languages are now measured (P1-A, 2026-08-20).**
      Corpus **73 -> 80 query cases**, `go_app` and `rust_app` admitted. Only
      source edit is `SUPPORTED_FIXTURES`; no behaviour change, no version bump.

      **Go deliberately gets no import case, and refusing to write one is the
      finding.** ADR-0066 rules a Go import stays `external`; an external edge
      carries no `target_symbol_id`, so it never appears in a `relation_path`
      (ADR-0057 restricts those to resolved edges). **The corpus vocabulary
      cannot express the ruled outcome at all.** A case written anyway would
      pass whatever the engine did — and a case that cannot fail reads as
      coverage while providing none, which is the c028 lesson. The inverted
      integration test remains the only guard, and that is now stated rather
      than assumed.

      **q080 is the control that keeps ADR-0066 honest.** Rust's `crate` is a
      language *keyword*, so its import **does** resolve — the exact contrast
      that diagnosed Go. Mutation A (emptying the declared-module index) fails
      **q069, q073 and q080** — the three import cases — while the CALLS cases
      survive, because calls resolve through a different tier. So if Rust
      imports ever stopped resolving, ADR-0066's explanation would lose the
      comparison it rests on, and a metric would say so.

      **Mutation B blinds Go's `owner_hint`** — the hook the entire Go slice
      runs on, since Go's receiver is a field rather than a lexical ancestor —
      and fails **q075 and q076** while q074 (a plain struct) survives. Each
      mutation hits exactly the cases that depend on it.

      **Every moved metric moved up**, which has not happened on previous
      growth: containing 0.7655 -> 0.7763, exact 0.6759 -> 0.6908, ndcg and
      `symbol_recall_at_10` both up. Earlier additions traded a small ranking
      dip for evidence; these did not, because all four query-backed fixtures
      have declared ranges the engine matches exactly.

      **The tripwire fired a third time in two days** (59 -> 66) and the margin
      is *still* unchanged — one miss scores 0.9848 and clears 0.98, two score
      0.9697 and fail. **51 -> 66 without ever buying slack.**

      Remaining gap, stated: **change cases exist for Java only** (one), so
      changed-symbol detection is unmeasured for Scala, Go and Rust; and
      `symbol_breadth`, `scala_app`, `go_app` and `rust_app` all carry zero.

- [x] **Change cases for Scala, Go and Rust (P1-B, 2026-08-20).** Corpus **29 ->
      32 change cases**; all four ADR-0065 languages now have change coverage.
      **No source change at all** — variants, cases, two table rows each, counts.

      **c030 measures ADR-0067 on the change side.** Mutating the extractor to
      ignore the supplementary query fails **c030 alone**; c029, c031 and c032
      survive, because Java, Go and Rust ship member-call patterns in their own
      `tags.scm` and Scala does not. So Scala's *impact analysis* depends on that
      ruling, not just its symbol lookup — before ADR-0067 a change to `charge`
      would have reported **no impact whatsoever**.

      **`unmet_targets` is now EMPTY for the first time in the project's
      history, and nothing was fixed.** `changed_symbol_precision` 0.9483 ->
      0.9531 crossed its 0.95 target **by dilution**: c020, c021 and c022 each
      still score **exactly 0.50**, unchanged, and the denominator moved 29 ->
      32. `(29x1.0 + 3x0.5)/32 = 0.9531`; the same three gave `0.9483` at 29.

      **This is a loss of gate signal and it must not be quoted as an
      achievement.** The cases were not added to move it — Scala, Go and Rust
      had no change coverage at all — but the effect is that a real, known,
      per-case defect **stopped being visible to the aggregate**. It is the
      mirror of ADR-0032/0033: there a threshold could not express a miss; here
      the denominator grew until a miss cannot register.

      **Never cite "all Section 19.3 targets met" without this entry.** Recorded
      in the register with a trigger, and in the README beside the number.
      Needs a decision: gate per-case, report the imperfect count beside the
      aggregate, or accept it explicitly.

      **[CLOSED 2026-08-20, and one word above was wrong.]** "A loss of gate
      signal" overstated it. The per-case option was **already implemented** —
      `tests/evaluation/test_change_adapter.py` pins c020-c022 two-sided and has
      since Phase 4, so the *gate* never stopped seeing them; only the
      *aggregate* did, which this entry says correctly one paragraph earlier.
      Resolved by the second option: `changed_symbol_exact_cases` is emitted
      beside the mean, and the Phase 4 row now reads
      `0.9531 (29/32 cases exact)`. Threshold unchanged, the three 0.50s
      unchanged (ADR-0003). **The lesson worth keeping is the misdiagnosis:**
      what was missing got written down before the suite was checked for what
      already existed.

      All three findings are `PUBLIC_BEHAVIOR_CHANGED` — a Scala `require`, a Go
      early `return` and a Rust `assert!` are indistinguishable, because
      `statement_diff` dispatches on Python and TS/JS only. **Three languages
      producing one code is the declared limit, recorded in each case's own
      `limitations` rather than left for a reader to infer.**

- [x] **The LF guard now covers the repository, not the corpus (P2-B, 2026-08-20).** `tests/unit/test_working_tree_line_endings.py`, two
      assertions over `git ls-files --eol`. The old guard was scoped to three
      corpus directories, which is why **18 product files drifted to CRLF with
      nothing failing**.

      **The scope is derived from Git on purpose.** A guard listing `src`,
      `tests`, `scripts`, `apps` would be the same defect it exists to stop —
      a list that must be extended, with nothing enforcing it. Deriving from
      `git ls-files` covers a new directory the day it is committed.

      **Why `git status` never showed this.** `text=auto` normalises on read,
      so Git compares LF to LF and reports clean while the disk holds CRLF.
      Staging a CRLF file shows a plain `A`; the endings appear only in a
      warning nobody keeps. That invisibility is the whole reason it survived.

      **The second assertion is the one worth remembering.** It asks what is
      *permitted* to drift, not what has: a file marked `-text` while its
      bytes are still LF passes the first check and fails this one. That is a
      silencer one commit before it matters. And the first check skips a
      **hard-coded** path rather than reading the `-text` attribute, so
      editing `.gitattributes` cannot turn it off.

      **Proven to fail, four ways**, since a clean tree makes a guard pass
      vacuously: CRLF drift in `src/`; drift plus a `.gitattributes` silencing
      attempt (both assertions fire); a latent `-text` exemption on an LF
      file; and a mixed-ending file, confirming `w/mixed` is reachable rather
      than decoration.

      **One finding on the way:** `tests/fixtures/upgrade/schema_0008.db` also
      carries `-text`, because `*.db binary` expands to `-text -diff`. Real,
      not a test bug. Binaries report `w/-text` and drop out without anyone
      listing extensions. Residual, stated in the docstring rather than
      guarded: marking a *source* path `binary` would hide it from both
      assertions, which is a much louder edit than adding `-text`.

      The corpus guard stays and now cross-references this one. They are not
      redundant: this derives scope from Git and cannot see an **untracked**
      fixture, while that reads bytes off disk and catches one the moment it
      is written. A new fixture is untracked exactly when it is most likely to
      be wrong.

- [x] **README claims are guarded (P2-A, 2026-08-20).** Eight assertions
      deriving the README's version constants, MCP tool count and corpus counts
      from source. **No mutation had to be invented: the README was already
      wrong when the guard was written**, and it caught both drifts on its first
      run — parser bundle `1.5.0` against a declared `1.6.0`, and corpus
      `65/28/8` against `80/32/11`. It correctly *passed* `resolver 1.5.0`,
      which genuinely had not moved, so it discriminates rather than just
      failing.

      **A third stale claim was found that the guard cannot cover**: the Tests
      row still read "2313 passed, 2 xfailed" when both xfails had been closed
      by ADR-0066/0067. A test count is a **measurement**, not derivable from
      source, so no assertion here can hold it. Fixed by hand, and the guard's
      docstring now says what it does *not* cover and why — a guard whose scope
      is unstated gets mistaken for a guarantee.

      **Deliberately narrow.** It checks the facts that have actually drifted,
      not the whole document: a guard that fails on ordinary rewording is one
      people learn to delete.

      This is the fourth item in the pattern the project keeps meeting — a list
      that must be extended when something is added, with nothing enforcing it.
      `SUPPORTED_FIXTURES` and the two `ROWS` tables are guarded and each forced
      a decision; the PyInstaller data list was not, and shipped an artifact
      that could not run at all; `README.md` was not, and drifted twice in two
      days.

## In Progress

~~**s007 — a genuine conceptual retrieval miss.**~~ **Fixed 2026-08-09** by
ADR-0028; it enters the top 10 at rank 8. The remaining Phase 7 miss is
`symbol_recall_at_10` 0.8571 against 0.90, whose residue is s013 and s001.
**Neither channel retrieves `OrderStatus` directly** — both reach it only
through the containing `models.py` chunk, which is a chunking or extraction
question about enums and is open rather than folded into ADR-0028.

Original entry, for the record:

**s007 — a genuine conceptual retrieval miss.** `OrderService.cancel` is absent
from the top 10 for "What happens to held stock if somebody changes their
mind?". Deliberately left as its own slice by the user's ruling so the
measurement correction and the retrieval fix stay attributable. Worth 0.0667 on
`containing_evidence_recall_at_10`.

~~**Nothing.** Verified 2026-08-07 rather than assumed.~~

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

## Nested config keys reported false changes — FIXED (ADR-0041, 2026-08-11)

**Fixed the same day it was reported.** A configuration key now hashes its own
value rather than the line range it cites: parsed value for JSON and TOML,
subtree text for YAML, with the path folded into the hashed string so two keys
holding equal values stay distinct. The reproduction went **8 findings (7
false) → 2**. `PARSER_BUNDLE_VERSION` 1.3.0 → **1.4.0**, so every snapshot is
stale until re-indexed. Gate green: 2181 passed, `check_phase4` exit 0.

**Three things worth keeping.**

**A test passed for the wrong reason and I nearly shipped it.** My first
sibling assertion used `project.scripts.run` — and `run` resolves to its own
line, so it was never affected by the bug and the test passed against the
broken code. The key that actually inherits is the TOML table header
`project.scripts`, which `_leaf_line`'s `key =` pattern cannot match. Caught
only because the *other* new test failed and I checked why this one hadn't.

**Every tracked baseline reproduced byte-for-byte, and that is a limitation,
not a reassurance** — the corpus has no change case over a nested config key,
so it cannot see this defect at all. Same blind spot ADR-0016 and ADR-0029
recorded. The unit tests are the only coverage.

**YAML compares subtree text, not values**, because Phase 2 declined a YAML
parser. Re-indenting a block without changing a value will report that key as
changed. Recorded rather than hidden.

Original diagnosis, kept because the reasoning is the reusable part:

**Reported by the user from a real preflight run and reproduced.** Changing one
line of `pyproject.toml` produces **8 `CONFIG_VALUE_CHANGED` findings, 7 of
them false.**

**This is an ADR-0025 regression, two days old, in the core product wedge.**
That record made nested config keys addressable symbols — right for search, and
it moved `lexical_resolution` 0.3750 → 0.6250. But a leaf whose own line cannot
be located **keeps its parent's range** (a deliberate choice, so a leaf is never
given a guessed line). Change detection hashes content over that range, so every
such leaf hashes the *whole parent block* — and any edit inside the block marks
all of them modified.

ADR-0025 anticipated the wrong risk. It measured **index volume** (6% growth,
judged modest) and never asked what a parent-range fallback does to **change
detection**. The retrieval side was measured; the change side was not, and the
change side is the product's whole wedge.

**The fix is not a filter.** Suppressing children of a changed parent would hide
genuinely changed nested keys. The leaf needs a hash of *its own value*, which
means the parser carrying real per-leaf content rather than a line range —
a `PARSER_BUNDLE_VERSION` bump and a re-index of every snapshot.

**What was NOT reproduced: literal duplicates.** The user saw two identical
`project changed` entries; the JSON contains eight *distinct* titles and no
repeat. So the engine does not duplicate, and the duplicate *rendering* is
unexplained — plausibly the web Preflight screen, which is where they saw it.
**Do not fix the rendering before reproducing it**; the identical evidence spans
above are enough to make distinct findings look duplicated to a reader, and that
may be the whole story.

Reproduction: a temp git repo with this project's own `pyproject.toml`, one
`version` line changed, indexed and analysed through the CLI. Roughly two
minutes to redo.

- [x] **Duplicate and false preflight findings (ADR-0042), 2026-08-11.** The
      user's second duplicate report, and **the register's guess that it "may be
      a UI issue" was wrong.** `FindingsList.tsx` files each finding into exactly
      one severity group; the engine emitted them.

      **`symbol_diff` matched on `(kind, qualified_name)` with no file in the
      key.** A config key name in *N* files was an *N*-versus-*N* match, not
      one-to-one, so it fell to the ambiguous branch and reported every
      occurrence deleted *and* added. On a **clean working tree with
      byte-identical bytes** (`od -c`, so not ADR-0022 line endings) that was
      **4 findings for a repository nobody had edited**; on this repository,
      1592 findings with five identical `cases changed`. The user's "twice" and
      "four times" was the number of files sharing that key name.

      Second cause: every ancestor restated its descendant's edit, the subtree
      residue ADR-0041 recorded. Folding on **line ranges reaches only the
      top-level key**, because ADR-0041 gave intermediates their own one-line
      ranges — so containment for a config key is its **dotted path**, with the
      trailing dot load-bearing (`service.apikey` is not inside `service.api`).

      Clean tree **4 → 0**; one nested edit **4 → 1**; the `pyproject.toml`
      bump **8 → (ADR-0041) 2 → 1**. `RESOLVER_VERSION` 1.3.0 → **1.4.0**, so
      **every snapshot must be re-indexed**. No schema or contract change.

      **The corpus was hiding the reported bug all along.** c012 had emitted two
      `CONFIG_VALUE_CHANGED` findings for one edit since Phase 4, and c014 two
      `PACKAGE_SCRIPT_CHANGED`. No metric could see it: `expected_findings` is a
      **set of codes**, and a set cannot count. Third instance of the
      ADR-0016 / ADR-0029 lesson. Whether it should be a multiset is open.

      Preflight "being deleted" on navigation was never data loss: the report is
      persisted and cached with `staleTime: Infinity`, but its id lived **only
      in the URL** while the sidebar link was hard-coded to the launcher. Now
      remembered per repository in localStorage.

      **Two process notes.** A `git checkout --` used to undo a mutation check
      reverted the fix with it — ADR-0022's lesson about that command cutting
      wider than intended, in a new place; do the revert from a copy. And
      `npx prettier` is **not** a tool of this project (ESLint is the gate);
      running it reported "issues" in correctly formatted files.

- [x] **Line endings are not a change (ADR-0043), 2026-08-11; committed
      2026-08-13.** **Found by verifying ADR-0042 on this repository instead of
      a fixture, and that is the whole lesson.** The small reproduction gave a
      clean tree zero findings. This repository, unmodified, `git status`
      empty, still reported **150 findings across 35 files**.

      `GitBlobStateView` reads the blob; `DirectoryStateView` reads the working
      tree; Git rewrites line endings between them whenever `core.autocrlf` is
      on — **the Windows default**, on the platform Section 5 names as primary.
      Both hashed raw bytes, so every line of such a file differed. **Git and
      CodeAtlas gave opposite answers to "did this file change?"** — for a
      product that is a second opinion on a diff, the worst available
      disagreement.

      Both views now normalize CRLF and lone CR to LF, for the compared hash
      **and** the bytes handed to the parser. Doing only the file level would
      have pushed the disagreement down to every symbol hash inside the file.
      Binaries excluded; `SnapshotStateView` deliberately untouched, because it
      checks disk against an index-time hash and nothing pairs it with another
      view. **1592 → (ADR-0042) 150 → 26.** No schema, contract, or version
      change, and no re-index required by this record.

      **Fourth defect the corpus could not see** (ADR-0016, ADR-0029, ADR-0042),
      second in one day — the fixtures are LF on both sides, so every baseline
      reproduced byte-for-byte. ADR-0022 added the `.gitattributes` pinning
      `eol=lf` for exactly this hazard; **it protected the corpus and not the
      engine.** When a rule is enforced by a file that only the fixtures live
      under, the product is not covered by it.

      **A process failure worth more than the fix.** The work was finished on
      2026-08-11 and then left uncommitted for two days, with its handoff entry
      sitting in a scratchpad file at the repository root and PLAN.md carrying
      408 lines of Markdown table reflow with zero content change. That is the
      `per-repository-embedding-model` failure mode (2026-08-06) again, smaller:
      finished work outside `main` drifts against whatever is decided next.
      Re-verified before committing rather than trusted — 2191 passed, ruff and
      mypy clean — and the reflow was reverted so the handoff is legible in the
      diff. **A formatter run is not a handoff.**

      Open, and the last 26 of the original 1592: the two views disagree about
      which files *exist*, so a tracked file matching a built-in ignore default
      reports `SYMBOL_DELETED` at **high** severity on a clean tree. It is a
      ruling, not a patch, and it is in the Deferred Register.

- [x] **Preflight sees only what it would index (ADR-0044), 2026-08-13.** Closes
      the item ADR-0043 left open — the last of the original 1592, and the only
      one with a user-visible symptom.

      The views disagreed about which files **exist**, not about their bytes.
      `GitBlobStateView` lists everything tracked at the ref;
      `DirectoryStateView` lists what a scan would index. A file that is tracked
      **and** excluded from a scan was in the base, absent from the target, and
      indistinguishable from a deletion — `SYMBOL_DELETED` at **high**, so
      `overall_risk` read `high` on an unmodified checkout.

      **The user's ruling: preflight never considers a file it would not index.**
      The blob side now applies the same ignore rules and the same *content*
      binary sniff. `is_binary_content` was made public rather than restated,
      because two implementations of "is this binary" would put a file on one
      side of a comparison and not the other — the very defect being fixed.
      **12 base-only files → 0**; the two views now list byte-identical path
      sets on this repository. The rejected alternative, letting tracked files
      bypass ignore rules, would have pulled built output and minified bundles
      into the index through the back door of a comparison.

      **Accepted with the ruling:** a tracked-and-ignored file can be added or
      deleted without preflight saying so. It has no symbols and no evidence to
      cite, so reporting it would mean reporting something no answer could
      support.

      **A fourth mechanism was found by reading the scanner, not from a report.**
      The NUL sniff is only its first test — Latin-1 prose carries no NUL and is
      skipped just the same. Closed here too, with `decode_text` shared. It
      returns the *text* rather than a boolean deliberately: a predicate would
      have made the scanner decode every file twice, and paying for a comparison
      fix on every index is the wrong trade. Nothing here triggers it, so this
      one closed a door nobody had walked through.

      **Found while fixing it, and deliberately not folded in:** the remaining
      exclusion mechanism does not disagree, it **refuses**.
      `GitDiffAdapter.archive` raises `ScanLimitExceededError` on any tracked
      file over `max_file_bytes`, so one committed 3 MB CSV makes a repository
      impossible to preflight, while the scanner merely skips it with
      `TOO_LARGE`. Worse than the bug being fixed, and a different ruling — so
      today's behaviour is **pinned by a test** and the question is in the
      register. Nothing here triggers it, which is why it went unnoticed.

      **The verification run found something bigger than the fix, and it is in
      the register.** A real preflight over 7 edited files returned **526
      findings, 524 `SYMBOL_DELETED` at high**, naming Markdown sections of
      `PLAN.md` and this file that exist in **both** states. No matching
      `SYMBOL_ADDED`, so not ADR-0042's shape.

      **I published a cause I had not verified, and it was wrong.** The report
      said a decode step was corrupting an em dash, from a title that printed as
      `2026-07-25T15:15:00Z � P0-SETUP started`. That was **my terminal**: the
      JSON on disk holds `—` intact, with no U+FFFD and no cp1252 `0x97`. The
      retraction is the lesson — a wrong cause in the register costs the next
      reader more than the bug, because they follow it. What the numbers
      actually say is that **505 sections produced 524 deletions**, so nothing
      paired at all.

      **Resolved the same day: the engine was right and the measurement was
      wrong.** The 12-minute analysis ran over a **live working tree while this
      session was rewriting `PLAN.md`** with `Path.write_text`, which truncates
      before it writes. The read landed in that window and saw an empty file.
      An empty target *should* report every section deleted. Proven by exact
      reproduction — empty target: **496 deletions**, against **496** in the
      artifact; truncated mid-write: 491+1; the real edited bytes: **2 findings,
      zero deletions**.

      **This is the sixth consecutive investigation of this shape to find the
      instrument at fault rather than the engine** (ADR-0017, 0018, 0024, 0027,
      0038). The plan predicted that from base rate and made Task 3's
      deliverable *a written cause rather than a patch* — which is the only
      reason no fix was applied to code that was already correct. Two lessons
      worth more than the finding: **do not edit the tree you are measuring**,
      and **a wall of deletions with no additions means the target was not there
      to be read**, not that pairing broke. Three tests now pin all of it. Also worth carrying: that run took
      **over 15 minutes** on this repository, which the docs already explain —
      the engine parses **both full states** every time, O(repository) not
      O(change).

      **Fifth consecutive defect the corpus could not see** (ADR-0016, ADR-0029,
      ADR-0042, ADR-0043). Worse: `test_git_blob_state_view_lists_same_paths_as_directory_view`
      has asserted this exact property **since Phase 4** and passed the whole
      time, because its fixture contains nothing any rule excludes. **A true
      assertion over a corpus that cannot exercise it is not coverage** — which
      is the argument for growing the corpus, now made five times by five
      different defects.

- [x] **Corpus growth started: findings can count, and a document insertion is
      measured (WS-0, WS-1 Tasks 1-2), 2026-08-14.** First execution against
      `docs/superpowers/plans/2026-08-14-post-closeout-program.md`, which gave
      the remaining work six workstreams and two named decision gates instead of
      a recurring "what's next".

      **`expected_findings` was a set of codes, and a set cannot count** - the
      reason c012 emitted a duplicate finding from Phase 4 until 2026-08-11 with
      no metric seeing it. `finding_count_correct` now compares multisets, with
      the aggregate reported beside `finding_precision` and ungated. It catches
      nothing today (1.0); it would have caught c012 on the first run.

      **c025 inserts a document section** so the section below shifts without
      changing - the shape behind the 496 false deletions. The plan's premise
      that no case edits a document was **wrong** (c013 does); the real gap was
      insertion and removal.

      **The transferable number: adding one corpus case touched nine hardcoded
      counts across five files**, found over three full-suite runs. Next time,
      find them in one pass. Two traps worth remembering: the findings `ROWS`
      table is indexed **positionally** by two tests, so a new row goes last;
      and the manifest's `expected_change_count` correctly refuses a silent
      addition.

      **A gate can lie about its own result.** `check_phase7.ps1` prints
      "verification completed" and exits with whatever the last native command
      left - no explicit `exit 0`. I read that line as success several times
      today without capturing `$?`. The suites inside did pass, but the claim
      was inferred, and **a release gate whose log and exit code can disagree is
      a defect**. Also: `.test-tmp` residue fails the next gate, which with
      three concurrency collisions makes four void runs in two days.

      **My own expectation was the wrong one, twice today** - the evidence range
      (a section runs to the next heading, so 5-8 not 5-7) and the claim that no
      document case existed. Both corrected on reasoning rather than on a number
      moving, which is the ADR-0003 line.

- [x] **Three blind-spot corpus cases, and one that cannot be written (WS-1
      Task 3), 2026-08-14.** Commit `a6dba3c`. Corpus is now **28 change cases
      / 40 query cases**. No `src/` change; no version bump, so no snapshot is
      stale.

      **c026** pins ADR-0041 (one nested TOML leaf edit, one finding),
      **c027** pins ADR-0042 (a key name in two files, one finding not four),
      **c028** pins ADR-0043 (a CRLF-only difference is not a change).

      **The one that cannot be written is the lesson.** 3c wanted a
      tracked-but-ignored file (ADR-0044), and the corpus **structurally cannot
      express it**: `predict_changes` compares two `DirectoryStateView`s
      (`engine_adapter.py:581`) and never builds a Git repository, while
      ADR-0044's fix lives in `GitBlobStateView`. Both directory sides already
      apply the same ignore rules, so the case would pass with the fix
      **reverted**. Recorded as a register row rather than committed — because
      a case that always passes reads as coverage and is worse than no case.
      **Check what the harness can actually distinguish before writing a case
      for it.**

      **Every case passed on its first run, so every case was mutation-checked**
      — and that is what caught a bad one. c028's first draft used a Markdown
      file and **passed with the mutation applied**: a section's hash comes from
      parsed text, so line endings dissolve before the diff sees them. It only
      bites on a code file. Without the mutation check it would have been
      committed as permanent green.

      **The plan's premises were stale again, twice.** Same shape as Task 2's
      "no case edits a document". 3a's target already existed — c012 edits a
      nested YAML leaf and has counted since Task 1 — so c026 moved to
      `app.toml`, which nothing touched and which takes ADR-0041's
      *parsed-value* path instead of YAML's subtree-text path. **Assume the
      next stated gap is already half-covered and check first.**

      **Three guards had to be exempted, and the first one is why the defect
      was invisible.** `test_every_corpus_file_has_lf_endings_in_the_working_tree`
      forbids CRLF anywhere in the corpus — so ADR-0043 could never have a case.
      One declared path is now skipped, `.gitattributes` holds its bytes with
      `-text` (`git ls-files --eol` shows `i/crlf w/crlf`), and a **positive**
      test asserts the two sides still differ in bytes and agree normalized.
      An exemption with nothing asserting the bytes is how a case silently stops
      measuring. Also exempted: the empty-prediction guard (c028 by id, with the
      cost written down — a real adapter failure now looks like a pass for that
      one case), and `Row.change`, which became optional so a case can declare
      that *nothing* changed without a placeholder asserting the opposite.

      **Baselines moved for arithmetic and must not be quoted as improvement.**
      Three perfect-scoring cases widen every denominator:
      `changed_symbol_precision` 0.9400 → 0.9464 — still under its 0.95 target,
      still the accepted structural miss — `containing_evidence_rate` 0.6860 →
      0.6932, `primary_evidence_recall_at_10` 0.7667 → 0.7742.

- [x] **Gate exit codes and test isolation — and both register diagnoses were
      wrong (2026-08-15).** Commits `1605fe2`, `19a7c32`. No `src/` change, no
      version bump, no baseline moved.

      **A remedy written into the register is still a hypothesis.** Both rows
      named a mechanism that measurement contradicted, and one of them named a
      *fix* (a lockfile) that would have been wrong. **Seventh
      instrument-not-engine finding.** Reproduce before implementing the
      remedy someone already wrote down — including when that someone was a
      previous session of me.

      **pytest deletes the `--basetemp` you give it** — the directory itself,
      when the first `tmp_path` is requested, with none of the numbering or
      retention it uses by default. Sharing one across runs is the bug; the
      residue in it was a symptom. A second run destroyed a *live* session's
      files. Each session now gets `.test-tmp/s-<pid>-<uuid>`, so two suites
      run concurrently (706 and 815, both green) and the "never run two gates
      at once" rule is retired. **A uuid, not a timestamp**: four processes
      launched together read the *same* `time.time_ns()` on Windows, leaving
      only the pid, and pids are reused (ADR-0037).

      **`powershell -File` does not propagate a trailing native exit code.** A
      script ending `cmd /c "exit 3"` exits 0. The leak only appears in a
      *caller* that reads `$LASTEXITCODE` — measured at 3 through a wrapper.
      So the gates were less broken than recorded, and all eight were fixed
      rather than the one the register named. The safety property — that
      `exit 0` cannot turn a red gate green — is pinned by a test *and* by
      deliberately breaking the real Phase 4 gate, which exited 1.

      **The mutation check earned its cost by failing to fail.** A test the
      plan called a guard passed with the defect reintroduced, because it
      asserted the root was *somewhere* above `tmp_path` — true either way. It
      now asserts the session leaf. A guard nobody has watched fail is a guess.

      **Do not import `tests/conftest.py`.** Doing so makes mypy find it under
      both `conftest` and `tests.conftest` and refuse the entire run — the same
      collision its own comment records for a second conftest module, by a
      different route. Share helpers as **fixtures**.

- [x] **The symbol corpus reaches fifty, and WS-1 is closed (2026-08-15).**
      Commits `c98e72d`, `9f919f0`. Scored symbol-intent cases **27 → 50**, so
      `exact_symbol_resolution`'s 0.98 finally tolerates one miss instead of
      silently requiring 27/27 — ADR-0033's open condition. Corpus is now 63
      query / 28 change cases over 7 fixtures. `exact_symbol_resolution` held
      at **1.0000** across all 50.

      **Check a threshold's arithmetic before growing a corpus toward it.** The
      plan said "~13 more cases". 27 + 13 = 40, where one miss scores 0.9750
      and 0.98 is as inexpressible as before. The real number was **23**,
      because 50 is the first integer where `ceil(0.98 × N) < N`.

      **Count the material, not the cases.** The five fixtures held only ~20
      distinct non-module symbols between them, and the existing 27 cases
      already queried all of them — four pairs ask the same question twice.
      More cases against that material would have padded a denominator to
      loosen a release target, the mirror image of ADR-0032/0033. A **new
      fixture** was the answer.

      **Every intent in `SYMBOL_INTENTS` feeds `exact_symbol_resolution`**, not
      just `EXACT_SYMBOL`. So corpus growth and graph coverage are the same
      job, and the corpus stopped being 16/27 `EXACT_SYMBOL`.

      **A tripwire firing is the tripwire working.** Two
      `test_threshold_granularity.py` tests failed; ADR-0033 wrote them to do
      exactly that once the corpus grew — one says so in its docstring. They
      are now inverted to assert the separation, so a *shrinking* corpus fails
      loudly.

      **Mutation-check with a mutation that matches the claim.** Reversing the
      ranking failed **0 of 23** new cases — most return a single symbol, so a
      reversal is a no-op. Dropping the top hit failed **18 of 23**. The first
      result is not a pass; it is the discovery that these cases are not
      ranking-sensitive, now its own register row.

      **My declared evidence was wrong and the engine was right, again.** Graph
      cases cite the *reference site*, not the definition range (ADR-0003, and
      every existing graph case). Correcting to the convention moved
      `containing_evidence_rate` 0.5984 → 0.6885.

- [x] **Gates A and B ruled; WS-3 delivered, WS-5 reframed (2026-08-15).**
      ADR-0045 and ADR-0046. Both decision gates the post-closeout program had
      carried are closed.

      **Gate A → skip an oversized tracked file, and declare it.** One
      committed 3 MB CSV used to make a repository impossible to preflight,
      while the directory scan merely skipped the same file. **`read_blob`
      still raises on purpose** — it is asked for one specific blob, and
      answering "here is nothing" for a file the caller named is a worse
      contract than refusing. The two Git paths differ deliberately now, and
      the reason is written at both.

      **"Skip it" is only acceptable with the second half.** Trading a loud
      failure for a silent omission is the worse defect for a change-assurance
      tool, so the engine emits a `FILE_TOO_LARGE` warning and a limitation
      naming the files.

      **The quiet half nobody had recorded:** the scanner has recorded
      `TOO_LARGE` since Phase 1 and **nothing ever carried it into a change
      report**, so the directory side was already omitting oversized files
      *silently*. The blob side was at least loud. Look for the silent twin of
      a loud defect.

      **Gate B → a module-level answer satisfies a conceptual question, and no
      ranking change is made.** **The right outcome was to write no code.**
      ADR-0030 had already investigated s001 and found no defect; ruling the
      other way would have declared one, spent real risk on a metric ungated on
      the retrieval profile (ADR-0023), and traded an evidence hit for a symbol
      hit — inverting what the product is for. WS-5 becomes a measurement, not
      a fix.

      **Inverting a pinning test is not deleting it.**
      `test_a_tracked_file_over_the_size_limit_fails_the_whole_comparison`
      existed so the asymmetry could not change silently *in either direction*.
      It now asserts the skip in the same place, beside a test that `read_blob`
      still raises — so the deliberate difference cannot erode either.

- [x] **WS-4 ruled and implemented; a gate now passes with zero margin
      (2026-08-16).** ADR-0047 and ADR-0048. `unmet_targets` is down to
      `['changed_symbol_precision']` alone.

      **`exact_symbol_resolution` is 49/50 = 0.9800 against 0.98 — exactly on
      the line.** ADR-0033 predicted 0.98 would become expressible at 50 cases
      because 50 is the first size tolerating one miss. The corpus reached 50
      and **the first real miss landed exactly on the threshold**. It passes;
      one more miss anywhere gives 0.9600 and it fails. **A green gate is not
      headroom** — say so whenever this number is quoted.

      **Two predictions failed, and both failures were the point.** Step 2
      predicted 0.9765 and gave 0.9588; step 4 predicted ~1.0000 and gave
      0.9706. Both failed **because every corrected range was derived from the
      claim against the fixture's relation table, never copied from the engine's
      output.** Copying would have matched both predictions and buried q006 —
      the only candidate *engine* finding in the entire investigation. **When a
      prediction fails, the model was wrong and that is information; when it
      succeeds because you fitted the expectation to the output, you have
      learned nothing.**

      **State per finding whether it is a faulty instrument or an absent
      decision.** The graph-evidence convention was an *absent decision* —
      nobody had ever ruled what a graph answer cites, and corpus and engine
      were each internally consistent. The `target/` ignore collision was a
      *faulty instrument*. Calling both "the instrument is wrong" was the
      reflex, and a reflex confirmed eight times is how a real engine defect
      eventually gets waved past.

      **A fix can regress metrics it never touched.** Re-including `target/`
      put a second `process` in the index; q035's trace subject became
      ambiguous and the answer now abstains. Abstaining is right
      (`AGENTS.md` §4.1), but it turned a wrong answer into no answer, and the
      accuracy metrics score those differently — four metrics moved, all from
      that one case.

      **Argue a convention from the contract, not from a head count.** The
      reference site is correct because the claim is "X calls Y" and the call
      site proves it, not because more cases used it.

      **A precision metric that cannot be met while the engine obeys an
      accepted decision is punishing compliance** (ADR-0048, ADR-0038's shape).
      Ungate it, keep reporting it — dropping the number changes what every
      tracked baseline means.

- [x] q035 closed; the gate margin restored (ADR-0050), 2026-08-16. The zero-margin
      `exact_symbol_resolution` from the entry above is fixed: **0.9800 → 1.0000
      (50/50)**, `containing_evidence_recall_at_10` 0.9706 → 0.9824,
      `abstention_correctness` and `mean_reciprocal_rank` → 1.0000. Two corpus
      lines in one case; **no source file changed**. `unmet_targets` stays
      `['changed_symbol_precision']`.

      Ruled by the user: q035 declares `query_subject:
      "target.processor.process"`, and its `expected_evidence` becomes the
      reference site `4-4` — a **ninth ADR-0047 instance**, which it could not
      have been on 2026-08-16 because it was abstaining and emitted nothing to
      compare.

      **Three things worth remembering.**

      **A recorded capability limit that was never probed.** `extra_build.md`
      said a disambiguating subject "may not be expressible" because "there is
      no file-scoped selector". `find_exact` has **four tiers** and tier 2 is
      `module_path || '.' || qualified_name`; `target.processor.process`
      resolves to one symbol. The claim had been reasoned about and written
      down, never run. It survived because **the ambiguity message does not
      disambiguate** — it prints `qualified_name`, identical for both, so
      "ask again with a qualified name" is followed by `process, process`.
      Still open as an engine-side row.

      **The fix passed its own mutation-check, and that is the real lesson.**
      Declaring `query_subject` restored the number. Repointing it at the
      *wrong* side (`base.service.process`) scored **identically** — because
      `expected_symbols` is `["process"]` and both fixture sides define that
      name. The case would have passed while tracing the wrong file. Only the
      evidence correction made it discriminate, since the two sides' reference
      sites are in different *files*. Generally: **`exact_symbol_resolution`,
      `mean_reciprocal_rank` and `abstention_correctness` all read a symbol's
      name, so no name-based metric can separate two same-named symbols.** And
      the obvious mutation — reverting the edit — would have failed correctly
      and taught nothing; pick one that could be wrong in the way the case is
      meant to catch.

      **Applying a prior ruling is not fitting to output, but say so out loud.**
      The corrected evidence coincides with what the engine emits, which the
      standing rule warns against. The justification is that ADR-0047's
      convention was ruled *before* q035 emitted anything, so this applies a
      rule to a previously invisible case rather than blessing a run. Stated in
      the ADR rather than left for a reader to worry about.

      Housekeeping found on the way: ADR-0047 forward-references an **ADR-0049
      that was never written**, so this record took **0050** rather than making
      that sentence point at the wrong document; and the ADR README index was
      **stale by two records** (0047, 0048 missing). Both are register rows.

- [x] Gate hygiene: three stale artifacts and a concurrency hazard, 2026-08-16.
      Cleanup after ADR-0050, on the user's instruction. `check_phase4 -SkipSync`
      and `check_phase7 -SkipSync -Semantic` both exit 0; pytest 2240 passed.
      No source, corpus or contract change.

      **A gated artifact behind an opt-in flag is not gated.**
      `baseline-phase-7.json` had not reproduced since 2026-08-14, and fixing it
      let the gate advance one step onto `rerank-phase-7.json` carrying the
      **identical** staleness — same commit, same cause, two added
      `finding_count_correctness` lines, no value changed. Both sat behind
      `-Semantic`, so two days of green `-SkipSync` runs never reached them.
      Rather than wait for a fourth, every tracked artifact with a metrics block
      was audited: only `baseline-phase-1` and `-2` also lack the key, and those
      stay **frozen** (ADR-0017). Each regeneration is its own commit with the
      diff reviewed in the message (ADR-0022).

      **Rebuild the package with the flags it was built with.** The existing
      artifact carried `torch` and `lancedb`; `build_package.ps1` without
      `-SemanticLocal` would have silently produced a deterministic-only
      package. The zip was rebuilt alongside the folder rather than left
      inconsistent with it.

      **Do not run two gate scripts at once.** Concurrently they gave 3 failed /
      2237 passed; solo the same tree gave 2240 passed, exit 0. The 2026-08-15
      `.test-tmp` fix made temp *directories* safe and the one-at-a-time rule was
      then retired **generally** — too broad, because the packaged e2e tests bind
      a loopback port and share one `dist/`. **Which three failed was not
      captured**, because the output was piped through `Select-Object -Last N`,
      so the mechanism is recorded as a hypothesis rather than a finding.

      **Two self-inflicted false-success signals, both the shape this project
      keeps finding.** `$?` after a pipe reports the *pipe's* status — four false
      `EXIT=0` readings, one on a genuinely failing step. And a scratch path
      written `/c/Users/...` rather than `C:/Users/...` is meaningless to Windows
      Python: the script **exited 0 while writing nothing where expected**, and
      the comparison that followed diffed a real file against a missing one.

- [x] q006 closed — **not an engine defect** (ADR-0051), 2026-08-16. The case
      carried as *the only candidate engine finding in nine investigations* is a
      **mis-typed corpus case**. Re-typed `TRACE_FLOW` → `CONCEPTUAL`, with
      **q064 added in the same change**. `containing_evidence_recall_at_10`
      0.9824 → **0.9941**, `primary` 0.9353 → 0.9471, denominator held at 50.
      No source file changed.

      **Both halves of the recorded hypothesis were false**, which is the
      reminder that a written-down diagnosis is not evidence. `claim` *does*
      have an outgoing edge (`CALLS add`, line 8), and evidence is built one per
      edge from `edge.start_line` — nothing "falls back to a chunk or lexical
      hit". And the engine's claim is *"claim calls add at idempotency.py:8"*,
      which line 8 proves exactly; it just does not *answer the question*.
      Line 7 holds no relation, so under ADR-0047 no correct trace can cite it,
      while the product's own `classify()` sends that question to `text` —
      whose result `5-9` contains line 7.

      **Check the denominator before changing an intent, not just before adding
      a case.** `TRACE_FLOW` is a symbol intent, so re-typing q006 alone would
      have dropped `exact_symbol_resolution` 50 → 49, where one miss scores
      0.9796 and **fails** — spending the margin ADR-0050 restored hours before.

      **Three ways a case scores without measuring what it claims**, all found
      by mutation the same day and worth treating as a checklist:
      a **whole-file evidence item satisfies any line in that file** (moving
      q006's expected line 7 → 1 changed nothing, because lexical also returns
      the `1-9` module chunk); **`exact_symbol_resolution` cannot detect a wrong
      expectation**, because `_query_term` feeds `expected_symbols[0]` in as the
      query and checks it comes back; and **no name-based metric separates two
      same-named symbols** (ADR-0050). None of the three was visible to review.

      Left open deliberately: **all three `TRACE_FLOW` cases examined classify
      as `text`**, so the label may be systemically wrong across all six. q003
      and q035 were not touched — q035 had been settled hours earlier and
      reopening it the same day on a different axis would discard that evidence.

- [x] Task 6 investigated; an **engine defect** found on the way (ADR-0052),
      2026-08-17. Not the outcome the task expected, and the more valuable half.

      **A claim beyond the first hop asserted a direct relationship.** Traversal
      runs to `max_depth` 2, so a graph answer routinely holds edges touching
      **neither end of the root**, and `_claims` rendered them against the
      root's name: *"test_capture_uses_idempotency_store calls
      IdempotencyStore.claim at tests/test_service.py:5"*, where line 5 is
      `assert service.capture(...)`. The test calls `capture`, not `claim` — a
      §4.1 violation, the citation showing a different call from the one
      asserted. `relation_paths` was **correct throughout**, so the fix is prose
      only: *"reaches Y indirectly, through Z"*, mirroring ADR-0016.

      **Not the first engine defect** — ADR-0019 was one, and nearly the same
      shape (*evidence named one symbol and showed another*); here the *claim*
      does. Worth saying because the "instrument, not engine" prior had just
      held a ninth time, and a prior confirmed nine times is the one that waves
      the tenth past.

      **Task 6's own premise was wrong.** It asked for "answer sets large enough
      for order to matter". Size is not the mechanism — q060 returns five
      symbols and is not ranking-sensitive, because all five are expected.
      Sensitivity needs a **distractor**, and distractor presence and reversal
      sensitivity are *the same 9 cases*, exactly. The only source of
      distractors is second-hop traversal, so **for a correctly-specified direct
      graph case ranking sensitivity is structurally unavailable** — ADR-0020
      has the corpus declare every endpoint, leaving nothing to mis-rank.
      `exact_symbol_resolution` is therefore a **resolution** gate, not a
      ranking gate.

      **Two mutation lessons, and the second is new.** The first tests were
      worthless: two mutations of the detection passed the *entire* unit,
      integration and contract suite, because the unit tests pass the new
      argument in by hand and never exercise the code that computes it — fix and
      test in different places with nothing covering the join, the `--format pr`
      shape. Then a third mutation exposed a flaw in the *new* test: it asserted
      a word appeared in the **concatenation** of all claims, which an unrelated
      first-hop claim satisfied by itself. **Assert against the one claim under
      test, never the joined text** — a concatenation passes for reasons that
      have nothing to do with the behaviour being pinned.

      Every baseline reproduced byte-for-byte, confirming "prose only" and its
      flip side: the corpus cannot see this fix.

- [x] A gated intent was flattering six metrics (ADR-0053), 2026-08-17. Found
      while verifying Task 4's premise, and it **corrects the previous entry**.

      `CONCEPTUAL` was missing from `SUPPORTED_INTENTS`, so those cases were
      emitted as `_abstention(measured=False)` and **never reached the engine**.
      **q024 had never been measured**; ADR-0051 put q006 in the same state
      hours earlier.

      **ADR-0017 on the neighbouring constant — the one ADR-0017 said "*was*
      maintained" — failing the opposite way.** A gated *fixture* scores `False`
      and stays in the denominator as a miss; a gated *intent* scores
      `measured=False` and **leaves** it. **Under-reporting is loud and gets
      found; removing a failing case is silent, because every number it touches
      moves the right way.** That asymmetry is the thing to remember.

      **The correction to ADR-0051.** Its conclusion survives — measured through
      lexical, q006 gives 0.9943 against the 0.9941 reported, so it does pass
      containment as argued. **But the number was obtained with q006 not
      measured at all.** A conclusion that happens to be true, verified by a
      measurement that could not have shown it, is indistinguishable from a
      wrong one until someone checks. **Check `measured` before quoting a metric
      that moved after a corpus edit.**

      Six metrics fell to the truth (`relation_path_recall` 0.9130 → **0.8750**);
      `exact_symbol_resolution` stayed 1.0000 and no gate broke. Guard derives
      from the **corpus**, not the constant, and is mutation-checked against a
      *future* intent as well as the stale one.

      **Task 4 is three cases, not two**, and still blocked on the ruling
      ADR-0034 asked for. A probe found why it cannot be implemented blind:
      `Order flow` carries eight `DOCUMENTS` edges where the corpus declares
      one, so emitting all stored paths trades recall 1.0 for precision 0.5 —
      ADR-0038's shape.

      **Two self-inflicted failures worth keeping.** `pathlib.write_text`
      rewrote two *source* files to CRLF on Windows — the ADR-0022 hazard on
      files the corpus LF guard does not cover. And **a mutation whose anchor
      failed to apply reported "NOT DETECTED"** for a guard that was never
      mutated: a mutation that does not apply looks exactly like a test that
      does not catch it. Assert the anchor matched, and prefer byte-level edits.

- [x] Task 3: a finding says what it is about (ADR-0054), 2026-08-17. The
      recorded task was a **rendering** problem; reproducing it found an
      **engine defect** underneath.

      `_finding_citations` keyed changed symbols on `qualified_name` **alone**,
      so two modules each defining `total` collapsed to whichever the dict saw
      last and **the finding about `billing.py` cited lines in `orders.py`** —
      a §4.1 violation, and **ADR-0042's own rule ("pair within the file
      first") reaching a surface that ruling did not touch**. The ambiguity
      began earlier: `FindingDraft.subject` was a bare string.

      **Look for what already carries the fact before adding a field to hold
      it.** `Finding` gained optional `subject`/`file_path`, but they are
      **derived from the citation, never stored**: every finding cites exactly
      one evidence item and `_cite` had labelled it with the subject since
      Phase 4. So no migration — `change_findings` has no such columns and
      storing them would be a second copy that can disagree — and one helper
      serves both the fresh and the rehydration path. `contract_version` stays
      `1.1`, `SCHEMA_VERSION` stays 14.

      **The plan was wrong twice**, and neither mattered much once checked:
      construction is in `application/change_analysis.py`, not
      `analysis/findings.py`; and "no migration needed" was right for the wrong
      reason.

      **Six surfaces. SARIF needed nothing** — it already carries the location
      in `artifactLocation`, so fixing the citation was enough, which is what
      "map to its own location model" actually asked for.

      **The web test had no teeth and only a mutation showed it.** Asserting
      both findings *render* stayed green when the key was reverted: React
      renders both children whatever the key, and a duplicate surfaces only as
      a console warning. **Assert on the mechanism the defect produces, not on
      what you hope it disturbs.** Rewritten to spy on `console.error`.

      **A derived field breaks round-trip equality, and that is worth saying
      out loud.** A finding saved without a subject reads back *with* one. That
      is normalisation from stored data rather than invention, and it is now
      pinned by its own test instead of being smoothed away by loosening the
      round-trip assertion.

- [x] Task 5: a route cites the handler it reaches (ADR-0055), 2026-08-17.
      Ruled by the user, and it settles **the last of ADR-0034's four causes for
      `trace`**. q032 **0.50 → 1.00**; `containing_evidence_recall_at_10`
      reaches **1.0000** — every case in the corpus now scores.

      A resolved `ROUTES_TO` edge additionally cites the **handler's
      definition** — an **explicit exception** to ADR-0047, on ADR-0019's
      `EXPORTS` precedent. A route *names* its target, and unlike an export its
      literal and its target sit in different files and usually different
      languages, so the near side alone cannot show what the flow reaches.
      Unresolved routes cite nothing extra.

      **Reproducing it found a defect nobody had recorded.** Evidence is
      deduplicated by region — correctly, one region is one citation — but
      `_claims` was built from the *surviving pairs*, so the second edge on a
      shared line lost its claim. `ROUTES_TO` and the `fetch` call carrying it
      share `frontend.ts:2`, so **the engine dropped its only resolved,
      cross-language edge and kept two unresolved browser globals, by iteration
      order.** `relation_paths` had it, the prose did not — ADR-0020 inverted.
      Fixed as a consequence of the ruling rather than as a separate patch.

      `_verb` had no `ROUTES_TO` entry either, so the claim would have read
      *"relates to"* — unseen because the claim never rendered. **A defect can
      hide behind another defect.**

      **Two of four mutations could not be exercised by the fixture, and both
      looked like passing guards.** Over-applying the carve-out was a no-op
      because every non-route edge in `mixed_app` is unresolved — replaced with
      a `python_app` test where a `CALLS` is resolved. Deleting the claim merge
      is still not caught, because a route literal and its call are the same
      expression and share a line, so the merge never fires here; recorded in
      the register as a stated limit rather than counted as coverage.

      > **A mutation that cannot apply is indistinguishable from a test that
      > cannot catch it.** Check that the mutation actually changed behaviour
      > before reading a green suite as coverage.

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
- **Preflight on a real repository is 635 s, and 99.5% of it is parsing**
  (ADR-0060). The register's ">15 minutes on a 664-file repository" is
  confirmed, not anecdotal. `parse_base` 316 s + `parse_target` 316 s against
  `file_diff` 2.4 s and `symbol_diff` 0.2 s. The remedy is not re-parsing
  unchanged files; **`SnapshotStateView` is not that remedy** — it is unused
  *and* still reads and hashes every file.
- **A synthetic profile measures scaling honestly and proportions
  dishonestly** (ADR-0060). `measure_phase4_perf.py` generates ~15-line
  modules, so `file_diff` looked like the biggest stage and parsing looked
  secondary; on a real tree it is the reverse by two orders of magnitude. Its
  *exponents* held — that is what it is good for. **An earlier draft of
  ADR-0060 repeated its proportions as fact.**
- **A true speedup can still be the wrong fix.** The `symbol_diff` quadratic
  was real (exponent 2.02, 39x at 800 modules) and is worth **2.7%** of the
  real-world number. Quote a speedup with the share of total it moves, or it
  misleads.
- **Guard complexity with a scan-counting test, not a timing test.** Counting
  traversals is deterministic and gate-safe; before the fix it read 51
  traversals for 50 symbols and 401 for 400. Assert *growth* across two sizes
  as well as a ceiling, or raising the constant defeats the guard.
- **Ranking sensitivity needs a two-hop chain, not a bigger answer set**
  (ADR-0059). It is *not* structurally unavailable for a correctly-specified
  direct case, as the plan claimed — `symbol_breadth` simply had no two-hop
  call chain, which is a fixture-shape limit. Adding one made q053 sensitive.
- **Check a denominator before adding a scored case, and again after.**
  Adding q065 moved `exact_symbol_resolution` 50 → 51; one miss still scores
  0.9804 and clears 0.98. Six hardcoded cardinality guards then failed, which
  is the corpus-count tripwire working as designed.
- **`relation_path_recall` is gated at 1.0, absolutely** (ADR-0058), and on the
  `retrieval` profile **only** — the semantic corpus declares zero relations, so
  its aggregate is `None`, and `_unmet_targets` counts `None` as a miss. A
  shared entry would have failed the Phase 7 gate on a metric that corpus cannot
  express. **A threshold the corpus already satisfies is decoration until you
  make it fail:** regressing ADR-0057 drove recall to 0.875 and the gate caught
  it.
- **A lexical answer carries the resolved edges of what it matched** (ADR-0057).
  Resolved only, because `target_symbol_id` is set for no state except
  `RESOLVED` — an unresolved edge has no far endpoint and cannot form a path.
  Eight of `Order flow`'s ten `DOCUMENTS` edges point at prose words. Claims are
  untouched and a step cites evidence **already returned**, so no evidence row
  is added and `containing_evidence_rate` does not move.
- **`_precision` returns 0.0, not 1.0, when nothing is predicted and something
  is expected** (ADR-0057). Predicting that emitting more would *lower*
  precision was wrong for that reason — the three cases were already scoring
  zero on both. **Model the baseline, not just the change**, before predicting a
  metric's direction.
- **A relation-metric aggregate only counts cases that declare a relation.**
  `relation_scores` filters on `case.expected_relations` being non-empty, so a
  case declaring none contributes nothing — which is why q006 and q031 could
  start emitting true undeclared edges with **no number moving anywhere**.
- **ADR-0056 accepted 2026-08-17.** The RRF coarse-chunk penalty stays unimplemented, and now on measurement
  rather than on caution** (ADR-0056). Applied corpus-wide at three strengths,
  **every metric that moves moves down** — including the `symbol_recall_at_10`
  it was supposed to raise. **s013's expected answer is itself a class chunk**,
  so the penalty demotes the answer it exists to promote (7 → 28); s001 loses
  its only containment hit (1 → 11); the one gain is s007, 8 → 7, already
  inside the top 10 so it cannot improve any Recall@10.
- **Check which corpus a metric is computed over before believing it grew**
  (ADR-0056). `_fuse` is gated on `SEMANTIC_INTENTS` and `predict_exact_symbols`
  attaches no fusion, so **WS-1 taking `cases` 27 → 50 never reached the
  fusion measurement**, which still runs on `semantic_cases` — 14 cases, one
  fixture, byte-identical since 2026-07-31. The task premise said "now the
  corpus is larger"; it was another stale one, and Task 4 remains the only
  premise in this program that checked out.
- **CodeAtlas does not download models.** Settings names the model and shows the
  `ollama pull …` command; the user runs it. `pull_ollama_model` was deleted on
  2026-08-05 as unreachable, and the ADR-0014 branch — written a day earlier —
  carried a route and UI for it. Merging on 2026-08-06 would have resurrected
  the feature silently, calling a function `main` no longer has, so **the pull
  was dropped during the merge** and `main`'s newer decision preserved. A pull
  is a multi-gigabyte network operation, and putting it behind a button in a
  settings form makes a slow or failed download look like a failed save.

- **`$?` after a pipe is the pipe's exit code, not the command's.** `cmd | tail`
  then `echo $?` reports `tail`, which always succeeds. This produced four false
  `EXIT=0` readings on 2026-08-16, one of them for a step that was actually
  failing. Capture into a variable first, or use `${PIPESTATUS[0]}`. It is the
  same class as the gate-script exit-code defect, and it survives *because a
  false green looks exactly like a real one*. **Rescued from `extra_build.md`
  when that file was deleted on 2026-08-19; it was recorded nowhere else.**
- **A gate script aborts at its first failing step, so a red step one hides
  everything after it.** When the pytest step fails, nothing downstream in
  `check_phase4` / `check_phase7` has run — do not report those gates as
  anything until their later stages are run directly. **Also rescued from
  `extra_build.md` on 2026-08-19.**

- **A grammar is not a parser, and `tags.scm` is not a graph** (ADR-0065,
  proposed 2026-08-19). Tree-sitter grammars ship a `tags.scm` query file, which
  makes "one generic parser for eleven languages" look obvious. Measured: nine of
  eleven ship one, they are 9-66 lines, and **not one of them captures an
  import** — so the thing resolution is actually built on is the thing the
  generic mechanism cannot supply. A design that looked purely declarative was
  disproven a second way by Go, whose method receiver is a **field of the method
  node rather than a lexical ancestor**, so an ancestor-walking qualified name is
  *wrong* rather than missing. `tags.scm` cuts per-language cost about 4x; it
  does not remove it.
- **Flag scope before refining it.** The request went from "Java and Go" to
  eleven languages. Measuring the existing implementations first — 1,087 lines
  for Python, 1,014 for TS+JS, before fixtures and tests — turned "that's a lot"
  into a number that could be argued with, and turned one impossible task into a
  decomposed program with a spike at the front.

- **A grammar's `tags.scm` marks the KIND; a sibling `@name` capture carries the
  target** (ADR-0065, 2026-08-19). Java's puts `@reference.call` on the
  *argument list*, so reading the reference node's own text gave `"(orderId)"`
  where the method was `charge`. `IMPLEMENTS` passed anyway and was pure luck:
  `type_list` held one identifier, and `implements A, B` would have emitted the
  target `"A, B"`. Found by a test, before it shipped.
- **`resolution.py` had a hardcoded Python-only module index** (ADR-0065). It
  gated `module_to_file` on `record.language == "python"` *and* derived the
  module from the file path, so Java's declared `com.shop.payments` never
  matched `src.main.java.com.shop.payments` and every cross-package import
  resolved `external`. Fixed by indexing the declared `module_path` for
  languages that declare one. **Python and TS/JS are deliberately excluded:
  their module IS their path, and a second opinion would change conclusions
  that are already right.**
- **Landing two staleness bumps together costs one reindex, not two.**
  `PARSER_BUNDLE_VERSION` and `RESOLVER_VERSION` both went 1.4.0 -> 1.5.0 in the
  same change for that reason. Sequencing them would have made users reindex
  twice for one feature.
- **A checkpoint is only worth having if you are willing to be wrong.** ADR-0065
  recorded one assumption read from code rather than measured, and planned Java
  alone so the other three languages were not built on it. The assumption was
  **false**, and the cost of finding out was one integration test rather than
  four languages of rework.

- **A language's module identity may not be in any file you parse** (ADR-0065,
  Go slice). Java declares `package com.shop.payments` in the source, so
  indexing the declaration works. Go's import path carries the prefix from
  `go.mod` — `myapp/internal/payments` — and a parse is a pure function of *one*
  file, so that prefix is unknowable. The fix is not more parsing but a
  **matching policy**, and its cost is asymmetric: trimming too far makes a
  third-party import resolve onto local code, which invents a relationship
  §4.1 forbids. **A miss is the safe direction.**
- **`owner_hint` earned its place.** It was added because Go's receiver is a
  field rather than an ancestor, and Go's whole slice needs no lexical scope at
  all — `scope_node_types` is empty. The hook that justified rejecting a purely
  declarative design is the hook the second language runs entirely on.

## Known Issues

- **A timer is named by its author, not by what it wraps** — the single mistake
  behind ADR-0060, ADR-0061 and ADR-0062, corrected by **ADR-0064 (2026-08-18)**.
  `parse_base` and `parse_target` wrap `_analyze_state`, which lists, reads,
  parses **and resolves**. Reading them as parse time produced, in order:
  "99.5% of preflight is parsing", then a corrected-but-still-wrong
  "parse plus resolve", then "resolution is ~6% and linear". Timed separately
  on a real repository: **parse 8.14 s (2.5%), resolve 310.24 s (97.0%)**.
  Parsing this entire repository takes **eight seconds**.

  Three records' worth of remedies — a within-call parse cache, stored-index
  reuse, a persisted parse cache — were all aimed at that 2.5%. Two were
  declined on their own arithmetic and one shipped; none was wrong to
  investigate, but all three were chosen because of a mis-read timer.

  The actual defect was in `resolution.py`, which claimed
  `O(references), not O(references x symbols)` **in its own module docstring**
  while three call sites scanned every symbol per reference. Fixed by indexing
  them: **313.97 s → 3.55 s, 88x**, verified identical across all 168,605
  relations. Two lessons worth carrying: a docstring's complexity claim is a
  claim, not a guarantee, and a generated corpus can hide a quadratic completely
  — ADR-0062's clean exponent of 1.14 was fitted on a corpus with no Markdown,
  hence no mentions, hence none of the references carrying the quadratic term.

- ~~**`CODEATLAS_EPHEMERAL` governs `serve` only — the CLI always writes the real
  database.**~~ **Made visible 2026-08-09**, not changed. Every command that
  opens a database now prints `Using database: <path>` to **stderr**, and
  `serve` does the same in its persistent branch (its ephemeral branch already
  announced itself, so the mode was only ever legible from one side).

  Stderr is the whole design: `--json` promises a machine-readable stdout, and a
  diagnostic line in that stream would break every scripted caller — a worse
  defect than the one being fixed. A test parses `--json` stdout on its own to
  pin that.

  **This surfaced a latent weakness in `test_upgrade_command.py`.** Its `_run`
  helper concatenates stdout and stderr, deliberately, so refusal messages stay
  testable — and three tests then parsed that combined string as JSON, which
  only ever worked because stderr happened to be empty on success. They now use
  `_run_json`, which reads stdout alone. That is the **stricter** assertion: the
  concatenating helper could not have detected a leak into stdout, because it
  put the leak and the payload in the same string.

  The behaviour split itself is unchanged and remains an open decision below.
- **Whether `CODEATLAS_EPHEMERAL` should cover CLI commands is still open**
  (raised 2026-08-09). `_ephemeral_requested` is read at exactly one
  call site, inside `serve` (`cli/main.py:866`). Every other command goes
  through `_services`, which is `path = database or default_database_path()`
  (`cli/main.py:178`). So `index`, `repo add`, `symbol`, `search`, and `impact`
  persist to `%LOCALAPPDATA%\CodeAtlas\data\codeatlas.db` no matter what that
  variable says, while the web application starts empty every run.

  Both behaviours are as designed. The original complaint was that **nothing
  surfaced the difference**, so a user running with `CODEATLAS_EPHEMERAL=1` was
  right about `serve` and wrong about the CLI, and discovered it only by finding
  data that "should not exist". **That half is now fixed** — both surfaces name
  their database — and what remains open is only whether the variable's *scope*
  should change. That is exactly how this was found: two repositories
  registered 2026-08-01 and 2026-08-03 — before ADR-0013 existed at all — were
  still present, and ephemeral mode could never have removed them, because
  decision 3 is that it never opens the real database. That property is what
  makes the mode safe and is not worth trading away.

  **The practical trap for an agent:** re-indexing a repository in that database
  produces work invisible to a `serve`-based workflow — the 2026-08-05 shape,
  where a fix lands on the artifact nobody is looking at. Check which surface
  the user actually runs before re-indexing anything.

  Whether the variable *should* cover CLI commands is an ADR-0013 amendment and
  an open scope decision, not a config fix.
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

  **Seen again 2026-08-10** and worth recording as a pattern, not an incident.
  Running seven gate scripts back to back (seven full suites) had phases 0–3
  abort mid-run — three of them with exit **-1**, a killed process, and with
  **no `FAILED` line anywhere**, because the run was cut off rather than
  failing. All four passed individually afterwards. *Progress dots that stop
  with no failure summary mean a terminated process, not a broken test* — read
  the whole log before believing a gate result, and re-run in isolation before
  calling it a regression.

- **No guard covers a flag combination that silently skips what it claims to
  run** (raised 2026-08-10). `tests/unit/test_gate_script_invocations.py` now
  catches the array-splat class of gate defect, but the nastier one found the
  same day — `-SkipWeb -Perf` exiting before the measurement and returning 0 —
  has nothing watching it. Given this project's history of green runs that
  measured nothing, this is a real gap rather than a tidy-up.

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

**Current, as of 2026-08-20.** The Deferred Register in `docs/plans/PLAN.md` is
the authority on what is open; this is a pointer, not a third copy.

### Where things stand

**ADR-0065 is delivered, merged, measured and packaged.** Java, Go, Rust and
Scala ship on `main`; both limits it carried are ruled (ADR-0066 declined Go's
import policy, ADR-0067 widened the profile contract for Scala); all four have
query *and* change evaluation cases; and the packaged artifact is rebuilt and
verified at parser `1.6.0`.

Corpus is **80 query / 32 change cases over 11 fixtures**. Versions: parser
`1.6.0`, chunker `1.1.0`, resolver `1.5.0`, `SCHEMA_VERSION` 14,
`contract_version` `1.1`. Last gate: `check_phase4.ps1 -SkipSync` exit 0,
**2350 passed, 3 skipped, no xfails**.

### One decision is waiting on the user

1. **`AGENTS.md` §12 disagrees with the implementation** on two route shapes and
   one unimplemented endpoint. Move the contract or move the code; §25 makes it
   an approval matter. (§5's language profile needs no decision — an approved
   ADR changed it — and is simply unwritten work.)

~~2. **`unmet_targets` is empty and nothing was fixed.**~~ **CLOSED 2026-08-20,
and the framing was half wrong.** `changed_symbol_precision` did cross 0.95 by
**dilution** — c020/c021/c022 still score exactly 0.50 each and the denominator
moved 29 -> 32 — but the option offered first, "gate per-case", was **already
implemented**: `tests/evaluation/test_change_adapter.py` has pinned those three
two-sided since Phase 4, failing if a fourth case slips below 1.0 and equally if
one of the three is quietly "fixed". **No regression guard was ever lost.** What
went blind was the *aggregate* and every report built on it, so the fix was
reporting: `changed_symbol_exact_cases` is emitted beside the mean and the
Phase 4 row now reads `0.9531 (29/32 cases exact)`. The 0.95 threshold is
unchanged and the three 0.50s stand — they are the honest full diff (ADR-0003).

**The reusable lesson is the mistake, not the fix:** the register recorded this
as "no longer visible to the gate" and it was read as urgent for a day on that
basis. Nobody had checked the suite for an existing guard before writing down
what was missing. **Check what already exists before recording a gap.**

### Startable without anyone

The plan is `docs/superpowers/plans/2026-08-20-remaining-work.md`.
**P2-A and P2-B are both done** — the README's claims and the repository's line
endings are now guarded, and those were the two items whose entire purpose was
stopping a recurrence. What is left needs nobody and is small: `SECURITY.md`
(still GitHub boilerplate), the stale `dist/codeatlas-win64.zip`, deleting the
merged `query-backed-language-support` branch, and `AGENTS.md` §5's language
profile (unwritten work, not a decision — an approved ADR already changed it).

**One environment note before running anything:** the suite now takes ~16 minutes
rather than ~6, because a packaged artifact exists and the semantic extras are
installed, so the packaged e2e tests **run rather than skip**. That is more
coverage, not a regression — but a run that looks hung probably is not.

---

**The three items below are DONE and are kept for their reasoning**, which is the
reusable part. They were the resume point on 2026-08-19.

1. ~~**Re-run `scripts/check_phase4.ps1 -SkipSync` and read the whole log.**~~
   **DONE 2026-08-19 — the gate is GREEN on this branch for the first time:
   `2313 passed, 2 xfailed`, exit 0, in 483 s.** All nine stages ran to
   completion (contract schema, tests, ruff, mypy over 379 files, dataset
   validation, the Phase 0/3/4 baselines, ADR-0016 invariants), and
   `git status` afterwards showed only the two documentation files this session
   edited — so **every `--check` baseline reproduced byte-for-byte** and nothing
   regenerated. The two xfails are the declared Go-import and Scala-member-call
   limits. The stale-placeholder fix in `609a63f` is now verified in a full run
   rather than against its own file.

   **The exit code was not trusted on its own**, per the warning below: the run
   was tee'd to a log, `$LASTEXITCODE` captured explicitly to that log
   (`GATE_LASTEXITCODE=0`), and the log grepped for `FAILED` / `ERROR` /
   `Tests failed` / a non-zero exit — all absent. Both signals agreeing is what
   makes this claim safe to make.

   Original entry, kept because the reasoning is the reusable part:

   The run that completed at session end **FAILED** — `1 failed, 2312 passed,
   2 xfailed`. Cause found and fixed:
   `test_registry_resolves_python_and_ignores_unsupported_languages` asserted
   `parser_for("rust") is None`, using Rust as its example of an unregistered
   language — and ADR-0065 registered Rust. **The property was still right; the
   example went stale**, which is exactly what that test's own comment records
   happening to `typescript` in Phase 3. The placeholder is now `kotlin`,
   chosen because ADR-0065 *measured* its grammar as shipping no `tags.scm`, so
   it cannot be registered by this engine.

   **The fix is verified only against its own file (29 passed). The gate has
   never run green on this branch — re-run it before claiming anything.**

   **And read the log, not the exit code.** The background runner reported
   **exit 0** while the log said `Tests failed with exit code 1` and PowerShell
   threw. This project already records "progress dots that stop with no failure
   summary mean a terminated process" and "`$?` after a pipe is the pipe's exit
   code"; this is the same family, and it nearly recorded a red gate as green.
2. **Rule the two declared limits**, both `strict` xfails carrying full
   diagnoses in their test files:
   - **Go import matching policy.** A Go import resolves `external` because its
     path carries the `go.mod` prefix. The cost is **asymmetric** — trimming to
     one segment makes a third-party `github.com/foo/payments` resolve onto a
     local `payments`, *inventing* a relationship §4.1 forbids. A miss is the
     safe direction. Contrast: Rust's `crate` is a keyword, so Rust imports
     resolve — that contrast is the diagnosis.
   - **Scala member calls.** Its `tags.scm` has only
     `(call_expression (identifier) @name)`, so `obj.method(x)` — most Scala
     calls — is invisible. Closing it needs a supplementary references query;
     the profile contract carries one authored slot (`imports_query`).
3. **Decide whether to merge to `main`.** Both version bumps land in one
   reindex; nothing is merged yet.

~~**The largest gap: no evaluation case measures any of the four languages.**~~ **CLOSED 2026-08-19/20 — all four are measured; see the entries above.** Kept for its reasoning:
Unit, integration and security tests are coverage, not measurement, and the
Section 19.3 target table still says nothing about Java, Go, Rust or Scala. No
fixture was added to `SUPPORTED_FIXTURES`, deliberately — ADR-0017's guard
requires scored cases, and gold data must be declared before the engine runs
against it (ADR-0003, ADR-0036). The design, the §25 scope change, and four required
grammar dependencies are all approved. **Approval is not implementation: no code
exists, and no surface may claim these languages work until it lands.** Delivery
is Java -> Go -> Rust -> Scala, and **slice one must verify that `resolution.py`
generalizes to Java and Go module semantics before the other three are built on
it** — that is the one load-bearing claim in the design that was read from the
code rather than measured.
`extra_build.md` was the execution order until its last task closed
(ADR-0050 to ADR-0059); it was **deleted 2026-08-19** on its own instruction,
after its two uniquely-recorded working rules were moved into Decisions above.
References to it in ADRs and handoff entries are historical evidence and were
deliberately left alone.

- ~~**Startable now: Task 7**~~ **DONE 2026-08-17 (ADR-0056).** Measured
  corpus-wide at three penalty strengths: **the lever is a pure loss, every
  metric that moves moves down**, and ADR-0030's predicted *trade* is not a
  trade — `symbol_recall_at_10` falls too. **Nothing is now startable without a
  ruling.**
- ~~**Blocked on a ruling: Task 4**~~ **DONE 2026-08-17 (ADR-0057).** Ruled:
  a lexical or conceptual answer emits relation paths, **resolved edges only**.
  `relation_path_recall` **0.8750 → 1.0000**; **ADR-0034's four causes are fully
  discharged.** The gate target was then **set at 1.0, absolutely** (ADR-0058).
- ~~Original entry: **Blocked on a ruling: Task 4** (what a lexical answer carries). Ask for this
  one first — **ADR-0055 just answered the same question shape for `trace`**,
  and Task 4 asks it for lexical answers. Three cases, not two: q024 joined
  after ADR-0053 made `CONCEPTUAL` measurable.~~
- ~~**Blocked on a ruling: the rest of Task 6**~~ **DONE 2026-08-17
  (ADR-0059).** Ruled: a graph expectation declares **direct results only**,
  which is what makes `exact_symbol_resolution` a ranking gate. **No tasks
  remain**; `extra_build.md` is complete and should be deleted.

Everything below is the older list, kept as written.

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
3. ~~**Consider deleting the five stale local branches** whose content is in
   `main` but which point at pre-rewrite commit objects, so `git branch`
   stops implying unmerged work. `backup-before-rewrite` can go with them once
   the rewrite is trusted.~~ **CLOSED 2026-08-10.** `git branch` now shows
   `main` alone. See the branch-cleanup entry under Completed for the measured
   fact that made `backup-before-rewrite` safe to delete.

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
