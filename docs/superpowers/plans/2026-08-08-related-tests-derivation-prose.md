# `related_tests` Derivation Prose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `related_tests` rendering a fixture- or helper-mediated `TESTS` edge as an assertion of coverage.

**Architecture:** Extract the sentence-building decision out of the private `_claims` loop into a pure function, so it can be unit-tested without a database; branch inside it on `module_hint`.

**Tech Stack:** Python 3.12, Pydantic 2, pytest. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-08-related-tests-derivation-prose-design.md`
- No change to `RelationKind`, the resolver, `RESOLVER_VERSION` (`1.2.0`), `SCHEMA_VERSION` (`14`), `contract_version` (`1.1`), or the `QueryResponse` shape.
- `derivation` and `confidence` on a `Claim` must stay exactly what the edge carried.
- Detection is by `module_hint`, never by `derivation`.
- Line length 88 (ruff). Full strict mypy on `src`, `tests`, `scripts`, `apps`.
- Run everything with `uv run` **from the repository root**. A `cd` in one shell call persists into the next; a relative path run from the wrong directory fails silently rather than loudly.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/codeatlas/application/graph_queries.py` | Add pure `claim_text(...)`; call it from `_claims` |
| `tests/unit/test_claim_text.py` | Unit tests for the pure function |
| `docs/adr/0016-derivation-tiered-test-edges.md` | Record the second surface |
| `documentation/memory.md`, `docs/plans/PLAN.md` | Close the follow-up; handoff |

---

### Task 1: Extract the sentence, then change it

**Files:**
- Modify: `src/codeatlas/application/graph_queries.py` (the `_claims` loop, ~lines 368–406)
- Create: `tests/unit/test_claim_text.py`

**Interfaces:**
- Produces: `def claim_text(*, edge: RelationRecord, other: str, root_name: str, file_path: str, start_line: int, inbound: bool) -> str`

**Background.** The current sentence is built inline:

```python
text=(
    f"{other} {_verb(edge.kind)} {root.qualified_name}"
    f" at {evidence.file_path}:{evidence.start_line}."
    if inbound
    else (
        f"{root.qualified_name} {_verb(edge.kind)} {other}"
        f" at {evidence.file_path}:{evidence.start_line}."
    )
),
```

`_verb` maps `RelationKind.TESTS` to `"tests"`. `FIXTURE_HINT` (`"<fixture>"`)
and `HELPER_HINT` (`"<helper>"`) are set on derived edges' `module_hint` by
`_derive_fixture_test_edges` / `_derive_helper_test_edges` in
`extraction/resolution.py`, and are importable from
`codeatlas.domain.relations`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_claim_text.py`:

```python
"""The sentence a claim renders, and what it may not assert.

ADR-0016: a `TESTS` edge derived through a fixture parameter or a helper call
explains rather than proves. `impact` applied that rule; this surface did not,
and rendered such an edge as "X tests Y" while citing a line that never names
Y.
"""

from __future__ import annotations

import pytest

from codeatlas.application.graph_queries import claim_text
from codeatlas.contracts import Derivation, RelationKind
from codeatlas.domain.relations import (
    FIXTURE_HINT,
    HELPER_HINT,
    RelationRecord,
    ResolutionState,
)


def _edge(
    *,
    kind: RelationKind = RelationKind.TESTS,
    module_hint: str = "",
    derivation: Derivation = Derivation.HIGH_CONFIDENCE_HEURISTIC,
) -> RelationRecord:
    return RelationRecord(
        relation_id="rel_1",
        source_symbol_id="sym_test_total",
        target_symbol_id="sym_Order",
        file_id="file_1",
        kind=kind,
        target_hint="Order",
        resolution=ResolutionState.RESOLVED,
        derivation=derivation,
        confidence=0.5,
        start_line=7,
        end_line=7,
        candidate_count=1,
        module_hint=module_hint,
    )


def _text(edge: RelationRecord) -> str:
    return claim_text(
        edge=edge,
        other="test_total",
        root_name="Order",
        file_path="tests/test_orders.py",
        start_line=7,
        inbound=True,
    )


def test_a_strict_tests_edge_still_reads_as_a_test() -> None:
    # Without this, a change that hedged EVERY claim would satisfy every other
    # test in this file.
    text = _text(_edge())

    assert text == "test_total tests Order at tests/test_orders.py:7."


