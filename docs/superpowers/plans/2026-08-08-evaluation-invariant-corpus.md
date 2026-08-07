# ADR-0016 Invariant Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the release gate a declarative corpus and checker that fails when a weak `TESTS` edge stops explaining a gap and starts closing one.

**Architecture:** A committed fixture tree (base + target) whose four changed symbols each reach the test suite by exactly one path; a JSON corpus declaring the expected `GapReasonCode` per symbol; a checker script that runs the real `ChangeAnalysisEngine` over it and writes committed result artifacts that must reproduce byte-for-byte.

**Tech Stack:** Python 3.12, Pydantic 2, pytest, PowerShell (gate script). No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-08-evaluation-invariant-corpus-design.md`
- `contract_version` stays `"1.1"`. The corpus carries its own independent `"1.0"`.
- No change to `ChangeCase`, `src/codeatlas/evaluation/runner.py`, the report model, or `docs/evaluation/baseline-phase-4.{json,md}`. Verified by empty diffs in Task 7.
- Artifacts must be byte-for-byte reproducible: no timings, no absolute paths, no wall-clock values, `sort_keys=True`, `newline="\n"`.
- `documentation/rules.md`: never log or emit an absolute local path. Artifact paths are corpus-relative only.
- A case the engine cannot run is a FAILURE, never a skip.
- Line length 88 (ruff). Full strict mypy on `src`, `tests`, `scripts`, `apps`.
- Run everything with `uv run` from the repository root.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `tests/evaluation/invariant_cases/cases.json` | The declarative expectations. Data, not code. |
| `tests/evaluation/invariant_cases/fixtures/orders/base/` | Pre-change tree |
| `tests/evaluation/invariant_cases/fixtures/orders/target/` | Post-change tree |
| `src/codeatlas/evaluation/invariants.py` | Corpus model, loader, and the check itself. Importable, so the pytest in Task 6 needs no subprocess. |
| `scripts/check_invariants.py` | Thin CLI boundary: argument parsing, artifact writing, exit codes. |
| `docs/evaluation/invariants.json` | Committed result artifact |
| `docs/evaluation/invariants.md` | Human reading of the same |
| `tests/unit/test_invariants.py` | Unit tests for the checker logic |
| `tests/integration/test_invariant_corpus.py` | Runs the real corpus in-process |
| `pyproject.toml` | Three exclusions for the fixture tree |
| `scripts/check_phase4.ps1` | Gate step |

The logic lives in `src/`, not in `scripts/`, matching how `run_phase4_baseline.py` delegates to `codeatlas.evaluation.*`. A script that holds its own logic cannot be unit-tested without a subprocess.

---

### Task 1: Prove the engine-direct path reproduces the gap reasons

**This task is a spike and must come first.** Everything else assumes that
calling the engine with two `DirectoryStateView`s produces the same gap reasons
that `test_fixture_test_mapping.py` gets through the full pipeline (Git, SQLite,
indexer). That is likely — `predict_changes` already gets real relations this
way — but it is the one genuine unknown, and if it is false the whole approach
changes.

**Files:**
- Create: `tests/evaluation/invariant_cases/fixtures/orders/base/src/orders.py`
- Create: `tests/evaluation/invariant_cases/fixtures/orders/base/conftest.py`
- Create: `tests/evaluation/invariant_cases/fixtures/orders/base/tests/conftest.py`
- Create: `tests/evaluation/invariant_cases/fixtures/orders/base/tests/test_orders.py`
- Create: the same four files under `fixtures/orders/target/`

**Interfaces:**
- Produces: a committed fixture tree at `tests/evaluation/invariant_cases/fixtures/orders/{base,target}/`, and the confirmed fact that `Order`, `total`, `unused_helper`, `audit` are the qualified names the engine reports.

**Background — why the source looks like this.** These shapes are lifted from
`tests/integration/test_fixture_test_mapping.py`, where they are already proven
to produce one distinct gap reason each. The comments are not decoration; each
one records a way the fixture silently collapses into the wrong reason. Carry
them verbatim.

- [ ] **Step 1: Write the base source tree**

`fixtures/orders/base/src/orders.py`:

```python
class Order:
    def __init__(self):
        self.amount = 0


def total(order):
    return order.amount


def unused_helper():
    return 0


def audit():
    return "ok"
