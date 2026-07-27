# Phase 4 — Change Assurance

Status: `complete` (gate approved by the user 2026-07-27, with the
changed-symbol precision miss — 0.9375 vs ≥0.95, structural, explained in
`docs/evaluation/phase-4-baseline-environment.md` — reported and accepted)
Gate authority: user
Prerequisites: Phase 3 approved; `AGENTS.md`; the blueprint
Activation gate: satisfied. The user approved this plan on 2026-07-26, recorded
in the `docs/plans/PLAN.md` handoff log, and P4-SETUP moved to `in_progress`
that day. Live task status is in `docs/plans/PLAN.md`, which is authoritative;
the board below is a convenience mirror.

## Outcome

A developer or coding agent points CodeAtlas at a working tree or a commit range
and receives a risk-ordered, evidence-backed account of what changed, what may
break, which tests and documents are affected, and which architecture rules were
newly violated — through the application service, REST, the CLI, and MCP, with
JSON, Markdown, and SARIF renderings of the same persisted analysis.

This is the product wedge (`AGENTS.md` Section 20: "This phase proves the core
product wedge"). It answers the five product questions directly: what changed,
what may be affected, what evidence proves it, how current that evidence is, and
what CodeAtlas does not know.

## Completion Gate (from `AGENTS.md` Sections 20 and 19.3)

Phase 4 may enter `awaiting_user_approval` only when all of the following hold
with verification evidence recorded in the handoff log. Per ADR-0003, every
gate claim that uses an evidence metric names which one it used, and
`exact_evidence_rate` is always reported beside `containing_evidence_rate`.

| # | Gate condition | Measured against |
| --- | --- | --- |
| 1 | Changed-symbol precision and recall ≥ 95% on the declared fixtures | `changed_symbol_precision`, `changed_symbol_recall` |
| 2 | Direct dependency impact recall ≥ 90% | `direct_impact_recall` |
| 3 | Valid file-and-line evidence 100%; both granularities reported | `exact_evidence_rate`, `containing_evidence_rate` |
| 4 | Active-snapshot leakage 0 — no base-side or superseded entity in a target-side answer | snapshot-isolation tests |
| 5 | Working-tree and commit-range analyses produce identical results through the service, REST, CLI, and MCP | cross-adapter tests |
| 6 | Unsupported factual claim rate < 2% | `unsupported_claim_rate` |
| 7 | Warm change-preflight p95 ≤ 10 s; ordinary changed-file deterministic refresh p95 ≤ 2 s, on the declared fixture and named hardware | `scripts/measure_phase4_perf.py` output recorded in `docs/evaluation/phase-4-baseline-environment.md` |
| 8 | Contract-valid REST/MCP responses 100% | contract suite |

A target that is missed is reported as missed, with the measurement and the
reason. The corpus is never edited to meet a number (ADR-0003's independence
principle applies to the change corpus exactly as to the query corpus).

## What Phase 3 Left in Place

Build on these; do not re-derive or duplicate them.

| Asset | Location | Phase 4 relevance |
| --- | --- | --- |
| Two-stage extraction/resolution with stable `relation_id`s | `extraction/`, `domain/ids.py` | an unchanged call site has the same `relation_id` on both sides of a change, which is what lets Phase 4 say "this edge is new" without fuzzy diffing |
| `ResolutionState` with first-class `external`/`unresolved`/`ambiguous` | `domain/relations.py` | a caller of a deleted symbol degrades to `unresolved` in the target graph — the breakage is a recorded fact, not an inference |
| Stored relations, `TESTS` edges, bounded traversal | `storage/sqlite/stores.py`, `retrieval/graph.py` | the target-side impact graph already exists and is queryable without N+1 reads |
| `EvidenceBuilder` with disk-read, hash-verified, drift-aware evidence | `application/evidence.py` | target-side evidence rules are reused unchanged; the change engine adds a base-side companion with the same hash discipline |
| Incremental indexing with measured reuse | `application/indexing.py` | working-tree preflight refreshes the active snapshot first when the tree drifted — this is the ≤2 s refresh path the gate measures |
| Read-only `GitAdapter` security posture | `repositories/git_state.py` | the diff adapter extends the same rules: argument arrays, `shell=False`, `cwd` selection, timeouts, no prompting |
| `Finding` contract model | `contracts.py` | findings already have code, severity, derivation, confidence, evidence IDs, remediation, limitations |
| Evaluation runner change metrics | `evaluation/runner.py` | `score_change_case` already computes precision/recall/impact/finding metrics against `ChangePrediction`; Phase 4 only has to emit honest predictions |
| Cross-adapter equivalence pattern | `tests/contract/test_cross_adapter.py` | the Phase 4 suite extends the same field-by-field comparison to analyses |
| `SnapshotFreshness`, drift warnings, abstention discipline | `contracts.py`, application services | a stale target is refreshed or the analysis says what it could not do; it never guesses |

## Open Items from Phase 3 That Phase 4 Closes

1. **`DOCUMENTS` edges are specified but never derived.** Phase 4 derives them
   (P4-05). The change corpus requires them: `DOCUMENT_REVIEW_REQUIRED` (c012)
   and the document impact paths (c015, c016, c019) are unreachable otherwise.
   As a side effect `related_documents` stops abstaining, which moves
   query-side metrics; the baseline deltas are reported honestly.
2. **Changed-symbol and impact metrics are 0.0000.** They become meaningful for
   the first time and are the headline Phase 4 gate numbers.

Items explicitly **not** closed: the MCP stdio transport loop remains
`# pragma: no cover` (a Phase 6 packaging concern); evidence granularity stays
open per ADR-0003 (Phase 5); the `mcp` dependency footprint is unchanged.

## Global Constraints

Phase 1–3 constraints all still apply. Additions and emphases:

- The change engine core MUST NOT invoke Git. Git is one front-end that
  produces two *states*; the engine compares states. This keeps the engine
  testable against plain directories and keeps the Git surface thin,
  mirroring the scanner/parser split.
- Every `git` invocation follows the `GitAdapter` rules: argument array,
  `shell=False`, `cwd` selection, `GIT_TERMINAL_PROMPT=0`,
  `GIT_OPTIONAL_LOCKS=0`, explicit timeout. Refs are validated against a
  strict grammar before becoming arguments, so `--upload-pack=...` can never
  ride through as an option. Paths read from Git output are untrusted and
  pass `validate_relative_path` containment before use.
- Base-side evidence MUST be hash-verified at analysis time exactly as
  target-side evidence is. A commit blob is immutable, so base evidence is
  historical by construction; it is labeled as base-side, never silently
  presented as current.
- No Git similarity claim. Rename/move findings derive from content-hash
  equality or unique moved-symbol identity — both deterministic. `git diff
  -M` may *pair* candidate files; it never *grounds* a finding.
- Findings are minimal and rule-driven. An extra finding the corpus does not
  expect lowers `finding_precision`, so the rule table fires exactly what its
  conditions prove and nothing more. Aspirational observations go in report
  sections or limitations, never in findings.
- The analysis MUST say when it could not analyze: unresolved refs, missing
  base, parse failures in the changed set, and truncated traversals are
  warnings and limitations, not silence.
- Migrations are forward-only and additive. `0001`–`0006` are applied and
  MUST NOT be edited; Phase 4 adds `0007`.
- Exactly one task may be `in_progress` or `verifying`.
- Test-first: write the failing test, observe it fail, then implement.

## Non-Goals (explicitly deferred)

| Deferred item | Phase |
| --- | --- |
| LLM explanations, embeddings, reranking | 7 |
| Chat/conversation persistence, SSE, web UI | 5 |
| Filesystem watcher, packaging, async/background analysis | 6 |
| Pull-request/CI integration, GitHub/GitLab APIs | out of MVP scope |
| Test execution, coverage claims, runtime behavior claims | never (blueprint Section 3.9) |
| Rename *similarity* scoring beyond content-hash and moved-symbol identity | out of scope (no `git -M` score claims) |
| Full architecture-rule taxonomy (naming, required tests/docs, sensitive paths) | 6+; Phase 4 implements forbidden-relation rules only |
| Documentation drift beyond `DOCUMENT_REVIEW_REQUIRED` for changed documented symbols | 6+ |
| Re-export chains, `tsconfig` paths, monorepo resolution, type inference | carried from Phase 3 |
| Rebase/cherry-pick-aware multi-commit narratives | out of scope |

## Phase Architecture Decisions

Fixed for Phase 4 so tasks compose. Deviation requires an ADR and user approval.
ADR-0005 (P4-SETUP) records decisions 1–8.

### 1. Two states, one engine

```text
Git front-end ──▶ StateView(base)  ─┐
                                    ├─▶ ChangeAnalysisEngine ──▶ ChangeReport
Disk/snapshot  ──▶ StateView(target)─┘   (no Git, no I/O outside readers)
```

A `StateView` exposes the files of one side of a change: relative path,
language, classification, content hash, and a content reader. Three
implementations:

| Implementation | Used for | Content source |
| --- | --- | --- |
| `SnapshotStateView` | target side of a working-tree analysis when the active snapshot is fresh | stored rows + disk reads through the existing drift rules |
| `GitBlobStateView` | base side (any ref), and both sides of a commit range when the active snapshot cannot serve | `git show <ref>:<path>` blobs, hash-verified at read |
| `DirectoryStateView` | evaluation corpus and tests | a directory root, read-only |

The engine is a pure pipeline over two `StateView`s. The evaluation adapter
runs it against corpus directories with no Git involvement; the production
flows run it against Git-backed views. Identical engine, identical rules —
what differs is only where bytes come from.

### 2. The two analysis flows

**Working tree (`analyze_working_tree`).** Default base: `HEAD`.

1. Resolve the repository and Git state. A non-Git repository cannot supply a
   base: `CHANGE_ANALYSIS_REQUIRES_GIT` (HTTP 409, CLI exit 3).
2. Freshness gate: scan the tree and compare the fingerprint to the active
   snapshot. On drift, run the ordinary incremental index first (the measured
   ≤2 s path). On no snapshot, run a full index. If indexing fails, the
   analysis fails with it; the previous active snapshot is untouched.
3. Target state = `SnapshotStateView` over the fresh active snapshot.
4. Base state: `git diff --name-status <base_ref>` gives the changed set.
   Files **not** in the changed set are byte-identical on both sides, so their
   base symbols/references/relations are the target snapshot's rows reused
   read-only. Files in the changed set get base blobs parsed in-memory. Base
   resolution runs in-memory over the union (reused references from unchanged
   files, extracted references from changed base files) — the same
   `SnapshotResolver`, the same trust ordering.
5. Engine run; persist; return.

**Commit range (`analyze_commit_range`).** Refs resolve to commits via
`git rev-parse --verify`. Each side independently uses
`SnapshotStateView` when the active snapshot's `git_head` equals that side's
commit **and** the tree is clean (`git status --porcelain` empty) **and** the
fingerprint still matches; otherwise that side is a full `GitBlobStateView`
parse. The common case `HEAD~1..HEAD` on a clean indexed tree reuses storage
for the target side. A full blob parse is honest about its cost: it is
recorded in `timing_ms` and in the report's limitations for large trees.

### 3. File-level diff and rename handling

The engine's file diff compares path sets and content hashes:

- added / deleted / modified (same path, different hash);
- **renamed**: a deleted path and an added path with identical content hash →
  deterministic rename. When hashes differ, pairing falls back to
  *moved-symbol identity* at the symbol-diff stage (below). `git diff -M`
  output, when present, is used only to order candidates, never as evidence.

### 4. Symbol-level diff

Per changed file pair, both sides are parsed (or reused) and symbols matched
by `(kind, qualified_name)`:

- `added`, `deleted`, `modified` (content hash differs);
- `moved`: a `(kind, qualified_name)` that vanishes from one file and appears
  in exactly one other file, uniquely. A non-unique match degrades to
  `deleted` + `added` with a limitation — a guess is never emitted;
- `dependency`: content unchanged **but** the symbol's resolved edge set
  differs between sides (e.g., a previously unresolved import now resolves).
  This is what makes c011's `render` a changed symbol with only a
  `DEPENDENCY_CHANGED` finding and no behavior finding. Container `MODULE`
  symbols are excluded from `changed_symbols`; their changes surface through
  their members and through dependency findings.

`signature_changed` compares the parsed signature with `export` modifiers
stripped, so a pure export-keyword change is an export finding, not a
signature finding.

### 5. Statement-level body classification

For a `modified` symbol whose signature is unchanged, the two bodies are
diffed line-wise (`difflib`, in-process, deterministic) and changed lines are
mapped to `ast` statements (Python) or tree-sitter statements (TS/JS):

- a **modified** `return` → return-value class;
- a **modified** `raise`/`throw` → error-behavior class;
- an **added** `raise` is an ordinary behavior change (c001), not an
  error-behavior change (c023) — the distinction is whether the statement
  existed before;
- anything else → generic behavior class.

This is a syntax-level judgment and is labeled `high_confidence_heuristic`.
It never claims runtime effect.

### 6. The finding rule table

The heart of the phase. Rules fire per changed symbol (or per file for
F3/F20) in the precedence order shown; within the body-classification group
(F10–F14) exactly one rule fires per symbol. Orthogonal rules (F15–F19,
F22–F24) may co-fire. Evidence is the changed definition's line range
(target side; base side for `deleted`/`moved-from`), the import statement
range for F20, or both file ranges for F3.

| Rule | Trigger (all conditions) | Code | Severity | Derivation |
| --- | --- | --- | --- | --- |
| F1 | symbol `added`, code kind, non-test | `SYMBOL_ADDED` | info | `deterministic` |
| F2 | symbol `deleted` | `SYMBOL_DELETED` | high | `deterministic` |
| F3 | deleted+added file pair matched by content hash or a moved symbol | `FILE_RENAMED` | info | `deterministic` |
| F4 | symbol `moved` (unique identity match) | `SYMBOL_MOVED` | medium | `deterministic` |
| F5 | signature delta is only added optional params **and** body unchanged | `PARAMETER_ADDED` | medium | `deterministic` |
| F6 | any other signature change on a non-private symbol | `PUBLIC_SIGNATURE_CHANGED` | high | `deterministic` |
| F7 | interface/type-alias shape changed (TS) | `PUBLIC_TYPE_CHANGED` | high | `deterministic` |
| F8 | previously exported symbol no longer exported | `EXPORT_REMOVED` | high | `deterministic` |
| F9 | symbol newly exported | `EXPORT_ADDED` | info | `deterministic` |
| F10 | body changed, modified `return`, symbol not route-adjacent | `RETURN_VALUE_CHANGED` | medium | `high_confidence_heuristic` |
| F11 | body changed, modified `raise`/`throw` | `ERROR_BEHAVIOR_CHANGED` | medium | `high_confidence_heuristic` |
| F12 | constructor/`__init__` body changed | `STATE_INITIALIZATION_CHANGED` | medium | `high_confidence_heuristic` |
| F13 | any other public body change | `PUBLIC_BEHAVIOR_CHANGED` | medium | `high_confidence_heuristic` |
| F14 | body changed and symbol has inbound `ROUTES_TO` | `PUBLIC_CONTRACT_CHANGED` | high | `high_confidence_heuristic` |
| F15 | changed symbol in a `TEST_CODE` file | `TEST_CHANGED` | info | `deterministic` |
| F16 | `CONFIG_KEY` value changed | `CONFIG_VALUE_CHANGED` | medium | `deterministic` |
| F17 | `CONFIG_KEY` under `scripts.*` in `package.json` changed | `PACKAGE_SCRIPT_CHANGED` | medium | `deterministic` + warning `PACKAGE_SCRIPTS_NOT_EXECUTED` |
| F18 | `DOCUMENT_SECTION` changed | `DOCUMENT_CHANGED` | info | `deterministic` |
| F19 | changed document content matches the injection-marker list | `UNTRUSTED_CONTENT_CHANGED` | low | `deterministic` + warning `REPOSITORY_CONTENT_IS_DATA` |
| F20 | a file's `IMPORTS` edge set differs between sides | `DEPENDENCY_CHANGED` | medium | `deterministic` |
| F21 | changed symbol owns a route literal whose target set changed, or holds an outbound `ROUTES_TO` | `ROUTE_REFERENCE_CHANGED` | medium | `high_confidence_heuristic` |
| F22 | changed `CONSTANT`/route literal with outbound `REFERENCES` | `CONFIG_REFERENCE_CHANGED` | medium | `high_confidence_heuristic` |
| F23 | changed symbol has inbound `DOCUMENTS` | `DOCUMENT_REVIEW_REQUIRED` | low | `low_confidence_heuristic` |
| F24 | architecture rule violated by an edge whose `relation_id` is absent from the base graph | `ARCHITECTURE_RULE_VIOLATED` (rule ID in details) | from rule | `static_resolved` |

Precedence: F15/F16/F17/F18/F19 (classification) precede F5–F9 (signature)
precede F14, F10, F11, F12, F13 (body, first match only). F1–F4, F20–F24 are
independent and co-fire. The table is verified against all 24 corpus cases in
the appendix of this plan; every case's expected finding set is reproduced
exactly, no more, no less.

### 7. Impact analysis

Seeds: every changed symbol. Edges considered: the target graph (stored or
in-memory resolved) plus the base graph for deleted/moved-away symbols.

- **Direct impact**: every edge touching a seed, either endpoint, either
  graph. Edges targeting a changed symbol's *container* (via `CONTAINS`)
  count — a constructor change surfaces class-level referencers (c004).
- **Transitive**: breadth-first from the direct frontier, default depth 3,
  max 5; visited cap 200/1,000; path cap 25/50. Truncation is a
  `GRAPH_TRUNCATED_*` warning plus a limitation, as in Phase 3.
- **Path orientation** (pinned against all 24 cases): paths are emitted
  changed-symbol-first, `[changed, other]`, except `DEPENDENCY_CHANGED`
  reports the introduced dependency as `[dependency, dependent]` (c011).
- Deleted symbols: impact comes from base-graph inbound edges whose sources
  still exist in the target tree; those sources' target-side references are
  `unresolved`, and that fact is reported in the impact section (not as a
  finding — the corpus does not expect one and precision is a gate).

The report also carries a **test-gap section**: changed code symbols with no
inbound `TESTS` edge, listed informationally with an explicit "a missing
`TESTS` edge does not prove absence of coverage" label. Never a finding.

### 8. Persistence, contract, and reports

Migration `0007` (additive, forward-only; `SCHEMA_VERSION` 6 → 7):

```text
change_analyses(analysis_id PK, repository_id FK CASCADE, kind,
                base_ref, target_ref, base_commit, target_commit,
                base_snapshot_label, target_snapshot_id NULL,
                status, overall_risk, changed_file_count, changed_symbol_count,
                finding_count, warnings_json, limitations_json, timing_json,
                created_at, completed_at)
change_changed_symbols(analysis_id FK, symbol_key, qualified_name, symbol_kind,
                       change_kind, file_path, base_file_path NULL,
                       base_start/end NULL, target_start/end NULL,
                       signature_changed, public, derivation, confidence)
change_findings(analysis_id FK, finding_id, code, severity, title, description,
                derivation, confidence, evidence_ids_json, remediation NULL,
                limitations_json, rank)
change_evidence(analysis_id FK, evidence_id, side, file_path, symbol NULL,
                start_line, end_line, content_hash, derivation, confidence)
```

Analyses are audit records: they survive snapshot pruning and repository
re-indexing. Deleting a repository cascades to its analyses.

The public contract gains one additive schema, `change_analysis_report`
(contract_version stays `"1.0"`; `docs/api/contract-v1.schema.json` is
regenerated): analysis metadata, `base`/`target` references, changed files,
changed symbols, impact edges (with derivation and confidence), findings,
`ChangeEvidenceItem`s carrying an explicit `side: base|target`, warnings,
limitations, `timing_ms`. Evidence is emitted only for findings and changed
definitions — impact edges are labeled graph facts, which keeps the evidence
list minimal and the exact/containing metrics meaningful.

Renderings, all from the same persisted rows: JSON (the contract model),
Markdown (summary, risk, changed symbols, impact, findings by severity,
evidence), and a minimal valid SARIF 2.1.0 subset (rules from finding codes,
results with relative `artifactLocation` and line regions, evidence IDs in
fingerprints). SARIF is an export format, never the internal model.

### 9. Route and document relations (P4-05)

Extraction stays per-file and pure; resolution stays whole-snapshot.

- **Route literals** (TS/JS: `fetch`/axios string or template arguments;
  Python: route-decorator string arguments) are extracted as references.
  Template parameters normalize to `{}` (`/orders/${id}` → `/orders/{}`).
- `ROUTES_TO` (`high_confidence_heuristic`): a call-site route literal
  resolves to a public function in another file whose name tokens intersect
  the path tokens (singular-tolerant, e.g. `orders` ~ `order`), uniquely.
  No unique candidate → no edge, counted as a diagnostic.
- Route literal in a constant/variable initializer → `REFERENCES`
  (`high_confidence_heuristic`) under the same matching (c018's
  `healthPath REFERENCES health`).
- `DOCUMENTS` (`low_confidence_heuristic`, never claim-supporting alone —
  the Phase 3 rule): a document section links to (a) code symbols owning a
  matching route literal, (b) handler candidates by the same token rule, (c)
  a `CONFIG_KEY` when *all* its dotted segments appear as whole words, (d) a
  symbol named exactly as a whole word.

`PARSER_BUNDLE_VERSION` moves `1.1.0 → 1.2.0` (parsers emit new references)
and `RESOLVER_VERSION` `1.0.0 → 1.1.0` (new derivations). Both join
`snapshot_id`, so every existing snapshot supersedes on first index after
this lands — correct, because the derived graph genuinely differs.

### 10. Architecture rules in TOML, not YAML

Rules live in `.codeatlas/rules.toml` inside the repository. TOML is parsed
by stdlib `tomllib`; introducing a YAML dependency for one trusted config
file repeats the mistake Phase 2 deliberately avoided. This deviates from the
blueprint's YAML example and is recorded in ADR-0005; the rule *semantics*
(forbidden relation types between path globs, severity) are the blueprint's.
Rule files are untrusted repository content: validated schema, bounded rule
count, glob syntax validated, unknown fields rejected. `**` glob support is
implemented locally (the ignore-rule subset deliberately lacks it).

### 11. Version constants and error codes

| Constant / code | Value | Effect |
| --- | --- | --- |
| `PARSER_BUNDLE_VERSION` | `1.1.0 → 1.2.0` | snapshot IDs change (P4-SETUP) |
| `RESOLVER_VERSION` | `1.0.0 → 1.1.0` | snapshot IDs change (P4-SETUP) |
| `SCHEMA_VERSION` | `6 → 7` | migration `0007` (P4-08) |
| `CHANGE_ANALYSIS_REQUIRES_GIT` | new | HTTP 409, CLI 3 |
| `GIT_REF_UNRESOLVABLE` | new | HTTP 400, CLI 2 |
| `CHANGE_ANALYSIS_NOT_FOUND` | new | HTTP 404, CLI 3 |
| `ANALYSIS_RULES_INVALID` | new | HTTP 422, CLI 2 |

CLI exit codes are otherwise unchanged: 0 success, 2 invalid input, 3
unavailable, 4 partial (analysis completed with skipped-file warnings),
5 policy failure, 6 internal failure.

### 12. Evaluation corpus variants

The 24 change cases were declared in Phase 0 with target-side content on disk
and the pre-change side declarative. Phase 4 realizes the pre-change side as
**variant overlays** without touching the declared cases, expectations, or
fixture roots (the corpus stays the independent check ADR-0003 requires).

- New root `tests/evaluation/cases/variants/<fixture_id>/<slug>/` holding
  `base/` and/or `target/` overlays. An overlay contains only the files that
  differ; the absent side defaults to the fixture root. Overlays are outside
  fixture roots, so scanners and query evaluation never see them.
- Ref grammar for the adapter: `working-tree:<slug>` → target is the slug's
  `target/` overlay if present else the fixture root; base is the slug's
  `base/` overlay if present else the fixture root. A bare name (`base`,
  `target`) → that subdirectory of the fixture root. `<name>:<slug>` (e.g.
  `target:strict`) → `variants/<fixture>/<name>-<slug>/`.
- Evidence snapshot labels map by suffix: `*-base` → the case's base state,
  anything else → its target state. Validated against the actual overlay
  files at dataset load.

Per-case overlay plan (target state is the fixture root unless noted):

| Case | Overlay | Base vs target delta |
| --- | --- | --- |
| c001 | `python_app/key-validation/base/` | `capture` without the `if not key: raise` guard |
| c002 | `python_app/return-format/base/` | `capture` returns a different f-string format |
| c003 | `python_app/claim-signature/base/` | `claim` with a renamed parameter (non-additive signature change) |
| c004 | `python_app/store-state/base/` | `IdempotencyStore.__init__` without the added state line |
| c005 | `python_app/test-expectation/base/` | test asserts the old expected value |
| c006 | `python_app/delete-fake/target/` | `tests/test_service.py` without `FakeStore`; base is the root |
| c007 | `tsjs_app/order-field/base/` | `Order.id` typed `number` instead of `string` |
| c008 | `tsjs_app/total-signature/base/` | `total` returns `string` instead of `number` |
| c009 | `tsjs_app/render-format/base/` | `render` returns a different template |
| c010 | `tsjs_app/remove-export/target/` | `orders.ts` without `export` on `total`; base is the root |
| c011 | `tsjs_app/client-import/base/` | `client.js` without the `total` import; `render` body identical (call resolves only in target) |
| c012 | `docs_config/port/base/` | `settings.yaml` with a different `service.port` value |
| c013 | `docs_config/health-doc/base/` | README `## Health` section with different text |
| c014 | `docs_config/script/base/` | `package.json` with a different `scripts.test` value |
| c015 | `mixed_app/get-order-return/base/` | `get_order` returns a different payload shape |
| c016 | `mixed_app/frontend-route/base/` | `loadOrder` fetches a different path |
| c017 | `mixed_app/health/base/` | `health` without the added non-return statement |
| c018 | `mixed_app/health-path/target/` | `healthPath` value changed away from `/health`; base is the root |
| c019 | `mixed_app/flow-doc/base/` | `Order flow` section with different wording |
| c020 | — (dirs exist) | `base/service.py` → `target/processor.py`: move + signature + body |
| c021 | — (dirs exist) | `legacy` present in base, absent in target |
| c022 | `git_changes/target-strict/` | `process` gains one optional parameter, body unchanged |
| c023 | `git_changes/error-message/target/` | `process` raise message modified; base is `target/` |
| c024 | `malicious_unsupported/prompt-injection/base/` | `untrusted.md` with different injection wording |

### 13. Performance measurement

`scripts/measure_phase4_perf.py` builds a deterministic synthetic repository
(generated, not a corpus fixture: ~300 Python modules with cross-imports),
indexes it cold, edits one file, then measures over 20 warm runs: (a)
incremental refresh time (target p95 ≤ 2 s), (b) full working-tree preflight
including freshness check, diff, analysis, and report (target p95 ≤ 10 s).
Hardware, OS, Python, and method are recorded in
`docs/evaluation/phase-4-baseline-environment.md`. The script is not a pytest
test; its output is committed documentation, per Section 19.3's naming rule.

### Module map additions

```text
src/codeatlas/
├── domain/
│   └── change.py               # ChangeKind, ChangedSymbol, AnalysisState views' domain types
├── repositories/
│   └── git_diff.py             # GitDiffAdapter: refs, name-status, blob reads (read-only)
├── analysis/
│   ├── __init__.py
│   ├── states.py               # StateView protocol + Snapshot/GitBlob/Directory views
│   ├── file_diff.py            # added/deleted/modified/renamed
│   ├── symbol_diff.py          # symbol match, signature compare, moved detection
│   ├── statement_diff.py       # body statement classification
│   ├── impact.py               # direct + bounded transitive impact
│   ├── findings.py             # the F1–F24 rule table
│   ├── risk.py                 # deterministic ordering and overall risk
│   ├── architecture.py         # rules.toml loading and evaluation
│   └── engine.py               # ChangeAnalysisEngine over two StateViews
├── application/
│   └── change_analysis.py      # ChangeAnalysisService: flows, freshness, persistence
├── delivery/
│   ├── __init__.py
│   ├── markdown_report.py
│   └── sarif_report.py
├── api/routers/
│   └── change_analysis.py      # the four Section 12.4 endpoints
└── storage/sqlite/
    ├── migrations/0007_phase4_change_analysis.sql
    └── stores.py               # + ChangeAnalysisStore
```

## Task Board

Mirror of `docs/plans/PLAN.md`, which is authoritative for live status.

| Task | Deliverable | Dependencies | Status |
| --- | --- | --- | --- |
| P4-SETUP | ADR-0005, version bumps, error codes, corpus-independent checks | Phase 3 | `complete` |
| P4-01 | `GitDiffAdapter` with ref validation and blob reads | P4-SETUP | `complete` |
| P4-02 | Corpus variants + dataset loader/validator extension | P4-SETUP | `complete` |
| P4-03 | `StateView` protocol and the three views + file-level diff | P4-SETUP | `complete` |
| P4-04 | Symbol diff and statement classification | P4-03 | `complete` |
| P4-05 | Route literals, `ROUTES_TO`/`REFERENCES`/`DOCUMENTS` derivation | P4-SETUP | `complete` |
| P4-06 | Impact engine with orientation rules and truncation reporting | P4-04, P4-05 | `complete` |
| P4-07 | Finding rule table, risk ordering, engine assembly | P4-06 | `complete` |
| P4-08 | Migration `0007`, store, analysis flows, freshness gate | P4-01, P4-07 | `complete` |
| P4-09 | Reports (JSON/Markdown/SARIF), REST, CLI, MCP, cross-adapter suite | P4-08 | `complete` |
| P4-10 | Evaluation adapter, baseline, perf, docs, phase gate | P4-02, P4-09 | `complete` |

---

## P4-SETUP — Decisions, Version Bumps, Error Codes

**Why first:** every downstream task depends on the rule table, the state
abstraction, and the version constants; and the snapshot-ID-changing version
bumps must land before any task writes code whose output differs.

**Files**

- Create: `docs/adr/0005-change-assurance-design.md`
- Modify: `src/codeatlas/parsing/registry.py` (`PARSER_BUNDLE_VERSION = "1.2.0"`)
- Modify: `src/codeatlas/extraction/resolution.py` (`RESOLVER_VERSION = "1.1.0"`)
- Modify: `src/codeatlas/domain/errors.py` (four error codes)
- Modify: `src/codeatlas/contracts.py` (`change_analysis_report` models, additive)
- Modify: `docs/api/contract-v1.schema.json` (regenerated)
- Modify: `tests/contract/test_schema_export.py`, contract tests for the new models
- Modify: `docs/plans/PLAN.md` (task board statuses)

**Steps**

- [ ] **Step 1: Write ADR-0005** covering decisions 1–8 and 10 of this plan:
  the two-state engine, the Git front-end security posture, corpus variants,
  the finding rule table with its precedence, base-side evidence discipline,
  route/document heuristics and their derivations, TOML rules, persistence
  and the additive contract.
- [ ] **Step 2: Add the four error codes** with their HTTP/CLI mappings and
  failing tests first.
- [ ] **Step 3: Add the contract models** (`ChangeAnalysisReport`,
  `ChangedSymbol`, `ImpactEdge`, `ChangeEvidenceItem`, envelope metadata) —
  additive, `extra="forbid"`, frozen; regenerate the schema; contract tests
  first.
- [ ] **Step 4: Bump both version constants** and re-run the full suite;
  every snapshot-derived expectation changes, which is the proof the bump
  landed.
- [ ] **Step 5: Run the full gate and append the handoff.**

**Acceptance**

- ADR-0005 records the decisions as designed, including the TOML deviation
  and the no-similarity-claim rule.
- Schema export is current; new models round-trip; nothing existing breaks.

---

## P4-01 — Git Diff Adapter

**Files**

- Create: `src/codeatlas/repositories/git_diff.py`
- Create: `tests/integration/test_git_diff.py`
- Create: `tests/security/test_git_diff_injection.py`
- Modify: `tests/conftest.py` (branched/commit-series git fixtures)

**Interface**

```python
class GitDiffAdapter:
    def resolve_ref(self, root: Path, ref: str) -> str  # -> commit sha
    def changed_files(self, root: Path, base: str, target: str | None) -> tuple[ChangedFileEntry, ...]
    def read_blob(self, root: Path, ref: str, relative_path: str) -> bytes | None
    def list_files(self, root: Path, ref: str) -> tuple[str, ...]
```

`target=None` means the working tree. Refs validate against
`^[0-9a-f]{40}$|^(HEAD(~\d+)?|[A-Za-z0-9][A-Za-z0-9._/-]{0,127})$` and reject
anything starting with `-` or containing `..` outside a range operator,
before becoming arguments. Blob reads are size-capped to the scan limits.

**Steps**

- [ ] **Step 1: Write the failing tests** against real Git fixtures: a
  two-commit repo with a rename, a modified file, a deleted file, an added
  file, and a dirty working tree.
- [ ] **Step 2: Implement** resolution, name-status parsing, blob reads, and
  tree listing with the `GitAdapter` security rules.
- [ ] **Step 3: Write the injection tests**: refs named `--upload-pack=...`,
  `-c core.pager=x`, `HEAD;rm -rf`, paths from mangled `name-status` output,
  and a path that escapes the root all degrade to codes, never to execution
  or escape.
- [ ] **Step 4: Run the gate and append the handoff.**

**Acceptance**

- Every command is read-only, argument-array, `cwd`-selected, timed out.
- A malicious ref or path produces a warning code, never an executed option.

---

## P4-02 — Corpus Variants and Dataset Extension

**Files**

- Create: `tests/evaluation/cases/variants/**` (16 overlay files per the
  decision-12 table)
- Modify: `src/codeatlas/evaluation/dataset.py` (`variants_root`, ref
  grammar, per-state evidence validation)
- Modify: `tests/evaluation/test_dataset.py`
- Create: `tests/evaluation/test_variants.py`

**Steps**

- [ ] **Step 1: Write the failing dataset tests**: a case's evidence validates
  against its *target* state when labeled target-side and its *base* state
  when labeled `*-base`; an overlay outside the variants root is rejected; a
  `..` path in an overlay is rejected.
- [ ] **Step 2: Author the 16 overlays** exactly per decision 12. Each is a
  small file; each is data, never executed.
- [ ] **Step 3: Implement the loader changes** — manifest gains optional
  `variants_root` (default `variants`), the ref grammar resolves states, and
  evidence validates against the resolved state for its label.
- [ ] **Step 4: Prove non-interference**: the query-side dataset validation,
  the Phase 3 baseline `--check`, and the full suite pass unchanged. Variants
  must be invisible to scanners (they live outside fixture roots — asserted
  by test).
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- Dataset validates: 6 fixtures, 40 query cases, 24 change cases, all
  evidence ranges valid against their resolved states.
- No declared case, expectation, or fixture root file was edited.

---

## P4-03 — State Views and File-Level Diff

**Files**

- Create: `src/codeatlas/domain/change.py`, `src/codeatlas/analysis/__init__.py`,
  `src/codeatlas/analysis/states.py`, `src/codeatlas/analysis/file_diff.py`
- Create: `tests/unit/test_file_diff.py`, `tests/integration/test_state_views.py`

**Steps**

- [ ] **Step 1: Write the failing tests** for `DirectoryStateView` (reads a
  tree, hashes content, honors scan limits) and `file_diff` (add/delete/
  modify/rename-by-hash; rename never claimed on similarity).
- [ ] **Step 2: Implement** the `StateView` protocol, `DirectoryStateView`,
  and the file diff.
- [ ] **Step 3: Implement `GitBlobStateView`** over `GitDiffAdapter` with
  hash verification at read, and `SnapshotStateView` over stored rows.
- [ ] **Step 4: Run the gate and append the handoff.**

**Acceptance**

- A rename is reported only on content-hash equality; everything else is
  delete+add.
- `SnapshotStateView` reuses stored symbols/references/relations for
  unchanged files and parses nothing.

---

## P4-04 — Symbol Diff and Statement Classification

**Files**

- Create: `src/codeatlas/analysis/symbol_diff.py`,
  `src/codeatlas/analysis/statement_diff.py`
- Create: `tests/unit/test_symbol_diff.py`,
  `tests/unit/test_statement_diff.py`

**Steps**

- [ ] **Step 1: Write the failing tests** per decision 4/5: added/deleted/
  modified/moved/dependency classification; unique-move vs ambiguous
  fallback; export-stripped signature comparison; `PARAMETER_ADDED` vs
  `PUBLIC_SIGNATURE_CHANGED` (added-optional-params *and* body unchanged);
  return/raise modified vs added; constructor state init.
- [ ] **Step 2: Implement** the symbol diff over the two states' parsed
  symbols, including the resolution-set comparison for `dependency` changes
  and container-exclusion for `MODULE` symbols.
- [ ] **Step 3: Implement** statement classification with `difflib` +
  `ast`/tree-sitter statement mapping.
- [ ] **Step 4: Run the gate and append the handoff.**

**Acceptance**

- Every classification rule in decisions 4–5 has a direct test, including
  the c020-vs-c022 signature distinction and the c001-vs-c023 raise
  distinction.

---

## P4-05 — Route and Document Relations

**Files**

- Modify: `src/codeatlas/parsing/tsjs_parser.py` (route literals)
- Modify: `src/codeatlas/parsing/python_parser.py` (decorator route literals)
- Modify: `src/codeatlas/parsing/document_parser.py` (mention references)
- Modify: `src/codeatlas/extraction/resolution.py` (derivations)
- Create: `tests/unit/test_route_literals.py`,
  `tests/integration/test_document_edges.py`
- Modify: `tests/integration/test_resolution.py`, graph query tests

**Steps**

- [ ] **Step 1: Write the failing tests**: template-literal normalization
  (`/orders/${id}` → `/orders/{}`), unique-handler matching, singular-tolerant
  tokens, constant-held literals becoming `REFERENCES`, document section →
  route owner/handler/config-key/exact-symbol `DOCUMENTS` edges, and the
  "never supports a claim alone" rule still holding in graph answers.
- [ ] **Step 2: Implement** extraction in the three parsers.
- [ ] **Step 3: Implement** resolution with diagnostics for non-unique or
  absent candidates.
- [ ] **Step 4: Assert the side effects explicitly**: `related_documents`
  answers the mixed/docs fixtures; re-indexing supersedes every snapshot
  (new version constants); no fixture outside mixed_app/docs_config gains
  edges (noise budget zero, asserted).
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- c015–c019's edges exist with the corpus's kinds and honest derivations.
- No `ROUTES_TO`/`DOCUMENTS` edge appears without a citable source range.

---

## P4-06 — Impact Engine

**Files**

- Create: `src/codeatlas/analysis/impact.py`
- Create: `tests/unit/test_impact.py`, `tests/integration/test_impact_engine.py`

**Steps**

- [ ] **Step 1: Write the failing tests** for: direct inbound/outbound across
  both graphs; container-target matching (c004); deleted-symbol base-side
  impact with target-side `unresolved` reporting; transitive expansion to
  depth 3 with truncation surfaced; the two orientation rules
  (changed-first; `[dependency, dependent]` for `DEPENDENCY_CHANGED`).
- [ ] **Step 2: Implement** the impact engine over the two states' relation
  sets with the Phase 3 bounds table.
- [ ] **Step 3: Verify against all 24 cases' expected impact paths** as a
  unit-table test (the corpus itself is exercised in P4-10; this table
  pins the rule per case).
- [ ] **Step 4: Run the gate and append the handoff.**

**Acceptance**

- All 24 expected impact-path sets are reproduced by the orientation rules.
- Truncation produces both a warning and a limitation.

---

## P4-07 — Findings, Risk, and Engine Assembly

**Files**

- Create: `src/codeatlas/analysis/findings.py`, `src/codeatlas/analysis/risk.py`,
  `src/codeatlas/analysis/architecture.py`, `src/codeatlas/analysis/engine.py`
- Create: `tests/unit/test_findings.py`, `tests/unit/test_risk.py`,
  `tests/unit/test_architecture.py`, `tests/integration/test_engine.py`

**Steps**

- [ ] **Step 1: Write the failing tests** for the F1–F24 table: each rule's
  trigger, precedence within the body group, co-firing rules, evidence
  selection, and the full per-case expectation table (all 24 cases produce
  exactly their declared finding sets).
- [ ] **Step 2: Implement** findings and risk ordering.
- [ ] **Step 3: Implement `architecture.py`**: `rules.toml` loading with
  strict validation, `**` glob matching, new-edge-only violation reporting
  via `relation_id` set difference.
- [ ] **Step 4: Assemble `ChangeAnalysisEngine.analyze(base, target)`**:
  file diff → symbol diff → impact → findings → test-gap section → risk →
  report object with timings.
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- The engine produces the declared finding set for every corpus case in
  isolation, with no Git involvement.
- Injection-marker matching treats content as data (c024) and a rule file
  with hostile content degrades to `ANALYSIS_RULES_INVALID`.

---

## P4-08 — Persistence, Flows, and Freshness Gate

**Files**

- Create: `src/codeatlas/storage/sqlite/migrations/0007_phase4_change_analysis.sql`
- Modify: `src/codeatlas/storage/sqlite/migrations.py` (`SCHEMA_VERSION = 7`),
  `src/codeatlas/storage/sqlite/stores.py` (`ChangeAnalysisStore`)
- Create: `src/codeatlas/application/change_analysis.py`
- Modify: `src/codeatlas/application/container.py`
- Create: `tests/integration/test_change_analysis_service.py`,
  `tests/integration/test_change_analysis_store.py`
- Modify: `tests/integration/test_migrations.py` (v6→v7 upgrade preserves rows)

**Steps**

- [ ] **Step 1: Write the failing migration and store tests** (forward-only,
  cascades with repository deletion, survives snapshot pruning).
- [ ] **Step 2: Implement** the migration, store, and report round-trip.
- [ ] **Step 3: Write the failing flow tests**: working-tree preflight on a
  real Git fixture (fresh snapshot reuse, drift-triggered incremental
  refresh, no-snapshot full index); commit range with clean-tree reuse and
  blob-parse fallback; non-Git repository → `CHANGE_ANALYSIS_REQUIRES_GIT`;
  unresolvable ref → `GIT_REF_UNRESOLVABLE`.
- [ ] **Step 4: Implement `ChangeAnalysisService`** wiring freshness,
  states, engine, persistence.
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- A working-tree preflight on the Phase 3 fixture repos runs end to end and
  persists a report retrievable by ID.
- A v6 database upgrades in place with analyses intact.

---

## P4-09 — Reports and Adapters

**Files**

- Create: `src/codeatlas/delivery/__init__.py`,
  `src/codeatlas/delivery/markdown_report.py`,
  `src/codeatlas/delivery/sarif_report.py`
- Create: `src/codeatlas/api/routers/change_analysis.py`
- Modify: `src/codeatlas/api/app.py`, `src/codeatlas/cli/main.py`
  (`impact`, `analysis` commands), `src/codeatlas/mcp/tools.py`
  (`analyze_working_tree`, `analyze_commit_range`, `get_change_analysis`,
  `get_change_report`)
- Create: `tests/unit/test_markdown_report.py`,
  `tests/unit/test_sarif_report.py`, `tests/contract/test_change_analysis_api.py`,
  `tests/contract/test_change_cross_adapter.py`, `tests/end_to_end/test_impact_cli.py`

**Steps**

- [ ] **Step 1: Write the failing renderer tests**: Markdown structure and
  escaping (repository text cannot break out of a code fence), SARIF 2.1.0
  minimal validity (schema-checked fields, relative URIs, line regions).
- [ ] **Step 2: Implement** both renderers from persisted rows.
- [ ] **Step 3: Write the failing adapter tests**: the four REST endpoints,
  CLI `impact --base/--commits/--format` with exit codes, the four MCP
  tools, and the cross-adapter field-by-field equivalence suite.
- [ ] **Step 4: Implement** the adapters — thin, over `ChangeAnalysisService`
  only.
- [ ] **Step 5: Run the gate and append the handoff.**

**Acceptance**

- The same analysis returns byte-identical evidence and findings through
  service, REST, CLI, and MCP.
- SARIF output parses as valid 2.1.0 with zero absolute paths.

---

## P4-10 — Evaluation, Baseline, Performance, Docs, Phase Gate

**Files**

- Modify: `src/codeatlas/evaluation/engine_adapter.py` (`predict_changes`)
- Create: `tests/evaluation/test_change_adapter.py`
- Create: `scripts/run_phase4_baseline.py`, `scripts/check_phase4.ps1`,
  `scripts/measure_phase4_perf.py`
- Create: `docs/evaluation/baseline-phase-4.json`, `.md`,
  `docs/evaluation/phase-4-baseline-environment.md`
- Create: `docs/operations/change-analysis.md`
- Modify: `docs/security/threat-model.md`, `README.md`,
  `scripts/check_phase3.ps1` (mark superseded), `docs/plans/PLAN.md`, this plan

**Steps**

- [ ] **Step 1: Write the failing adapter tests**: each of the 24 cases runs
  through the engine via `DirectoryStateView`s and maps to a
  `ChangePrediction` with the label rules of decision 12.
- [ ] **Step 2: Implement `predict_changes`** and generate the Phase 4
  baseline with timings excluded.
- [ ] **Step 3: Report every metric honestly**, including exact vs containing
  evidence and any case that misses, with a per-case explanation as prior
  phases did. Do not edit the corpus to meet a number.
- [ ] **Step 4: Write `measure_phase4_perf.py`**, run it, and record the
  numbers with hardware in the environment doc.
- [ ] **Step 5: Write `docs/operations/change-analysis.md`** (flows, rule
  table, orientation rules, what Phase 4 still does not do), update the
  threat model (Git diff surface, rules file trust, temp handling, report
  injection) and README.
- [ ] **Step 6: Write `check_phase4.ps1`**, run the full gate, record
  commands, exit codes, and results, and set Phase 4 to
  `awaiting_user_approval`.

**Acceptance**

- The gate table at the top of this plan is measured and reported, including
  any miss.
- `check_phase4.ps1` exits 0.

---

## Verification Commands

```powershell
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases --check
uv run python scripts/measure_phase4_perf.py
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1
```

## Task Status Transitions

`docs/plans/PLAN.md` holds the authoritative status and the full handoff
evidence for every transition. This table records only where each task's
evidence lives.

| Task | Status | Recorded |
| --- | --- | --- |
| P4-SETUP | `complete` | PLAN.md handoff 2026-07-27T00:00:00Z |
| P4-01 | `complete` | PLAN.md handoff 2026-07-27T00:00:01Z |
| P4-02 | `complete` | PLAN.md handoff 2026-07-27T00:00:02Z |
| P4-03 | `complete` | PLAN.md handoff 2026-07-27T00:20:00Z |
| P4-04 | `complete` | PLAN.md handoff 2026-07-27T00:30:00Z |
| P4-05 … P4-10 | see PLAN.md | PLAN.md task board and handoff log |
