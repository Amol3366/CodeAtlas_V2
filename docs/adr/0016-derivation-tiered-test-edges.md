# ADR-0016: Derivation-Tiered Test Edges and the Fixture Relation

- Status: accepted
- Date: 2026-08-07
- Decision owners: user (feature plan approval), implementing agent (record)
- Supersedes: none
- Extends: ADR-0004 (relation model)

## Context

ADR-0004 fixed `TESTS` at exactly one derivation: `high_confidence_heuristic`,
emitted only when a `TEST_CODE` symbol both imports and calls the target. That
rule is precise but blind to two common pytest patterns:

1. A test function takes a fixture as a parameter; the fixture body (in the
   same file or `conftest.py`) is what actually imports and calls the target.
   The test never names the target directly.
2. A test calls a local helper function, and the helper is what calls the
   target.

Both patterns are real coverage a human reviewer would recognize instantly,
and both were previously invisible to `test_gaps`: the target symbol was
reported as untested with no indication that a near-miss existed one hop
away. The nine tasks preceding this one taught CodeAtlas to walk that one hop
and record what it finds — without ever promoting what it finds into a fact.

`conftest.py` also needed classification: it is test-support code, not a
symbol a change to production behavior should route around, but the
`TEST_CODE` classifier for the file has to actually mark it as such for
fixture-mediated edges to have a source at all. `SymbolKind.FIXTURE` was
declared in Phase 0 and never emitted; a `@pytest.fixture`-decorated function
is now recognized and classified with it.

Two things need deciding before later phases assume they are settled: what
kind of relation an "asked for this fixture" reference is, and what
confidence a `TESTS` edge should carry when it is inferred through that
reference or through a helper call rather than named directly.

## Decision

### 1. `CONSUMES_FIXTURE` is a new, intermediate relation kind

`RelationKind.CONSUMES_FIXTURE` records that a test function requested a
fixture by parameter name. It is:

- **Stored** — a first-class `RelationRecord`, `static_resolved` when the
  fixture name resolves to exactly one `FIXTURE` symbol in scope, subject to
  the same evidence and citation rules as every other relation.
- **Citable** — evidence exists and can be fetched like any other relation's;
  a `CONSUMES_FIXTURE` edge is not a synthetic bookkeeping row invisible to
  the rest of the system.
- **Excluded from impact expansion.** `src/codeatlas/analysis/impact.py`
  places it in `_NON_IMPACT_KINDS` beside the comment: "An extraction
  intermediate: it records which fixture a test asked for, not what depends
  on what. Following it would report a fixture name as blast radius."
  Walking it during a change-impact traversal would report a fixture's own
  name as if it were affected code, which is not what "impact" means.

This puts a concept specific to one test framework in one language —
pytest's parameter-name fixture injection — into a relation-kind enum that is
otherwise language- and framework-neutral (`CALLS`, `IMPORTS`, `INHERITS`).
That cost is accepted deliberately: the alternative, a generic
"parameter-mediated reference" kind, would have to be reverse-engineered from
this one concrete case with no second example to generalize from, and would
likely be wrong in ways only visible once a second framework is added. A
named, narrow kind that is honest about being pytest-shaped is preferable to
a falsely general one. If a comparable pattern appears in another framework
or language, `CONSUMES_FIXTURE` is the concrete precedent to generalize from,
not a design to imitate verbatim.

### 2. `TESTS` is now derivation-tiered, not derivation-fixed

ADR-0004 fixed `TESTS` at one derivation. That is no longer true:

| Derivation path | `derivation` | `confidence` |
| --- | --- | --- |
| Test symbol imports **and** calls the target directly | `high_confidence_heuristic` | high |
| Test symbol consumes a fixture that imports and calls the target | `low_confidence_heuristic` | low |
| Test symbol calls a helper that imports and calls the target | `low_confidence_heuristic` | low |

One relation kind (`TESTS`) now carries two confidence tiers depending on how
many indirection hops separate the test from the target, and which kind of
hop it is. This is consistent with `MAY_CALL` already existing beside `CALLS`
for ambiguity in ADR-0004: the relation kind names *what* the edge claims,
and derivation plus confidence name *how sure the claim is*, not a second
relation kind per confidence level. Recording indirect coverage as a
different relation kind (e.g., `MAY_TEST`) was considered and rejected — see
Alternatives.