```

`fixtures/orders/base/conftest.py`:

```python
# `import orders` + `orders.Order()` rather than `from orders import Order`:
# the strict import-and-call pass matches an IMPORTS relation's target symbol
# against a CALLS target in the same file. A module import only names the
# module as imported, not `Order` itself, so this fixture cannot accidentally
# satisfy the strict pass on its own -- it only produces the CALLS edge that
# the fixture-mediation pass follows.
import pytest

import orders


@pytest.fixture
def store():
    return orders.Order()
```

`fixtures/orders/base/tests/conftest.py`:

```python
import pytest


@pytest.fixture
def clock():
    return 0
```

`fixtures/orders/base/tests/test_orders.py`:

```python
# Imports are deliberately *local* to each function rather than shared at
# module scope. A shared top-level import would be visible to every test in
# the file, and then any test that merely calls the corresponding helper would
# look like it both imports and calls the symbol directly, collapsing
# helper-mediated into strict.
def test_total(store):
    assert store is not None


def _build():
    # `import orders` + `orders.total(...)`, for the same reason as the root
    # fixture above: it must produce a CALLS edge without also satisfying the
    # strict import-and-call pass on `_build` itself.
    import orders

    return orders.total({'amount': 1})


def test_via_helper():
    _build()


def test_direct():
    from orders import unused_helper

    assert unused_helper() == 0
```

Note there is no test reference to `audit` anywhere. That absence is what
produces `NO_TEST_FILE_REFERENCE`, so do not add one.

- [ ] **Step 2: Write the target tree**

Copy all four base files to `fixtures/orders/target/` unchanged, then replace
only `target/src/orders.py` with the version below. Every symbol's body must
differ from base, or the engine will not see it as changed and it can never
become a gap.

```python
class Order:
    kind = 'sales'

    def __init__(self):
        self.amount = 0


def total(order):
    return order.amount + 1


def unused_helper():
    return 1


def audit():
    return "changed"
```

- [ ] **Step 3: Confirm the engine reports what we expect**

Run this throwaway probe (do not commit it):

```bash
uv run python -c "
from pathlib import Path
from codeatlas.analysis.engine import ChangeAnalysisEngine
from codeatlas.analysis.state import DirectoryStateView
root = Path('tests/evaluation/invariant_cases/fixtures/orders')
r = ChangeAnalysisEngine().analyze(
    DirectoryStateView(root / 'base'), DirectoryStateView(root / 'target')
)
print('gaps:', sorted(r.impact.test_gaps))
for x in r.impact.test_gap_reasons:
    print(' ', x.qualified_name, x.reason)
"
```

Expected:

```text
gaps: ['Order', 'audit', 'total']
  Order FIXTURE_MEDIATED_ONLY
  total HELPER_MEDIATED_ONLY
  audit NO_TEST_FILE_REFERENCE
```

`unused_helper` must be absent from `gaps` — it is the control.

**If `DirectoryStateView` is not importable from `codeatlas.analysis.state`,
find it with:** `uv run python -c "import codeatlas.evaluation.engine_adapter as m; print(m.DirectoryStateView.__module__)"`

**STOP AND REPORT if the output differs.** Do not adjust the expectations to
match the output — that would bake whatever the engine currently does into a
corpus meant to constrain it. Report the difference and wait.

- [ ] **Step 4: Commit**

```bash
git add tests/evaluation/invariant_cases/fixtures
git commit -m "test: add the invariant corpus fixture tree

One tree, four changed symbols, each reachable by exactly one path, so the
four gap reasons must discriminate between each other in a single engine run.
Source shapes and their comments are carried from the integration test that
proved them."
```

---

### Task 2: Exclude the fixture tree from pytest, ruff, and mypy

**Files:**
- Modify: `pyproject.toml`

The tree contains `test_*.py` files and deliberately minimal untyped code.
Without all three exclusions the real suite collects the fixture tests, lint
fails, and strict mypy fails. Do this before writing any code so later tasks
get honest tool output.

- [ ] **Step 1: Verify the problem exists first**

```bash
uv run pytest -q --collect-only 2>&1 | grep -c invariant_cases
```

Expected: a non-zero count. If it is 0, report — the exclusion may already be
implied by a pattern and the edits below would be dead configuration.

- [ ] **Step 2: Add the three exclusions**

In `[tool.pytest.ini_options] norecursedirs`, `[tool.ruff] exclude`, and
`[tool.mypy] exclude`, add this entry alongside the existing four pairs:

- pytest and ruff: `"tests/evaluation/invariant_cases/fixtures"`
- mypy: `"tests/evaluation/invariant_cases/fixtures/"` (mypy's existing
  entries carry a trailing slash; match them)

- [ ] **Step 3: Verify all three are quiet**

```bash
uv run pytest -q --collect-only 2>&1 | grep -c invariant_cases   # expect 0
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```

All three must pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: treat the invariant fixture tree as data

pytest would collect its test files into the real suite, and ruff and mypy
would check code written to be minimal rather than correct."
```

