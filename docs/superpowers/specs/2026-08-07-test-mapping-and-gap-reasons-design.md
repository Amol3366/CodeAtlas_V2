# Fixture- and helper-mediated test mapping, with evidence-backed absence reasons

Status: approved design, not yet implemented
Date: 2026-08-07
Authority: `AGENTS.md` is the contract. This spec is subordinate to it.
Related: ADR-0003 (evidence granularity), ADR-0004 (relation model), and the
proposed ADR-0016 described in Section 10.

## 1. Why

CodeAtlas already answers "what did I change and what does it reach". It answers
"which tests does that reach" more narrowly than the repository actually
supports, and it says nothing at all about *why* a test link is absent.

`_derive_test_edges` (`src/codeatlas/extraction/resolution.py:660`) emits a
`TESTS` edge only where a test symbol both imports and calls the target. That bar
is defensible and is why the edge earns `high_confidence_heuristic`. It is also
why a pytest fixture that constructs the object under test makes the test
invisible: the test never imports the target and never calls it.

The consequence reaches the user. `_test_gaps` (`src/codeatlas/analysis/impact.py:459`)
reports every changed code symbol that no `TESTS` edge reaches. A
fixture-mediated symbol lands in that list, indistinguishable from a symbol no
test mentions anywhere. Both render as a bare name.

This work closes both halves with one mechanism. Evaluating a candidate test
relationship produces a verdict; today every verdict except "qualified" is
discarded. Retaining the near-misses yields new lower-confidence edges *and* the
reason a gap exists, because they are the same computation.

### The governing principle

**A weak edge explains a gap rather than closing it.**

A fixture-mediated link is reported as an impact edge carrying
`low_confidence_heuristic`, and the symbol *stays* in `test_gaps` with that edge
cited as the reason. Nothing is laundered: an edge too weak to be coverage is
never silently promoted into coverage, and an edge too weak to close a gap is
still worth showing to a developer deciding what to run.

This is the reusable output of this slice. The Preflight screen, the PR Markdown
export, and the CLI impact view are all renderings of it.

## 2. Scope

**In scope.** Python only. Fixture-mediated and helper-mediated `TESTS` edges at
`low_confidence_heuristic`. Structured absence reasons for every test gap.
Surfacing both through impact expansion and the change-analysis report.

**Out of scope, deferred to later slices.** TypeScript/JavaScript `describe`/`it`
callback attribution. Doc-to-code (`DOCUMENTS`) strengthening. Mock and patch
string references. The Preflight web route. PR-ready Markdown export. CLI impact
UX.

**Out of scope, permanently.** Any claim that a symbol is tested or untested.
CodeAtlas does not execute tests (`AGENTS.md` Section 3.9). Every output here
describes what the relation graph shows, never what is covered. The disclaimer
already in `src/codeatlas/delivery/markdown_report.py:167` remains true and
remains mandatory.

## 3. Extraction — classifying fixtures

`SymbolKind.FIXTURE` is declared in `src/codeatlas/contracts.py:133` and reserved
in two consumers — `_UNTESTABLE_KINDS` (`src/codeatlas/analysis/impact.py:46`)
and `src/codeatlas/analysis/findings.py:63`. Nothing has ever emitted it. This
section finishes work the codebase already anticipated.

`_function_kind` (`src/codeatlas/parsing/python_parser.py:331`) gains decorator
awareness. It receives the function's decorator list and returns
`SymbolKind.FIXTURE` when a decorator's dotted name is `pytest.fixture` or
`fixture`, in either bare (`@pytest.fixture`) or called
(`@pytest.fixture(scope="session")`) form.

Matching reads the dotted name from the AST node, never the source text. A
comment or a string containing `pytest.fixture` must not classify anything.

**Branch order is deliberate and must not change.** The existing
`is_test_file and name.startswith("test_")` branch stays first. A function named
`test_*` that also carries a fixture decorator remains a `TEST`, because that is
what pytest collects it as. The fixture branch is evaluated only after that.

Nested functions and methods are unchanged: the `inside_class` branch already
returns before either test branch, and a fixture defined inside a class body is
out of scope for this slice.

### 3.1 The `conftest.py` classification gap