Both indirect paths require the same two-sided check as the direct path
(import and call), just relocated to the fixture or helper body instead of
the test body itself. A fixture or helper that only imports, or only calls,
still leaves the target in `test_gaps`.

### 3. The governing principle: a weak edge explains a gap, it does not close it

This is the durable part of this decision, more durable than the specific
relation kind or confidence tiers above.

A `low_confidence_heuristic` `TESTS` edge is evidence that CodeAtlas *found
something* — a fixture or helper that plausibly reaches the target — not
evidence that the target *is tested*. Accordingly:

- The edge **appears in impact** — citable, walkable one hop like any
  `TESTS` edge, carrying its derivation so a consumer can see exactly how
  indirect it is.
- The symbol it points at **stays in `test_gaps`.** Nothing about finding a
  low-confidence path removes a symbol from the gap list.
- The gap now carries a `GapReason` (`GapReasonCode.FIXTURE_MEDIATED_ONLY` or
  `HELPER_MEDIATED_ONLY`) naming the near-miss and citing the weak edge as
  `evidence_ids`, so the gap report explains *why* coverage looks the way it
  does instead of reporting only its absence. `GapReasonCode` also names
  three direct-path failure modes (`IMPORTED_NOT_CALLED`,
  `CALLED_NOT_IMPORTED`, `NO_TEST_FILE_REFERENCE`) so every remaining gap,
  indirect or direct, carries a reason rather than silence.