---

### Task 3: The corpus model and loader

**Files:**
- Create: `src/codeatlas/evaluation/invariants.py`
- Create: `tests/unit/test_invariants.py`
- Create: `tests/evaluation/invariant_cases/cases.json`

**Interfaces:**
- Consumes: `ContractModel` from `codeatlas.contracts`, `GapReasonCode` from `codeatlas.contracts`
- Produces:
  - `class InvariantCase(ContractModel)` with fields `id: str`, `invariant: str`, `fixture: str`, `expect_gap_reasons: dict[str, GapReasonCode]`, `expect_not_gaps: list[str]`
  - `class InvariantCorpus(ContractModel)` with `contract_version: Literal["1.0"]`, `cases: list[InvariantCase]`
  - `class InvariantCorpusError(Exception)`
  - `def load_corpus(directory: Path) -> InvariantCorpus`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_invariants.py`:

```python
"""The ADR-0016 invariant corpus: its model, and the check it drives."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas.contracts import GapReasonCode
from codeatlas.evaluation.invariants import (
    InvariantCorpusError,
    load_corpus,
)


def _write(directory: Path, payload: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cases.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return directory


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "i001",
        "invariant": "a fixture-mediated symbol stays a gap",
        "fixture": "orders",
        "expect_gap_reasons": {"Order": "FIXTURE_MEDIATED_ONLY"},
        "expect_not_gaps": [],
    }
    case.update(overrides)
    return case


def test_a_corpus_round_trips(tmp_path: Path) -> None:
    directory = _write(
        tmp_path, {"contract_version": "1.0", "cases": [_case()]}
    )

    corpus = load_corpus(directory)

    assert corpus.cases[0].id == "i001"
    assert corpus.cases[0].expect_gap_reasons["Order"] is (
        GapReasonCode.FIXTURE_MEDIATED_ONLY
    )


def test_an_unknown_reason_code_is_refused(tmp_path: Path) -> None:
    # A typo in a reason code must not silently become an expectation that
    # can never fail.
    directory = _write(
        tmp_path,
        {
            "contract_version": "1.0",
            "cases": [_case(expect_gap_reasons={"Order": "FIXTURE_ONLY"})],
        },
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_an_unknown_field_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        {"contract_version": "1.0", "cases": [_case(expect_coverage=True)]},
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_a_missing_corpus_is_an_error_not_an_empty_pass(tmp_path: Path) -> None:
    # An empty corpus would report "all invariants held" having checked none.
    with pytest.raises(InvariantCorpusError):
        load_corpus(tmp_path / "absent")


def test_a_corpus_with_no_cases_is_refused(tmp_path: Path) -> None:
    directory = _write(tmp_path, {"contract_version": "1.0", "cases": []})

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_a_case_asserting_nothing_is_refused(tmp_path: Path) -> None:
    # Both expectation fields empty means the case cannot fail.
    directory = _write(
        tmp_path,
        {
            "contract_version": "1.0",
            "cases": [_case(expect_gap_reasons={}, expect_not_gaps=[])],
        },
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)


def test_duplicate_case_ids_are_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path, {"contract_version": "1.0", "cases": [_case(), _case()]}
    )

    with pytest.raises(InvariantCorpusError):
        load_corpus(directory)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: FAIL — `ModuleNotFoundError: codeatlas.evaluation.invariants`

- [ ] **Step 3: Implement the model and loader**

`src/codeatlas/evaluation/invariants.py`:

```python
"""The ADR-0016 invariant corpus.

The Phase 4 evaluation corpus measures how accurate change assurance is --- a
number that legitimately moves. This corpus asserts one boolean that must not:
a weak `TESTS` edge explains a gap rather than closing it. Keeping them apart
is why the Phase 4 baseline is untouched by this feature.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from codeatlas.contracts import ContractModel, GapReasonCode


class InvariantCorpusError(Exception):
    """The corpus could not be read, or does not assert anything."""