`_is_test_path` (`src/codeatlas/repositories/classification.py:150`) classifies a
file as `TEST_CODE` when it sits in a known test directory, or when its stem
starts with `test_`, ends with `_test`, or ends with `.spec` / `.test`. A
`conftest.py` at the repository root, or beside a package, matches none of these
and is classified `SOURCE_CODE`.

`_derive_test_edges` gates on `FileClassification.TEST_CODE`
(`src/codeatlas/extraction/resolution.py:690`). Fixtures in such a `conftest.py`
would therefore be invisible regardless of everything else in this design.

`_is_test_path` gains an exact-stem match on `conftest`.

This reclassifies files outside this feature's scope, so it is called out rather
than folded in silently. It gets a dedicated test asserting that a root
`conftest.py` classifies as `TEST_CODE` and that no other classification branch
changes. Reviewers should expect it in the diff.

## 4. Extraction — fixture consumption as references

`extract_python_references` (`src/codeatlas/extraction/python_relations.py:143`)
emits, for each `TEST`-kind function, one `SymbolReference` per injected
parameter.

- `kind` is the new `RelationKind.CONSUMES_FIXTURE`.
- `target_hint` is the parameter name as written.
- `module_hint` is empty — the syntax names no module.
- The line range is the function signature.
- `part` disambiguates parameters sharing a line, per the existing convention in
  `src/codeatlas/domain/relations.py:85`.

Excluded: `self` and `cls`; any parameter carrying a default, which pytest would
not inject; `*args` and `**kwargs`.

### 4.1 Why `CONSUMES_FIXTURE` is a stored relation kind

`resolution.py` dispatches on the reference's `RelationKind`. A reference that
carries no kind of its own has nowhere to be routed, so the join in Section 5
would have to be computed by re-deriving fixture consumption inside the resolver
— duplicating extraction logic in a module whose job is resolution.

The kind is **intermediate**. It is recorded in the graph and cited as evidence,
but it is excluded from impact expansion and is never rendered as a finding. It
exists so the join has something to join on and so an absence reason can point at
a real stored edge rather than an inference.

The cost is acknowledged: this puts a Python-test-framework concept into an
otherwise language-neutral enum. Accepted deliberately, because the alternative
puts extraction logic in the resolver, and a duplicated derivation that two
modules can disagree about is the worse failure.

Adding an enum member is additive. `contract_version` stays `1.1`.

## 5. Resolution — two new derivation passes

Both passes run after `_derive_test_edges`. Both emit `RelationKind.TESTS` at
`Derivation.LOW_CONFIDENCE_HEURISTIC`.

**Neither pass ever upgrades or replaces an existing edge.** If the strict
import-and-call pass already produced `TESTS(test → target)` for a pair, both
passes skip that pair. A strong edge is never rewritten by a weak one.

Both reuse the seen-set and dedup discipline already in `_derive_test_edges`.

### 5.1 Fixture-mediated

For each `CONSUMES_FIXTURE(test → name)`:

1. Resolve `name` to a `SymbolKind.FIXTURE` symbol, searching the test's own
   file first, then any `conftest.py` in an ancestor directory of the test file.
   Nearest ancestor wins; ties break on sorted path for determinism.
2. For each `CALLS` edge from that fixture to a target symbol in a non-test
   file, emit `TESTS(test → target)`.

   `CALLS` covers construction as well as invocation: a fixture building the
   object under test emits `CALLS` against the class name. There is no
   `INSTANTIATES` member in `RelationKind` (`src/codeatlas/contracts.py:141`)
   and this design does not add one.

Unresolved parameter names produce no edge and no error. A test parameter that
names no fixture in scope is ordinary — it may come from a plugin — and is not a
defect to report.

**Scoping is deliberately partial.** pytest's real resolution includes plugins,
`usefixtures`, dynamic registration, and package-level scoping rules this design
does not model. Partial scoping over-matches rather than under-matches, and
over-matching at `low_confidence_heuristic` — where an edge cannot close a test
gap — is the safe direction to be wrong in.

### 5.2 Helper-mediated

For each `SymbolKind.TEST` symbol:

1. Walk `CALLS` one hop to a function in a file classified `TEST_CODE`.
2. Walk `CALLS` one further hop from that helper to a target in a non-test file.
3. Emit `TESTS(test → target)`.

**Depth is fixed at one intermediate hop and is not configurable.** Two hops
through shared test utilities reaches a large fraction of any codebase, which
would make the signal worthless rather than merely weak.

## 6. Contract — absence reasons

