# `related_tests` must not assert coverage it cannot show

Date: 2026-08-08
Status: approved, not yet implemented

## The problem

ADR-0016 established that a `TESTS` edge derived through a fixture parameter or
a helper call is `low_confidence_heuristic`: it explains, it does not prove.
`impact` applies that rule. `related_tests` never had it applied.

`application/graph_queries.py:159` queries `kinds=(RelationKind.TESTS,)` with no
derivation filter, and the claim built at `graph_queries.py:395` reads:

```python
f"{other} {_verb(edge.kind)} {root.qualified_name}"
f" at {evidence.file_path}:{evidence.start_line}."
```

`_verb` maps `RelationKind.TESTS` to `"tests"`, so a fixture-mediated edge
produces:

> `test_total tests Order at tests/test_orders.py:7.`

Line 7 is `def test_total(store):` — a line that never mentions `Order`. The
sentence asserts coverage, and its own citation cannot show the relationship it
asserts.

This is **not** a contract bug. The `Claim` carries `derivation` and
`confidence` from the edge, which is the designated mechanism and is already
correct. The defect is entirely in the prose: a reader is told a fact, and the
evidence offered does not support it.

ADR-0016's consequences section discusses `impact` only and never mentions this
surface, so the omission was an accident rather than a decision.

## What changes

One place — the claim-text construction. A `TESTS` edge carrying a mediation
hint gets different wording:

| Case | Text |
| --- | --- |
| Strict | `test_direct tests unused_helper at tests/test_orders.py:24.` |
| Fixture | `test_total may exercise Order indirectly, through a fixture, at tests/test_orders.py:7.` |
| Helper | `test_via_helper may exercise total indirectly, through a helper, at tests/test_orders.py:15.` |

`derivation` and `confidence` are untouched. Response shape is untouched — no
new field, no `contract_version` change.

### Detection uses `module_hint`, not `derivation`

`_derive_fixture_test_edges` and `_derive_helper_test_edges`
(`extraction/resolution.py`) set `module_hint` to `FIXTURE_HINT` (`"<fixture>"`)
or `HELPER_HINT` (`"<helper>"`), documented there as recording "how this edge
was derived, so a gap reason can name it without re-deriving".

That is the correct discriminator here for two reasons. `derivation` is a
*strength* — it says how far to trust the edge, not how it was obtained — so it
cannot name the mediation, and any future edge assigned the same strength for an
unrelated reason would be swept in. `module_hint` says exactly which derivation
path produced the edge, which is precisely what the new wording states.

## Why the edge is kept rather than filtered

A fixture-mediated edge names a test worth running. Dropping it would return
"no tests recorded" for a symbol that several tests do reach, and the caller
could not distinguish "none exist" from "none strong enough" — silence that is
more misleading than a hedge.

ADR-0016's principle transfers directly: report it, cite it, label it, never
dress it as a fact it cannot support. The verb was the only thing lying.

## What is deliberately not fixed

The citation stays at the fixture-parameter line, which still does not show the
relationship. The sentence no longer claims that it does — "indirectly" is what
makes the mismatch legible instead of misleading.

Citing the line that *would* show it (the fixture definition in `conftest.py`)
is impossible from stored data: the derived edge sets
`file_id=relation.file_id` and `start_line=relation.start_line` from the
`CONSUMES_FIXTURE` relation, and stores neither the intermediate symbol's
identity nor its location. The fixture's name survives only inside
`relation_id` (`fixture:store:Order`), and recovering data by parsing an opaque
identifier is not an option — it would break the next time id construction
changes.

Fixing this properly means extending both derivation functions to carry the
intermediate hop, which bumps `RESOLVER_VERSION` `1.2.0` → `1.3.0` and makes
every existing snapshot stale until re-indexed. That cost was weighed and
scoped out; this spec buys the honesty without the reindex.

## Blast radius

Six call sites route to the same `services.graph.related_tests`:

- `api/routers/graph.py:59`, `api/routers/query.py:135`
- `cli/main.py:537`, `cli/main.py:599`
- `mcp/tools.py:269`, `mcp/tools.py:416`
- `conversations/pipeline.py:344`
- `evaluation/engine_adapter.py:63`

All of them consume the same application service, so one change reaches every
surface. This is the opposite of the `--format pr` defect, where each adapter
carried its own copy of a guard and the CLI's copy was missed.

Only `TESTS` edges with a mediation hint diverge. `_verb` keeps its behaviour
for every other relation kind.

## The evaluation-baseline risk, and how it is discharged

`QueryPrediction` (`evaluation/runner.py:54`) carries
`claims: list[NonEmptyText]`, and the scored metrics are computed from evidence
and claims. So changing claim prose *can* move `baseline-phase-3.json`, which
`check_phase4.ps1` verifies byte-for-byte.

It probably will not: the corpus almost certainly contains no fixture- or
helper-mediated scenario — that absence is exactly the gap the invariant corpus
was built to work around. But that is a prediction, not a plan.

**This is verified empirically before anything is committed**, by running
`run_phase3_baseline.py --check` and `run_phase4_baseline.py --check`:

- **Both pass** — the change is invisible to the corpus. Record that as a
  limitation, because it means the evaluation corpus cannot see this fix either,
  exactly as it could not see the gap-reason work.
- **Either moves** — stop and raise it. Regenerating a baseline is the project
  owner's standing call, not the implementer's.

## Testing

Unit tests at the claim-construction level:

1. A fixture-hinted `TESTS` edge produces "may exercise ... indirectly, through
   a fixture".
2. A helper-hinted `TESTS` edge says "through a helper".
3. **A strict `TESTS` edge keeps the plain "tests" verb.** Without this, a
   change that hedged every claim would pass every other test here.
4. A claim built from a hinted edge never contains the substring `" tests "`.
   That is the actual invariant, and the one a future refactor would break
   without noticing.
5. `derivation` and `confidence` on the claim are unchanged from the edge.

Each guard is mutation-checked: removing it must fail exactly the test that
covers it.

## Out of scope

No change to `RelationKind`, the resolver, `RESOLVER_VERSION`, `SCHEMA_VERSION`,
`contract_version`, the `QueryResponse` shape, or any other query method.
`related_documents` is untouched — `DOCUMENTS` edges are already excluded from
claims entirely (`graph_queries.py:374`) and travel as evidence only.

The invariant corpus is not extended: its checker runs `ChangeAnalysisEngine`
over two directories, while this surface needs a snapshot and a database. Unit
tests cover it instead, and the handoff records that this surface is guarded by
tests rather than by the corpus.

## Documentation

- `docs/adr/0016-derivation-tiered-test-edges.md` — record that the invariant
  applies to `related_tests` as well, and how; the consequences section
  currently names `impact` only
- No `docs/operations/` page documents `related_tests` output today, so none
  needs amending. The ADR is the record.
- `documentation/memory.md` — close the second recorded follow-up
- `docs/plans/PLAN.md` — appended handoff entry