class InvariantCase(ContractModel):
    """One scenario and what must be true of it."""

    id: str
    invariant: str
    fixture: str
    # Qualified name -> the reason that name must be reported with. Both
    # halves are asserted: membership in `test_gaps` AND the reason. Checking
    # membership alone would pass if every reason collapsed to one constant.
    expect_gap_reasons: dict[str, GapReasonCode] = Field(default_factory=dict)
    # Names that must NOT be gaps. Without this, a bug making every symbol a
    # permanent gap would satisfy every other assertion in the corpus.
    expect_not_gaps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_asserts_something(self) -> InvariantCase:
        if not self.expect_gap_reasons and not self.expect_not_gaps:
            raise ValueError(
                f"case {self.id} asserts nothing and can never fail"
            )
        return self


class InvariantCorpus(ContractModel):
    """Every invariant case, and the fixture root they resolve against."""

    contract_version: Literal["1.0"] = "1.0"
    cases: list[InvariantCase]
    # Not serialized: it is where the corpus was loaded from, not part of it.
    root: Path = Field(default=Path("."), exclude=True)

    @model_validator(mode="after")
    def validate_cases(self) -> InvariantCorpus:
        if not self.cases:
            raise ValueError(
                "an empty corpus would report that every invariant held"
                " having checked none"
            )
        identifiers = [case.id for case in self.cases]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("case ids must be unique")
        return self


def load_corpus(directory: Path) -> InvariantCorpus:
    """Read `cases.json` from `directory`."""
    path = directory / "cases.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvariantCorpusError(f"cannot read corpus: {error}") from error
    try:
        corpus = InvariantCorpus.model_validate(payload)
    except ValidationError as error:
        raise InvariantCorpusError(f"invalid corpus: {error}") from error
    return corpus.model_copy(update={"root": directory})
```

If `ContractModel` is not exported from `codeatlas.contracts`, find it with
`grep -rn "class ContractModel" src/` and import from there.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 5: Write the corpus data**

`tests/evaluation/invariant_cases/cases.json`:

```json
{
  "contract_version": "1.0",
  "cases": [
    {
      "id": "i001",
      "invariant": "a fixture-mediated symbol is explained, not covered",
      "fixture": "orders",
      "expect_gap_reasons": { "Order": "FIXTURE_MEDIATED_ONLY" },
      "expect_not_gaps": []
    },
    {
      "id": "i002",
      "invariant": "a helper-mediated symbol is explained, not covered",
      "fixture": "orders",
      "expect_gap_reasons": { "total": "HELPER_MEDIATED_ONLY" },
      "expect_not_gaps": []
    },
    {
      "id": "i003",
      "invariant": "a strict import-and-call edge still closes a gap",
      "fixture": "orders",
      "expect_gap_reasons": {},
      "expect_not_gaps": ["unused_helper"]
    },
    {
      "id": "i004",
      "invariant": "an unreferenced symbol reports bare absence",
      "fixture": "orders",
      "expect_gap_reasons": { "audit": "NO_TEST_FILE_REFERENCE" },
      "expect_not_gaps": []
    }
  ]
}
```

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/evaluation/invariants.py tests/unit/test_invariants.py \
  tests/evaluation/invariant_cases/cases.json
git commit -m "feat: add the ADR-0016 invariant corpus model and data

A case that asserts nothing, a corpus with no cases, and a mistyped reason
code are all refused: each would otherwise report a passing invariant that
was never checked."
```

---

### Task 4: The check itself

**Files:**
- Modify: `src/codeatlas/evaluation/invariants.py`
- Modify: `tests/unit/test_invariants.py`

**Interfaces:**
- Consumes: `InvariantCorpus` and `load_corpus` from Task 3
- Produces:
  - `class CaseResult(ContractModel)`: `case_id: str`, `invariant: str`, `held: bool`, `failures: list[str]`
  - `class InvariantResult(ContractModel)`: `contract_version: Literal["1.0"]`, `results: list[CaseResult]`, and a property `held: bool` that is true only when every result held
  - `def check_corpus(corpus: InvariantCorpus) -> InvariantResult`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_invariants.py`:

```python
from codeatlas.evaluation.invariants import (
    InvariantCase,
    InvariantCorpus,
    check_corpus,
)


def _corpus(case: InvariantCase, root: Path) -> InvariantCorpus:
    return InvariantCorpus(cases=[case], root=root)


def _fixture_root() -> Path:
    return Path("tests/evaluation/invariant_cases")


def test_an_unrunnable_case_fails_rather_than_skipping(tmp_path: Path) -> None:
    # "did not hold" and "was not measured" must not be the same result.
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="does-not-exist",
        expect_gap_reasons={"Order": GapReasonCode.FIXTURE_MEDIATED_ONLY},
        expect_not_gaps=[],
    )

    result = check_corpus(_corpus(case, tmp_path))

    assert result.held is False
    assert result.results[0].held is False
    assert result.results[0].failures