`test_gaps: list[NonEmptyText]` (`src/codeatlas/contracts.py:502`) is unchanged
in name, type, and meaning. A new sibling field is added to
`ChangeAnalysisReport`:

```python
test_gap_reasons: list[GapReason] = Field(default_factory=list)
```

```python
class GapReason(ContractModel):
    qualified_name: NonEmptyText
    reason: GapReasonCode
    explanation: NonEmptyText
    evidence_ids: list[NonEmptyText] = Field(default_factory=list)
```

| `GapReasonCode` | Meaning |
| --- | --- |
| `NO_TEST_FILE_REFERENCE` | No test file imports or calls this symbol |
| `IMPORTED_NOT_CALLED` | A test imports it but never exercises it |
| `CALLED_NOT_IMPORTED` | A test calls the name without importing it — likely a different symbol |
| `FIXTURE_MEDIATED_ONLY` | Reached only through a fixture; a candidate, not coverage |
| `HELPER_MEDIATED_ONLY` | Reached only through a test helper |

There is no `TARGET_NOT_TESTABLE` code. A symbol whose kind is in
`_UNTESTABLE_KINDS` is skipped before it can become a gap
(`src/codeatlas/analysis/impact.py:474`), so it never needs explaining. Every
reason code describes a symbol that *is* in `test_gaps`.

`evidence_ids` cite the near-miss edges that justify the reason:
`FIXTURE_MEDIATED_ONLY` cites the fixture edge, `IMPORTED_NOT_CALLED` cites the
import. `NO_TEST_FILE_REFERENCE` cites nothing, because
there is nothing to cite — an absence of evidence is reported as an absence, not
dressed in a citation.

Exactly one reason is assigned per gap. Where a symbol qualifies for several,
the first match in this precedence order wins:

1. `FIXTURE_MEDIATED_ONLY`
2. `HELPER_MEDIATED_ONLY`
3. `IMPORTED_NOT_CALLED`
4. `CALLED_NOT_IMPORTED`
5. `NO_TEST_FILE_REFERENCE` — the fallback when no other match applies.

The order runs from the strongest near-miss to the weakest, so the reason names
the closest thing to coverage that was actually found.

The addition is purely additive. `contract_version` stays `1.1` and a client
written against Phase 4 continues to work against the new response.

### 6.1 A behavioral consequence to expect

Once fixtures classify as `SymbolKind.FIXTURE`, a changed fixture stops appearing
in `test_gaps` entirely, because `_UNTESTABLE_KINDS` already excludes that kind.
This is a correct improvement — "is this fixture tested" is not a question that
applies — and it will move measured numbers. See Section 8.

## 7. Impact integration

New edges enter impact expansion carrying their derivation, so a fixture-mediated
test is reported as a test the developer should probably run, with
`low_confidence_heuristic` visible on it.

The existing depth-1 restriction on `TESTS` propagation
(`src/codeatlas/analysis/impact.py:403-409`) applies unchanged. A weak edge gets
no additional reach.

`RelationKind.CONSUMES_FIXTURE` is excluded from expansion. It is an extraction
intermediate, not a dependency.

`_test_gaps` (`src/codeatlas/analysis/impact.py:459`) returns names and reasons
together. Its current membership test —
`any(relation.kind is RelationKind.TESTS ...)` at line 481 — becomes a
derivation-aware classification that distinguishes a qualifying edge from a weak
one. That single check is the entire behavioral change in the function; the
`_UNTESTABLE_KINDS` and `DELETED` guards above it are unchanged.

## 8. Staleness and reindexing

`RESOLVER_VERSION` (`src/codeatlas/extraction/resolution.py:59`) moves
`1.1.0` → `1.2.0`. That invalidates derived-row reuse
(`src/codeatlas/application/indexing.py:478`), so relations recompute on the next
index rather than being copied forward.

**No schema migration.** `RelationRecord` already carries `derivation`, and no
table changes. `SCHEMA_VERSION` stays 14.

A version bump does not reindex anything by itself. An existing snapshot keeps
its old relations until the user reindexes, which means it will report gaps the
new resolver would explain. A change analysis run against a snapshot whose
`resolver_version` predates the bump therefore adds a **limitation** to the
report stating that test-gap data came from an older resolver and may overstate
gaps.

Reporting stale results without saying so is the failure mode this product exists
to prevent. The limitation is not optional polish.

