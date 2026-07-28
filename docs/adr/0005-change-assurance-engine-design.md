# ADR-0005: Change-Assurance Engine Design

- Status: accepted
- Date: 2026-07-26
- Decision owners: user (Phase 4 plan approval), implementing agent (record)
- Supersedes: none
- Refines: ADR-0001, ADR-0003, ADR-0004

## Context

Phase 4 builds the product wedge — change assurance. A developer or coding agent
points CodeAtlas at a working tree or a commit range and asks what changed, what
may break, which tests and documents are affected, and which architecture rules
were newly violated. The result must be evidence-backed, snapshot-isolated,
risk-ordered, and delivered through the same shared application services as
everything else, with JSON, Markdown, and SARIF renderings of one persisted
analysis.

Eight interlocking decisions had to be fixed before eleven tasks could depend on
them, because each changes output shape, identity, or trust semantics and is far
cheaper to fix now than after the fact.

The Phase 0 change corpus declares 24 cases with expected changed-symbol sets,
impact paths, and findings, but the pre-change side is declarative ("Fixture
change is declarative in Phase 0"). The corpus is the independent check
(ADR-0003); the engine must be made to satisfy it without editing it.

## Decision

### 1. Two states, one engine

The change engine compares a base `StateView` and a target `StateView` and never
invokes Git. Git is one front-end that produces states (working-tree and
commit-range flows); plain directories are another (the evaluation corpus and
fixture tests). Three `StateView` implementations — `SnapshotStateView` (stored
rows + disk reads, used for a fresh target), `GitBlobStateView` (base side and
historical commits), and `DirectoryStateView` (corpus/tests) — feed one
`ChangeAnalysisEngine`. The evaluation harness exercises the same engine the
production flows use, with no Git involvement.

### 2. Git front-end security posture

`GitDiffAdapter` extends the `GitAdapter` rules: argument arrays with
`shell=False`, repository selected by `cwd` never a positional path,
`GIT_TERMINAL_PROMPT=0`, `GIT_OPTIONAL_LOCKS=0`, explicit timeout, read-only
plumbing commands only. Refs are validated against a strict grammar before
becoming arguments, so `--upload-pack=...` and `-c core.pager=x` can never
parse as options. Paths read from Git output are untrusted and pass
`validate_relative_path` containment before use. Blob reads are size-capped to
the scan limits.

### 3. Corpus variants (no corpus edit)

The 24 change cases become executable through overlay directories under
`tests/evaluation/cases/variants/<fixture>/<slug>/` holding `base/` and/or
`target/` overlays of only the files that differ; the absent side defaults to
the fixture root. No declared case, expectation, or fixture root file is edited.
The dataset manifest gains an optional `variants_root`. The ref grammar maps
`working-tree:<slug>`, named subdirectories (`base`, `target`), and
`<name>:<slug>` to the resolved states. Evidence snapshot labels map by suffix
(`*-base` → base state, else target state). Variants live outside fixture
roots, so scanners and query evaluation never see them.

### 4. Finding rule table with pinned precedence

Findings are rule-driven and minimal: an extra finding the corpus does not
expect lowers `finding_precision`, so the F1–F24 table fires exactly what its
conditions prove. Deterministic structural findings (added/deleted/renamed/
moved/signature/export/config/test/document/dependency) co-fire with
`high_confidence_heuristic` statement classifications (return-value,
error-behavior, state-init, behavior, public-contract) and a few
`low_confidence_heuristics` (document-review). The body-classification group
fires exactly one rule per symbol in fixed precedence: contract > signature >
return/throw/state-init > behavior. A `PARAMETER_ADDED` finding requires added
optional parameters **and** an unchanged body, which is the c020-vs-c022
distinction. The table is verified against all 24 corpus cases in the phase plan
and pinned executably in P4-07.

### 5. Impact orientation

Impact paths are emitted changed-symbol-first, `[changed, other]`, for every
edge touching a changed symbol in either graph, except
`DEPENDENCY_CHANGED`, which reports the introduced dependency as
`[dependency, dependent]`. That pair of rules is the only orientation consistent
with all 24 expected impact-path sets. Deleted symbols draw impact from
base-graph inbound edges whose sources still exist in the target tree; those
sources' target-side references are `unresolved`, reported in the impact section
(not as a finding). Edges targeting a changed symbol's container through
`CONTAINS` count, so a constructor change surfaces class-level referencers.

### 6. No Git similarity claims

Rename and move findings derive only from content-hash equality or unique
moved-symbol identity — both deterministic. `git diff -M` output may *order*
candidate pairs but never *grounds* a finding. The c020 forbidden claim ("Git
similarity was measured.") records this rule in the corpus itself.

### 7. Base-side evidence discipline

Base-side evidence is hash-verified at analysis time exactly as target-side
evidence is. A commit blob is immutable, so base evidence is historical by
construction; it is labeled with an explicit `side: base` in the report and
never silently presented as current. Evidence is emitted only for findings and
changed definitions — impact edges are labeled graph facts, which keeps the
evidence list minimal and the exact/containing metrics meaningful (ADR-0003).

### 8. Persistence, contract, and relation additions

Migration `0007` (additive, forward-only; `SCHEMA_VERSION` 6 → 7) adds four
tables: `change_analyses`, `change_changed_symbols`, `change_findings`, and
`change_evidence`. Analyses are audit records that survive snapshot pruning and
cascade with repository deletion. The contract gains one additive schema,
`change_analysis_report` (`contract_version` stays `"1.0"`), with
`ChangeEvidenceItem`s carrying an explicit `side`. `PARSER_BUNDLE_VERSION`
moves `1.1.0 → 1.2.0` (parsers will emit route-literal and document-mention
references in P4-05) and `RESOLVER_VERSION` `1.0.0 → 1.1.0` (the resolver will
derive `ROUTES_TO`/`REFERENCES`/`DOCUMENTS` in P4-05). Both join `snapshot_id`,
so every existing snapshot supersedes on first index after the bump — correct,
because the derived graph genuinely differs. Four error codes are added:
`CHANGE_ANALYSIS_REQUIRES_GIT` (409/3), `GIT_REF_UNRESOLVABLE` (400/2),
`CHANGE_ANALYSIS_NOT_FOUND` (404/3), `ANALYSIS_RULES_INVALID` (422/2).

### 10. Architecture rules in TOML, not YAML

Rules live in `.codeatlas/rules.toml` inside the repository and are parsed with
stdlib `tomllib`. The blueprint's example uses YAML; this decision deviates
because Phase 2 deliberately kept a YAML dependency out of the tree, and adding
one for a single trusted configuration file would repeat that avoidance for no
gain. The rule *semantics* (forbidden relation types between path globs, rule
severity) are the blueprint's. Rule files are untrusted repository content:
validated schema, bounded rule count, glob syntax validated, unknown fields
rejected. `**` glob support is implemented locally; the ignore-rule subset
deliberately lacks it. Phase 4 implements forbidden-relation rules only; the
broader rule taxonomy (naming, required tests/docs, sensitive paths) is 6+.

## Alternatives

- **A single-stage engine that parses both sides during a Git-coupled pass.**
  Rejected: it makes the engine untestable without Git, couples product logic to
  a process-invoking front-end, and prevents the corpus from exercising the same
  engine the production flows use.
- **Edit the corpus to match the engine.** Rejected per ADR-0003: a corpus
  edited to meet the engine measures nothing. Variants realize the declared
  pre-change side without touching any declared expectation.
- **A fuzzy/similarity rename scorer.** Rejected: it would let a heuristic
  masquerade as a deterministic finding and would directly violate c020's
  forbidden claim.
- **Emit evidence for every impact edge.** Rejected: it would inflate
  `predicted_evidence_count`, depress `valid_evidence_rate` below the 100% gate,
  and serve no product purpose — impact edges are graph facts with derivations,
  not citable definitions.
- **YAML rules.** Rejected for the dependency reason above; TOML is stdlib and
  the rule file is small and structured.
- **A breaking `contract_version` bump for the change report.** Rejected: the
  report is a new additive schema; existing consumers are unaffected and
  `contract_version` stays `"1.0"`.

## Consequences

- The change engine is unit-testable against directories and integration-testable
  against real Git repos; the Git surface stays thin.
- Bumping `PARSER_BUNDLE_VERSION` and `RESOLVER_VERSION` in P4-SETUP, ahead of
  the P4-05 behavior that justifies the bump, follows the Phase 3 precedent:
  no released snapshot carries the new version with old behavior, because no
  user indexes between the uncommitted task handoffs.
- Route-literal and document-mention derivation (P4-05) adds edges to the
  `mixed_app` and `docs_config` fixtures only; query-side metrics will move,
  and the deltas are reported honestly in P4-10. No fixture outside those two
  gains edges (a noise budget of zero, asserted by test).
- `finding_precision` rewards minimalism: the rule table fires only what it
  proves, and aspirational observations go in report sections or limitations.
- Migration `0007` is forward-only; rollback is restoring the database from a
  pre-migration copy or deleting it and re-indexing.

## Security and Privacy

`GitDiffAdapter` is the second place CodeAtlas launches a process while holding
untrusted repository paths (the first being `GitAdapter`). The same controls
apply: argument arrays, `cwd` selection, no prompting, read-only commands,
timeouts, ref validation, path containment. No repository code is executed
during analysis; parsing is data-only, as in every prior phase. Rule files are
untrusted repository content and are validated strictly. Base-side evidence
never leaves the workstation; the local-first contract is unchanged. SARIF and
Markdown renderers escape repository text, which cannot break out of a code fence
or inject JSON structure.

## Migration and Rollback

Forward: P4-SETUP bumps the two version constants and adds the four error codes
and the additive contract models; P4-08 applies migration `0007`; P4-05 lands
the parser/resolver behavior that the version bumps anticipate. Each step's
handoff records current verification. A v6 database upgrades in place with rows
intact, proven by an upgrade-preservation test in P4-08. There is no schema
downgrade; revert means restoring the database file or deleting it and
re-indexing. Because the bumped versions change `snapshot_id`, a re-index after
rollback rebuilds cleanly rather than colliding with Phase 4 rows. The contract
addition is additive, so a client written against Phase 3 keeps working against
a Phase 4 backend that simply never populates `change_analysis_report`.

## Approval

Approved by the user on 2026-07-26 as part of the Phase 4 execution plan
(`docs/plans/phases/phase-04-change-assurance.md`), after being shown the plan
summary and the TOML-rules deviation. The approval instruction was **"I approved
phase 4 but first I just need to know any front end is there?"**; the plan as
written, including the decisions recorded above, is the scope approved. No
amendments were requested.