def test_a_wrong_reason_fails_even_though_it_is_a_gap() -> None:
    # `Order` IS a gap in the real fixture, but for the fixture reason.
    # Demanding the helper reason must fail, or membership alone is all
    # that is being checked.
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="orders",
        expect_gap_reasons={"Order": GapReasonCode.HELPER_MEDIATED_ONLY},
        expect_not_gaps=[],
    )

    result = check_corpus(_corpus(case, _fixture_root()))

    assert result.held is False


def test_a_symbol_wrongly_expected_to_be_covered_fails() -> None:
    case = InvariantCase(
        id="i001",
        invariant="x",
        fixture="orders",
        expect_gap_reasons={},
        expect_not_gaps=["Order"],
    )

    result = check_corpus(_corpus(case, _fixture_root()))

    assert result.held is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_corpus'`

- [ ] **Step 3: Implement the check**

Add to `src/codeatlas/evaluation/invariants.py` (and add the imports
`from codeatlas.analysis.engine import ChangeAnalysisEngine` plus the
`DirectoryStateView` import path confirmed in Task 1):

```python
class CaseResult(ContractModel):
    """What one case did, and why if it failed."""

    case_id: str
    invariant: str
    held: bool
    # Human-readable, corpus-relative. Never an absolute path: rules.md
    # forbids emitting one, and it would also break reproducibility.
    failures: list[str] = Field(default_factory=list)


class InvariantResult(ContractModel):
    """Every case result. This is what gets committed as the artifact."""

    contract_version: Literal["1.0"] = "1.0"
    results: list[CaseResult]

    @property
    def held(self) -> bool:
        return all(result.held for result in self.results)


def check_corpus(corpus: InvariantCorpus) -> InvariantResult:
    """Run every case through the real engine and compare."""
    engine = ChangeAnalysisEngine()
    results = [_check_case(engine, corpus, case) for case in corpus.cases]
    return InvariantResult(results=results)


def _check_case(
    engine: ChangeAnalysisEngine,
    corpus: InvariantCorpus,
    case: InvariantCase,
) -> CaseResult:
    fixture = corpus.root / "fixtures" / case.fixture
    try:
        report = engine.analyze(
            DirectoryStateView(fixture / "base"),
            DirectoryStateView(fixture / "target"),
        )
    except Exception as error:  # noqa: BLE001 - an unrunnable case is a failure
        # Deliberately broad: any reason the engine cannot run this case is a
        # failure of the case, never a skip. A gate that reports "held" for a
        # case it could not execute is the exact problem this corpus exists
        # to fix.
        return CaseResult(
            case_id=case.id,
            invariant=case.invariant,
            held=False,
            failures=[f"case could not be run: {type(error).__name__}"],
        )

    gaps = set(report.impact.test_gaps)
    reasons = {
        item.qualified_name: item.reason
        for item in report.impact.test_gap_reasons
    }

    failures: list[str] = []
    for name, expected in sorted(case.expect_gap_reasons.items()):
        if name not in gaps:
            failures.append(
                f"{name} was expected to remain a gap but was not reported"
            )
            continue
        actual = reasons.get(name)
        if actual != expected:
            failures.append(
                f"{name} is a gap for {actual} but {expected} was expected"
            )
    for name in sorted(case.expect_not_gaps):
        if name in gaps:
            failures.append(
                f"{name} was expected to be covered but was reported a gap"
            )

    return CaseResult(
        case_id=case.id,
        invariant=case.invariant,
        held=not failures,
        failures=failures,
    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: PASS, 10 tests.

- [ ] **Step 5: Mutation-check the guard**

Prove the assertions are real. Temporarily change `_check_case` so
`expect_not_gaps` is not checked (delete that `for` loop), then run:

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: `test_a_symbol_wrongly_expected_to_be_covered_fails` FAILS.

Restore the loop, re-run, confirm PASS. **If the test still passed with the
loop deleted, the test is not testing anything — stop and report.**

- [ ] **Step 6: Commit**

```bash
git add src/codeatlas/evaluation/invariants.py tests/unit/test_invariants.py
git commit -m "feat: check the ADR-0016 invariant against the real engine