## 9. Testing

**Unit.** Fixture decorator recognition, including bare and called forms, dotted
and bare names, a `test_*` function carrying a fixture decorator (stays `TEST`),
and a string or comment containing `pytest.fixture` (classifies nothing).
Parameter extraction including the `self`/`cls`, defaulted, and `*args`/`**kwargs`
exclusions. Fixture scope resolution including nearest-ancestor precedence and
the sorted-path tie-break. Helper-mediated one-hop walking, and a two-hop chain
that must produce nothing.

**Classification.** A root `conftest.py` classifies as `TEST_CODE`; a
`conftest.py` beside a package classifies as `TEST_CODE`; no other classification
branch changes behavior.

**Integration.** A fixture repository containing a root `conftest.py`, a
package-level `conftest.py`, a fixture-consuming test, a helper-mediated test, a
strictly import-and-call tested symbol, and a symbol no test references. Asserts
the edge set, the derivations on those edges, and the reason assigned to each
gap. Per `documentation/rules.md`, SQLite, parsers, and application services are
real here; only external boundaries may be mocked.

**Contract.** `test_gaps` unchanged in type and content semantics.
`test_gap_reasons` present and additive. `contract_version` still `1.1`. A
response deserializes against the Phase 4 client shape.

**Precedence.** A pair reachable both strictly and through a fixture keeps its
`high_confidence_heuristic` edge and is not duplicated, and does not appear in
`test_gaps`.

**Mutation checks.** Much of this changes behavior that currently produces
nothing, so new tests may pass on first run for the wrong reason. Each new
invariant is mutation-checked before it is trusted — the practice recorded in
`documentation/memory.md` after the `POST /v1/models/test` work, where a security
test passed against a deliberately leaking resolver because the leak path never
executed.

## 10. Evaluation and gate metrics

This changes measured behavior. New impact edges enlarge reported blast radius,
and fixtures leaving the gap list changes the gap counts.

Phase 4's recorded numbers — changed-symbol recall 1.0000, direct-impact recall
1.0000, finding precision 1.0000 across 24 cases, unsupported-claim rate 0.0000 —
are gate evidence approved by the user on 2026-07-27. Per `documentation/rules.md`,
**they are not edited.**

The evaluation is re-run and the new numbers are recorded as a new artifact under
`docs/evaluation/`, stating the delta against the Phase 4 baseline and explaining
each movement.

If direct-impact precision drops, that is reported as a finding. It is not
resolved by weakening the passes until the number recovers. Whether it drops is
not predictable from the design and is expected to be discovered during
implementation.

The unsupported-claim rate must stay at 0.0000. A `low_confidence_heuristic` edge
is a labeled candidate, not a claim, so this design should not move it — and if
it does, that indicates a labeling defect rather than an acceptable cost.

## 11. ADR-0016

Extends ADR-0004's relation model with:

1. A new `RelationKind` (`CONSUMES_FIXTURE`) that is intermediate — stored and
   citable, excluded from impact expansion.
2. Derivation-tiered `TESTS` edges, where the same relation kind carries
   different confidence depending on how it was derived.
3. The governing principle: **a weak edge explains a gap rather than closing
   it.**

Point 3 is the durable part. The Preflight screen, PR Markdown export, and CLI
impact view are renderings of it, and it is the claim that distinguishes
CodeAtlas from tools that resolve ambiguity silently in one direction or the
other.

## 12. Definition of done

- `SymbolKind.FIXTURE` is emitted; `conftest.py` classifies as `TEST_CODE`.
- Both derivation passes produce `TESTS` edges at `low_confidence_heuristic`,
  never overwriting a strict edge.
- `test_gap_reasons` is populated for every entry in `test_gaps`.
- A weak edge appears in impact with its derivation and does **not** remove its
  symbol from `test_gaps`.
- `RESOLVER_VERSION` is `1.2.0`; a stale-resolver snapshot reports a limitation.
- `contract_version` is `1.1` and `SCHEMA_VERSION` is 14, both unchanged.
- The full quality gate passes, with commands, exit codes, and output recorded.
- Evaluation re-run, new artifact written, deltas explained, Phase 4 baseline
  untouched.
- ADR-0016 written and accepted.
- `documentation/memory.md` updated and a handoff appended to
  `docs/plans/PLAN.md`.