def test_a_fixture_mediated_edge_does_not_assert_coverage() -> None:
    text = _text(
        _edge(
            module_hint=FIXTURE_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "may exercise" in text
    assert "through a fixture" in text
    assert "indirectly" in text


def test_a_helper_mediated_edge_names_the_helper_path() -> None:
    text = _text(
        _edge(
            module_hint=HELPER_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "through a helper" in text


@pytest.mark.parametrize("hint", [FIXTURE_HINT, HELPER_HINT])
def test_a_mediated_claim_never_says_the_test_tests_the_symbol(
    hint: str,
) -> None:
    # The actual invariant, and the one a future refactor would break without
    # noticing. Any rewording is free as long as it does not reintroduce the
    # bare verb.
    text = _text(
        _edge(module_hint=hint, derivation=Derivation.LOW_CONFIDENCE_HEURISTIC)
    )

    assert " tests " not in text


def test_the_citation_is_still_present_on_a_mediated_claim() -> None:
    # The line does not show the relationship, but dropping it would leave the
    # claim uncitable, which is worse than citing a weak location honestly.
    text = _text(
        _edge(
            module_hint=FIXTURE_HINT,
            derivation=Derivation.LOW_CONFIDENCE_HEURISTIC,
        )
    )

    assert "tests/test_orders.py:7" in text


def test_a_hint_on_a_non_tests_edge_is_ignored() -> None:
    # `module_hint` is also used by document derivation. Only a TESTS edge may
    # be reworded, or an unrelated edge kind would start hedging.
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS, module_hint=FIXTURE_HINT),
        other="render",
        root_name="total",
        file_path="a.py",
        start_line=3,
        inbound=True,
    )

    assert text == "render calls total at a.py:3."


def test_an_outbound_claim_leads_with_the_root() -> None:
    text = claim_text(
        edge=_edge(kind=RelationKind.CALLS),
        other="helper",
        root_name="total",
        file_path="a.py",
        start_line=3,
        inbound=False,
    )

    assert text == "total calls helper at a.py:3."
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_claim_text.py -q`
Expected: FAIL — `cannot import name 'claim_text'`

If `RelationRecord` or `ResolutionState` are not importable from
`codeatlas.domain.relations`, find them with
`grep -rn "class RelationRecord" src/` and correct the import.

- [ ] **Step 3: Add the pure function**

Add to `src/codeatlas/application/graph_queries.py`, next to `_verb`. Import
`FIXTURE_HINT` and `HELPER_HINT` from `codeatlas.domain.relations` alongside
the existing imports from that module, and `RelationRecord` if not already
imported.

```python
# How a mediated `TESTS` edge was derived, in the words the sentence uses.
# Keyed on `module_hint` rather than `derivation`: a derivation is a strength,
# and a strength cannot name the path an edge came from. See ADR-0016.
_MEDIATION: Final[dict[str, str]] = {
    FIXTURE_HINT: "a fixture",
    HELPER_HINT: "a helper",
}


def claim_text(
    *,
    edge: RelationRecord,
    other: str,
    root_name: str,
    file_path: str,
    start_line: int,
    inbound: bool,
) -> str:
    """The sentence one claim renders.

    A `TESTS` edge reached through a fixture parameter or a helper call names a
    test worth running, but it cannot show that the test covers the symbol --
    its citation is the mediating line, which never mentions the target. So it
    is reported and cited, and worded so it does not assert what it cannot
    support.
    """
    citation = f" at {file_path}:{start_line}."
    mediation = (
        _MEDIATION.get(edge.module_hint)
        if edge.kind is RelationKind.TESTS
        else None
    )
    if mediation is not None:
        subject, obj = (other, root_name) if inbound else (root_name, other)
        return (
            f"{subject} may exercise {obj} indirectly,"
            f" through {mediation},{citation}"
        )

    if inbound:
        return f"{other} {_verb(edge.kind)} {root_name}{citation}"
    return f"{root_name} {_verb(edge.kind)} {other}{citation}"
```

Add `Final` to the `typing` import if it is not already there.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_claim_text.py -q`
Expected: PASS, 8 tests (the parametrized one counts twice).

- [ ] **Step 5: Call it from `_claims`**

Replace the inline `text=(...)` expression in the `_claims` loop with:

```python
                    text=claim_text(
                        edge=edge,
                        other=other,
                        root_name=root.qualified_name,
                        file_path=evidence.file_path,
                        start_line=evidence.start_line,
                        inbound=inbound,
                    ),
```

Leave `derivation=edge.derivation` and `confidence=edge.confidence` exactly as
they are — they were already correct and are not part of this defect.

- [ ] **Step 6: Prove nothing else changed**

```bash
uv run pytest tests/integration/test_graph_queries.py tests/contract/test_mcp_tools.py -q
```

Expected: PASS. These exercise real claims through a database and through MCP;
they contain no fixture-mediated edge, so every claim they assert on must read
exactly as before.

- [ ] **Step 7: Mutation-check the strict guard**

Temporarily delete the `if edge.kind is RelationKind.TESTS` condition, so the
mediation branch fires on any hinted edge:

```python
    mediation = _MEDIATION.get(edge.module_hint)
```

Run: `uv run pytest tests/unit/test_claim_text.py -q`
Expected: `test_a_hint_on_a_non_tests_edge_is_ignored` FAILS.

Restore it by re-editing the file — **not** with `git checkout`, which would
discard every uncommitted change in it. Re-run and confirm PASS.

- [ ] **Step 8: Lint, type-check, commit**

```bash
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
git add src/codeatlas/application/graph_queries.py tests/unit/test_claim_text.py
git commit -m "fix: stop related_tests asserting coverage it cannot show

A TESTS edge derived through a fixture parameter or a helper call cited a line
that never names the target, while the sentence read 'X tests Y'. The claim's
derivation and confidence were already correct; only the prose overclaimed.

Keyed on module_hint rather than derivation: a strength cannot name the path an
edge came from."
```

---

### Task 2: Discharge the evaluation-baseline risk

**Files:** none modified. This task is a verification gate.

`QueryPrediction` (`evaluation/runner.py:54`) carries `claims`, and the scored
metrics read them, so changed prose *can* move a tracked baseline.

- [ ] **Step 1: Run both baseline checks**

```bash
uv run python scripts/run_phase3_baseline.py \
  --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-3.json \
  --markdown-output docs/evaluation/baseline-phase-3.md --check
echo "phase3=$?"

uv run python scripts/run_phase4_baseline.py \
  --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-4.json \
  --markdown-output docs/evaluation/baseline-phase-4.md --check
echo "phase4=$?"
```

- [ ] **Step 2: Act on the result**

**Both exit 0** — expected. The corpus has no fixture- or helper-mediated case,
so this change is invisible to it. Record that in Task 3 as a limitation: it
means the evaluation corpus cannot see this fix either, the same blind spot the
invariant corpus was built to work around.

**Either is non-zero — STOP.** Do not regenerate a baseline. Report which one
moved and what the diff shows. Regenerating a tracked baseline is the project
owner's standing call, and this plan has no authority to make it.

---

### Task 3: Documentation and handoff

**Files:**
- Modify: `docs/adr/0016-derivation-tiered-test-edges.md`
- Modify: `documentation/memory.md`
- Modify: `docs/plans/PLAN.md`

- [ ] **Step 1: Record the second surface in the ADR**

The consequences section names `impact` only. Append to the `## Enforcement`
section added by the invariant-corpus work:

```markdown
### The second surface

`related_tests` (`application/graph_queries.py`) returns weak `TESTS` edges too.
It does not filter them — a fixture-mediated edge names a test worth running,
and returning silence would be more misleading than a hedge — but it no longer
renders them with the bare verb. A mediated edge reads "may exercise ...
indirectly, through a fixture", keyed on `module_hint` rather than `derivation`,
because a strength cannot name the path an edge came from.

Its citation remains the mediating line, which does not show the relationship.
Citing the fixture definition instead would require the resolver to store the
intermediate hop, bumping `RESOLVER_VERSION` and making every snapshot stale;
that was weighed and declined. The wording carries the imprecision instead.

Guarded by `tests/unit/test_claim_text.py`, not by the invariant corpus: that
checker runs `ChangeAnalysisEngine` over two directories, while this surface
needs a snapshot and a database.
```

- [ ] **Step 2: Close the follow-up in memory**

In `documentation/memory.md`, follow-up 2 (`related_tests` is a second surface
the invariant was never applied to) is now closed. Rewrite it in the same shape
used for follow-up 1: strike the heading, mark it CLOSED 2026-08-08, and record
what was decided and why — that the edge is kept rather than filtered, that
detection is by `module_hint`, and that the weak citation was accepted rather
than paying a `RESOLVER_VERSION` bump and a full reindex.

- [ ] **Step 3: Append the handoff entry**

Prepend a dated entry to the `## Handoff Log` in `docs/plans/PLAN.md` (entries
run newest-first). Cover: what changed and where; that all six call sites route
through one application service so a single change reached every surface; the
baseline-check result from Task 2; the mutation verification; and the standing
limitation that the evaluation corpus cannot see this fix.

- [ ] **Step 4: Full verification**

```bash
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```

The suite takes roughly four minutes. Run it alone — two concurrent pytest runs
share `--basetemp=.test-tmp` and will corrupt each other's results.

- [ ] **Step 5: Commit**

```bash
git add docs documentation
git commit -m "docs: record related_tests as ADR-0016's second surface"
```

---

## Completion

After Task 3, use superpowers:finishing-a-development-branch.