An unrunnable case is a failure, not a skip. Both halves of a gap
expectation are asserted -- membership alone would pass if every reason
collapsed to one constant."
```

---

### Task 5: Rendering and the CLI boundary

**Files:**
- Modify: `src/codeatlas/evaluation/invariants.py`
- Modify: `tests/unit/test_invariants.py`
- Create: `scripts/check_invariants.py`

**Interfaces:**
- Consumes: `InvariantResult` from Task 4
- Produces: `def render_invariant_markdown(result: InvariantResult) -> str`, and `scripts/check_invariants.py` with `build_parser()` and `main(argv) -> int`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_invariants.py`:

```python
from codeatlas.evaluation.invariants import (
    CaseResult,
    InvariantResult,
    render_invariant_markdown,
)


def test_the_markdown_names_a_failure_rather_than_only_counting_it() -> None:
    result = InvariantResult(
        results=[
            CaseResult(
                case_id="i001",
                invariant="a fixture-mediated symbol stays a gap",
                held=False,
                failures=["Order is a gap for None but FIXTURE... expected"],
            )
        ]
    )

    text = render_invariant_markdown(result)

    assert "i001" in text
    assert "Order is a gap" in text


def test_a_pipe_in_a_failure_cannot_break_the_table() -> None:
    result = InvariantResult(
        results=[
            CaseResult(
                case_id="i001", invariant="a|b", held=False, failures=["x|y"]
            )
        ]
    )

    text = render_invariant_markdown(result)

    for line in text.splitlines():
        if line.startswith("| i001"):
            assert line.count("|") == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: FAIL — `cannot import name 'render_invariant_markdown'`

- [ ] **Step 3: Implement the renderer**

Reuse the existing escaping rather than writing a second copy — add
`from codeatlas.delivery.markdown_text import escape_cell` and:

```python
def render_invariant_markdown(result: InvariantResult) -> str:
    """The human reading of the artifact.

    Fixture text is repository text and is escaped for the cell it lands in,
    exactly as the change report's markdown is.
    """
    verdict = "held" if result.held else "BROKEN"
    lines = [
        "# ADR-0016 invariants",
        "",
        "A weak `TESTS` edge explains a gap rather than closing it.",
        "",
        f"Result: **{verdict}** "
        f"({sum(1 for r in result.results if r.held)}"
        f"/{len(result.results)} cases held)",
        "",
        "| Case | Invariant | Held | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for item in result.results:
        detail = escape_cell("; ".join(item.failures)) if item.failures else ""
        lines.append(
            f"| {escape_cell(item.case_id)} "
            f"| {escape_cell(item.invariant)} "
            f"| {'yes' if item.held else 'NO'} "
            f"| {detail} |"
        )
    return "\n".join(lines) + "\n"
```

If `escape_cell` is not at `codeatlas.delivery.markdown_text`, locate it with
`grep -rn "def escape_cell" src/`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_invariants.py -q`
Expected: PASS, 12 tests.

- [ ] **Step 5: Write the CLI script**

`scripts/check_invariants.py` — modelled directly on
`scripts/run_phase4_baseline.py`, reusing its exit codes and `_write` /
`_matches` shape:

```python
"""Check the ADR-0016 invariant corpus and write its result artifact.

The Phase 4 baseline measures accuracy, which moves. This checks one boolean
that must not: a weak `TESTS` edge explains a gap rather than closing it.
Weakening it requires editing corpus data AND regenerating a committed
artifact -- two visible acts in one diff.

Usage::

    uv run python scripts/check_invariants.py \\
        --corpus tests/evaluation/invariant_cases \\
        --json-output docs/evaluation/invariants.json \\
        --markdown-output docs/evaluation/invariants.md [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from codeatlas.evaluation.cli import (
    EXIT_INTERNAL_FAILURE,
    EXIT_INVALID_INPUT,
    EXIT_STALE_ARTIFACT,
    EXIT_SUCCESS,
)
from codeatlas.evaluation.invariants import (
    InvariantCorpusError,
    InvariantResult,
    check_corpus,
    load_corpus,
    render_invariant_markdown,
)

# A broken invariant is not a stale artifact and must not share its code: one
# means "regenerate this file", the other means "the product regressed".
EXIT_INVARIANT_BROKEN = 7


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check the ADR-0016 invariant corpus."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare against the tracked artifacts instead of overwriting.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = check_corpus(load_corpus(args.corpus))
        json_text = _result_json(result)
        markdown_text = render_invariant_markdown(result)

        if not result.held:
            for item in result.results:
                for failure in item.failures:
                    print(f"{item.case_id}: {failure}", file=sys.stderr)
            print(
                "ADR-0016 invariant broken. A weak edge must explain a gap,"
                " not close it. See docs/adr/0016-derivation-tiered-test-"
                "edges.md.",
                file=sys.stderr,
            )
            return EXIT_INVARIANT_BROKEN

        if args.check:
            if not (
                _matches(args.json_output, json_text)
                and _matches(args.markdown_output, markdown_text)
            ):
                print(
                    "Invariant artifacts are stale. Regenerate them without"
                    " --check and review the diff.",
                    file=sys.stderr,
                )
                return EXIT_STALE_ARTIFACT
            return EXIT_SUCCESS

        _write(args.json_output, json_text)
        _write(args.markdown_output, markdown_text)
        return EXIT_SUCCESS
    except (InvariantCorpusError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid input: {error}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - defensive CLI boundary
        print(f"Internal failure: {error}", file=sys.stderr)
        return EXIT_INTERNAL_FAILURE


def _result_json(result: InvariantResult) -> str:
    return (
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)
        + "\n"
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _matches(path: Path, expected: str) -> bool:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n") == expected
    except OSError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
```

Check `src/codeatlas/evaluation/cli.py` for the actual exit-code constant
names and confirm `EXIT_STALE_ARTIFACT` exists; if a constant is named
differently, use the real name.

- [ ] **Step 6: Generate the artifacts**

```bash
uv run python scripts/check_invariants.py \
  --corpus tests/evaluation/invariant_cases \
  --json-output docs/evaluation/invariants.json \
  --markdown-output docs/evaluation/invariants.md
```

Expected: exit 0. Read `docs/evaluation/invariants.md` and confirm it says
`held` and `4/4 cases held`. Confirm neither artifact contains an absolute
path (`grep -i "C:\\\\\|/home/\|/Users/" docs/evaluation/invariants.json`
must find nothing).

- [ ] **Step 7: Verify reproducibility**

```bash
uv run python scripts/check_invariants.py \
  --corpus tests/evaluation/invariant_cases \
  --json-output docs/evaluation/invariants.json \
  --markdown-output docs/evaluation/invariants.md --check
```

Expected: exit 0, no output.

- [ ] **Step 8: Commit**

```bash
git add scripts/check_invariants.py src/codeatlas/evaluation/invariants.py \
  tests/unit/test_invariants.py docs/evaluation/invariants.json \
  docs/evaluation/invariants.md
git commit -m "feat: add the invariant checker and its committed artifact

A broken invariant exits 7, distinct from the stale-artifact code: one says
regenerate the file, the other says the product regressed."
```

---

### Task 6: Wire it into the gate and the test suite

**Files:**
- Create: `tests/integration/test_invariant_corpus.py`
- Modify: `scripts/check_phase4.ps1`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_invariant_corpus.py`:

```python
"""The committed invariant corpus, run in-process.

`scripts/check_invariants.py --check` is the gate. This is the same check
without the artifact comparison, so a plain `uv run pytest` catches a broken
invariant too. It holds no expectations of its own -- it asserts only that
every case in the corpus held -- so it cannot be weakened without weakening
the corpus.
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.evaluation.invariants import check_corpus, load_corpus

CORPUS = Path("tests/evaluation/invariant_cases")


def test_every_adr_0016_invariant_holds() -> None:
    result = check_corpus(load_corpus(CORPUS))

    broken = [
        f"{item.case_id}: {'; '.join(item.failures)}"
        for item in result.results
        if not item.held
    ]
    assert not broken, "\n".join(broken)


def test_the_corpus_covers_both_weak_derivation_paths() -> None:
    # The gap this whole corpus exists to close. If someone deletes the
    # fixture and helper cases, every other assertion here still passes.
    corpus = load_corpus(CORPUS)
    expected = {
        reason
        for case in corpus.cases
        for reason in case.expect_gap_reasons.values()
    }

    assert "FIXTURE_MEDIATED_ONLY" in expected
    assert "HELPER_MEDIATED_ONLY" in expected


def test_the_corpus_still_proves_a_strict_edge_closes_a_gap() -> None:
    corpus = load_corpus(CORPUS)

    assert any(case.expect_not_gaps for case in corpus.cases)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_invariant_corpus.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 3: Add the gate step**

In `scripts/check_phase4.ps1`, add two parameters to the `param(...)` block
after `$Phase4BaselineMarkdown`:

```powershell
    [string]$InvariantsJson = "docs/evaluation/invariants.json",
    [string]$InvariantsMarkdown = "docs/evaluation/invariants.md"
```

Then add this step after the "Phase 4 engine baseline" step and before the
final `Write-Output`:

```powershell
# The Phase 4 corpus measures accuracy across 24 representative cases. It has
# no fixture- or helper-mediated scenario, so it cannot see the ADR-0016
# invariant at all. This step is the one that can.
Invoke-Checked "ADR-0016 invariants" @(
    "run", "python", "scripts/check_invariants.py",
    "--corpus", "tests/evaluation/invariant_cases",
    "--json-output", $InvariantsJson,
    "--markdown-output", $InvariantsMarkdown,
    "--check"
)
```

- [ ] **Step 4: Prove the gate actually fails when the invariant breaks**

This is the whole point of the work; verify it rather than assuming it.
Temporarily edit `src/codeatlas/analysis/impact.py` so `_test_gaps` accepts
`Derivation.LOW_CONFIDENCE_HEURISTIC` as qualifying (the exact mutation
ADR-0016 forbids), then run:

```bash
uv run python scripts/check_invariants.py \
  --corpus tests/evaluation/invariant_cases \
  --json-output docs/evaluation/invariants.json \
  --markdown-output docs/evaluation/invariants.md --check
```

Expected: **exit 7**, with stderr naming `Order` and `total`.

Then revert the mutation with `git checkout src/codeatlas/analysis/impact.py`
and re-run: expected exit 0.

**If the mutated run exits 0, the corpus does not detect the thing it was
built to detect — stop and report.**

- [ ] **Step 5: Run the full suite**

```bash
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
```

All must pass.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_invariant_corpus.py scripts/check_phase4.ps1
git commit -m "feat: gate the ADR-0016 invariant

Verified by mutation: allowing a low-confidence edge to qualify in _test_gaps
makes the checker exit 7 naming Order and total."
```

---

### Task 7: Documentation and the untouched-surface proof

**Files:**
- Modify: `docs/operations/change-analysis.md`
- Modify: `docs/adr/0016-derivation-tiered-test-edges.md`
- Modify: `documentation/memory.md`
- Modify: `docs/plans/PLAN.md`

- [ ] **Step 1: Prove nothing else moved**

```bash
git diff --stat main -- docs/evaluation/baseline-phase-4.json \
  docs/evaluation/baseline-phase-4.md \
  src/codeatlas/evaluation/dataset.py \
  src/codeatlas/evaluation/runner.py \
  tests/evaluation/cases/changes.json
```

Expected: **empty output**. If anything appears, the separation the design is
built on has been violated — stop and report.

- [ ] **Step 2: Document the corpus**

In `docs/operations/change-analysis.md`, under the "Test gap reasons"
section, append:

```markdown
**How this is gated.** The Phase 4 corpus has no fixture- or helper-mediated
case, so it cannot exercise the ADR-0016 invariant. A separate corpus at
`tests/evaluation/invariant_cases/` does, checked by
`scripts/check_invariants.py` and recorded in `docs/evaluation/invariants.json`.
Four cases run against one fixture tree: fixture-mediated, helper-mediated, a
strict edge that must still close a gap, and an unreferenced symbol. Regenerate
the artifact by running the script without `--check`. A broken invariant exits
7; a stale artifact exits with the stale-artifact code. This corpus asserts a
boolean, never accuracy — a case about how well something is detected belongs
in the Phase 4 corpus instead.
```

- [ ] **Step 3: Record it in the ADR**

Append to `docs/adr/0016-derivation-tiered-test-edges.md`:

```markdown
## Enforcement

Gated by `tests/evaluation/invariant_cases/` and `scripts/check_invariants.py`,
run by `scripts/check_phase4.ps1`. Verified by mutation: making
`low_confidence_heuristic` qualify in `_test_gaps` exits 7.
```

- [ ] **Step 4: Update memory and the handoff log**

In `documentation/memory.md`, close the recorded open item about the
evaluation corpus not seeing this feature: state that a separate invariant
corpus now covers it, and why extending the Phase 4 corpus was rejected (the
`ChangeCase` `extra="forbid"` model plus the byte-for-byte baseline check).

Append — never rewrite — a handoff entry in `docs/plans/PLAN.md` covering
what shipped, the mutation verification, and the standing rule that this
corpus does not grow into an accuracy corpus.

- [ ] **Step 5: Commit**

```bash
git add docs documentation
git commit -m "docs: record the invariant corpus and close the corpus gap"
```

---

## Completion

After Task 7, use superpowers:finishing-a-development-branch.