Nothing is promoted from candidate to fact by this feature. A test suite
that only reaches a symbol through a fixture is, correctly, still reported
as not directly testing it — CodeAtlas now explains that more precisely
instead of describing it less accurately as "no relevant edge found at all."
`ContractModel` validation (`Task 7 Step 6`'s mutation-checked invariant)
enforces that this cannot regress silently: a `low_confidence_heuristic`
`TESTS` edge in impact without its symbol staying in `test_gaps` is treated
as a defect, not an acceptable simplification.

### 4. Version and schema effects

`RESOLVER_VERSION` moves `1.1.0` → `1.2.0`: resolution logic now derives
edges it did not derive before, so every snapshot resolved under the old
version is stale by the same reasoning ADR-0004 applied to its own
`RESOLVER_VERSION` bump. `contract_version` stays `"1.1"` — `GapReason` and
the `test_gap_reasons` field are additive and optional, breaking no existing
consumer. `SCHEMA_VERSION` stays `14` — no new table or column is required;
`CONSUMES_FIXTURE` and the new `TESTS` derivations are new *values*, not new
*shapes*, in already-migrated columns.

## Alternatives

- **A separate `MAY_TEST` relation kind for indirect coverage**, mirroring
  `CALLS`/`MAY_CALL`. Rejected: `MAY_CALL` exists because ambiguity is a
  property of *resolution* (which candidate?), whereas fixture- and
  helper-mediated coverage is a property of *derivation confidence*
  (how sure are we this edge means what it claims?). Confidence and
  derivation already carry that distinction for every other relation kind;
  adding a kind here would be inconsistent with how `DOCUMENTS` and
  `MAY_CALL` itself already separate resolution ambiguity from confidence
  tiering.
- **Silently dropping fixture/helper reach entirely**, leaving the prior
  Phase-3 behavior unchanged. Rejected: it is the status quo this feature
  was commissioned to improve, and it throws away information CodeAtlas can
  derive safely as long as it is labeled honestly.
- **Promoting fixture/helper-mediated coverage to `high_confidence_heuristic`
  and removing the symbol from `test_gaps`.** Rejected outright by the
  project owner's ruling that governs this whole feature: a weak edge
  explains a gap, it never closes it. One indirection hop is materially
  weaker evidence than a direct import-and-call, and conflating them would
  let a heuristic masquerade as near-direct evidence.
- **A generic "indirect-reference" relation kind** instead of naming
  `CONSUMES_FIXTURE` after pytest specifically. Rejected for the reasons in
  Decision §1: one concrete example does not justify a general abstraction,
  and a narrow, honestly-named kind is easier to reason about and easier to
  generalize from later than a premature generalization would be.

## Consequences

- Every snapshot resolved before this change is superseded on first re-index
  (`RESOLVER_VERSION` bump), same mechanism as every prior resolver-affecting
  ADR.
- `test_gaps` reports are more informative but not shorter: this feature
  changes *why* a gap is reported, not how many gaps exist for a suite with
  no fixture- or helper-mediated coverage at all. A suite that does use those
  patterns will see fewer "no signal found" gaps and more "found this,
  explained why it doesn't count" gaps — that is by design.
- `impact` output for a changed symbol reached only through a fixture or
  helper now includes a `low_confidence_heuristic` `TESTS` edge it did not
  include before. A consumer that filters findings by derivation class
  (per the derivation ladder in `documentation/architecture.md`) already has
  the mechanism to treat this appropriately; no new filtering capability is
  required, but consumers that previously assumed all `TESTS` edges were
  `high_confidence_heuristic` should stop doing so.
- `docs/evaluation/baseline-phase-4.json`/`.md` are Phase 4 gate evidence
  approved 2026-07-27 and are **not** edited or regenerated by this feature,
  per the project owner's explicit ruling. See
  `docs/evaluation/test-mapping-2026-08-07.md` for the re-measured numbers
  recorded beside that baseline; the delta, if any, is documented there
  rather than folded into the baseline file.
- `_NON_IMPACT_KINDS` in `impact.py` now has two purposes to keep straight:
  excluding purely structural kinds (`CONTAINS`, `EXPORTS`) from blast-radius
  walks, and excluding extraction intermediates (`CONSUMES_FIXTURE`) from the
  same walk for a different reason. Both share the set today; a future kind
  added to either category should re-read the adjacent comment before
  assuming the same exclusion reasoning applies.

## Security and Privacy

No change. `CONSUMES_FIXTURE` extraction is a pure function of one file's
tree-sitter/`ast` parse, matching every other relation extraction; no new I/O,
network access, or execution of repository code is introduced. Evidence for
the new edges follows the existing `evidence` table contract (identifiers,
line range, content hash, derivation — never the excerpt).

## Migration and Rollback

Forward: no schema migration. `SCHEMA_VERSION` stays `14`. The
`RESOLVER_VERSION` bump invalidates prior snapshots through the existing
`snapshot_id` mechanism (ADR-0004 §2); a full re-index picks up the new
derivations with no manual migration step. `change_analysis.py`'s
resolver-staleness guard (Task 6 of this plan) reports a limitation rather
than a silent under-count when it detects a snapshot older than the current
`RESOLVER_VERSION`.

Rollback: revert the code change and re-index; the resolver version reverts
with it and `TESTS`/`CONSUMES_FIXTURE` edges derived under `1.2.0` are
superseded the same way any snapshot is superseded on version change. No
schema downgrade is needed because none was applied.

## Approval

Approved by the user as part of the ten-task "test mapping and gap reasons"
feature plan
(`.superpowers/sdd/2026-08-07-test-mapping-and-gap-reasons/task-10-brief.md`),
which also carries the explicit ruling that the Phase 4 baseline files are
gate evidence from 2026-07-27 and are not to be edited or regenerated by this
work. The scope approved is the nine implementation tasks plus this
documentation task, as written.

## Enforcement

Gated by `tests/evaluation/invariant_cases/` and `scripts/check_invariants.py`,
run by `scripts/check_phase4.ps1`.

Verified by mutation: making `LOW_CONFIDENCE_HEURISTIC` qualify alongside
`HIGH_CONFIDENCE_HEURISTIC` in `_test_gaps` (`analysis/impact.py`) makes the
checker exit 7, naming `Order` and `total`.

The Phase 4 evaluation corpus cannot enforce this — it contains no fixture- or
helper-mediated case, so no metric there moves when the invariant breaks. That
is why the enforcement lives in a separate corpus rather than as an added
metric.
