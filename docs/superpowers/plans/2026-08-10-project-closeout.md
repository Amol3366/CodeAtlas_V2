# CodeAtlas V2 Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four remaining substantial defects and rulings, then give `docs/plans/PLAN.md` a terminal state that dispositions every open item as closed or explicitly deferred with a stated reason.

**Architecture:** Four independent slices — one product defect (pid-reuse detection), one measurement-instrument correction (relation path scoring), and two rulings that settle corpus/scope questions — followed by a closeout that converts the open tail into a declared end. No slice depends on another; they are ordered by value, not by need.

**Tech Stack:** Python 3.12, `ctypes`/Win32 (no new dependency), Pydantic contract models, pytest, SQLite. No frontend change. No migration.

## Global Constraints

Copied verbatim from `AGENTS.md` and the accepted ADR record. Every task's requirements implicitly include this section.

- `contract_version` stays **`1.1`**. `SCHEMA_VERSION` stays **`14`**. No migration in this plan.
- `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION`, and `CHUNKER_VERSION` stay unchanged. Any task that would move one is out of scope and must stop and report.
- **ADR-0003 holds: the evaluation corpus is never edited to make a number look better.** The only legitimate corpus edit is the ADR-0035/0036 rule — an expectation must name an identifier the system can produce. Task 3 is justified on that rule or not at all.
- **Do not rewrite historical ADRs, completed phase plans, or handoff evidence.** Append; never edit the record a gate was approved on.
- A new metric is **added beside** the one it corrects, never replacing it, so no historical baseline number changes meaning (the ADR-0003 / ADR-0027 precedent).
- No new Python or JS dependency. `uv.lock` and `pnpm-lock.yaml` must be byte-identical at the end.
- Domain code (`src/codeatlas/domain/`) imports nothing outward.
- Every task ends with the gate green: `uv run ruff check src tests scripts apps`, `uv run mypy --no-incremental src tests scripts apps`, `uv run pytest -q`, and the exit code captured **from the tool, not inferred**.
- **A test that has never been observed failing is a comment.** Every test written here is either observed red before the implementation, or mutation-checked after it. This is not optional — it is the single most-cited lesson in `documentation/memory.md`.
- Append a handoff entry to `docs/plans/PLAN.md` and update `documentation/memory.md` at the end of every task.

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `src/codeatlas/indexing/ownership.py` | Add process start time to the owner stamp and compare it in `owner_is_live` | 1 |
| `tests/integration/test_crash_reporting.py` | Extend with pid-reuse cases beside the existing ownership tests | 1 |
| `src/codeatlas/evaluation/runner.py` | Add `relation_path_recall` beside `relation_path_correctness` | 2 |
| `tests/evaluation/test_runner.py` | Pin recall-vs-precision behaviour | 2 |
| `tests/evaluation/cases/queries.json` | q010 target endpoint only | 3 |
| `docs/adr/0037-*.md` … `0039-*.md` | The three new decision records | 2, 3, 4 |
| `docs/adr/README.md` | Ledger rows for 0037–0039 | 2, 3, 4 |
| `docs/plans/PLAN.md` | Handoffs, then the terminal Active Work block | all, 5 |
| `documentation/memory.md`, `phases.md`, `PRD.md`, `README.md` | Status and the deferred register | 5 |

---

### Task 1: Pid-reuse detection in crash recovery

**Why this is first:** it is the only item on the list a *user* of the packaged build experiences. A reassigned pid leaves a repository permanently blocked from reindexing, and today the only remedy is reading `codeatlas doctor` and knowing what it means.

**The claim being overturned:** `ownership.py`'s own docstring says closing this "needs the owner's process start time, which has no portable source without a new dependency." That is true for *portable* and false for *Windows*, which `AGENTS.md` Section 5 names as the primary supported environment — and this module already calls `kernel32` through `ctypes` for exactly this kind of question. `GetProcessTimes` is beside `OpenProcess`, which the file already uses.

**Files:**
- Modify: `src/codeatlas/indexing/ownership.py` (docstring, `current_owner`, `owner_is_live`; add `process_start_time`)
- Test: `tests/integration/test_crash_reporting.py`

**Interfaces:**
- Produces: `process_start_time(pid: int) -> int | None` — an opaque, comparable integer identifying a process *instance*, or `None` when this platform or this process cannot answer. Callers must treat `None` as "unknown", never as "dead".
- Changes: `current_owner()` return value gains an optional `"started_at": int` key. It is **omitted** when `process_start_time` returns `None`, so the stamp shape stays exactly as it is on platforms that cannot answer.
- `owner_is_live(owner)` signature is unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_crash_reporting.py`, beside the existing ownership tests:

```python
def test_a_reused_pid_does_not_keep_a_dead_owner_alive() -> None:
    """The pid exists, but it is not the process that stamped the run.

    This is the failure the module docstring has declared open since Phase 6:
    the OS reassigns a dead owner's pid, the liveness check says "alive", and
    the repository stays blocked from reindexing forever. A start time
    distinguishes a process *instance* from a pid, which is only a slot.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-a-dead-process",
        # Deliberately not this process's creation time. 1 is a valid FILETIME
        # (1601-01-01) that no live process can have.
        "started_at": 1,
    }

    assert owner_is_live(owner) is False


def test_a_matching_start_time_still_reports_the_owner_alive() -> None:
    """The conservative direction is preserved: a real owner is left alone.

    Without this, Step 3 could be "return False whenever a start time is
    present", which passes the test above and corrupts a live index.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-another-process",
        "started_at": process_start_time(os.getpid()),
    }

    assert owner_is_live(owner) is True


def test_a_stamp_without_a_start_time_keeps_the_old_behaviour() -> None:
    """A database written by an earlier build must not change meaning.

    Those stamps carry no `started_at`, and inferring one is impossible. The
    rule stays pid-only for them, which is what they were written under.
    """
    owner = {"pid": os.getpid(), "token": "token-of-another-process"}

    assert owner_is_live(owner) is True


def test_an_unreadable_start_time_does_not_strand_a_live_run() -> None:
    """`None` means unknown, and unknown must read as alive.

    `process_start_time` returns `None` when the platform cannot answer or the
    handle cannot be opened. Treating that as "dead" would let one process
    heal another's in-flight index — the corruption the module exists to
    prevent.
    """
    owner = {
        "pid": os.getpid(),
        "token": "token-of-another-process",
        "started_at": None,
    }

    assert owner_is_live(owner) is True
```

Extend the existing import at the top of the file:

```python
from codeatlas.indexing.ownership import (
    PROCESS_TOKEN,
    owner_is_live,
    process_is_alive,
    process_start_time,
)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
uv run pytest tests/integration/test_crash_reporting.py -q -k "reused_pid or start_time"
```

Expected: **FAIL** with `ImportError: cannot import name 'process_start_time'`. If any test passes at this point, stop — the import would have failed first, so a pass means the test file was not edited.

- [ ] **Step 3: Implement `process_start_time`**

Add to `src/codeatlas/indexing/ownership.py`, after `_windows_process_is_alive`:

```python
def process_start_time(pid: int) -> int | None:
    """An opaque value identifying a process *instance*, not a pid slot.

    A pid is reused. A pid plus the moment that process started is not, for
    any interval that matters here. Returns ``None`` when this platform or
    this handle cannot answer, which callers must read as "unknown" and never
    as "dead" — see `owner_is_live`.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_process_start_time(pid)
    if sys.platform.startswith("linux"):
        return _linux_process_start_time(pid)
    # macOS has no answer here without a new dependency, and Section 5 does
    # not name it as a supported environment. `None` keeps the pre-existing
    # pid-only behaviour rather than guessing.
    return None


def _linux_process_start_time(pid: int) -> int | None:
    """Field 22 of `/proc/<pid>/stat`, in clock ticks since boot.

    Parsed from the last `)` rather than by splitting on spaces: field 2 is
    the executable name in parentheses and may itself contain spaces and
    parentheses, so a naive split mis-indexes every field after it.
    """
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    _, _, rest = raw.rpartition(")")
    fields = rest.split()
    # `rest` begins at field 3, so field 22 is index 19.
    if len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _windows_process_start_time(pid: int) -> int | None:
    """The creation FILETIME, as one comparable integer.

    100-nanosecond intervals since 1601-01-01. Two processes sharing a pid
    cannot share this value unless they started in the same 100 ns, which is
    not reachable — the OS does not reissue a pid that fast.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return None

    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        )
        if not ok:
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)
```

Add `from pathlib import Path` to the imports at the top of the file.

- [ ] **Step 4: Record the start time on new stamps**

Replace `current_owner` in the same file:

```python
def current_owner() -> dict[str, Any]:
    """The owner stamp to record on a run this process is starting.

    `started_at` is omitted rather than stored as `None` when the platform
    cannot answer, so a stamp written here is shaped exactly as it was before
    this key existed and old readers parse it unchanged.
    """
    stamp: dict[str, Any] = {"pid": os.getpid(), "token": PROCESS_TOKEN}
    started_at = process_start_time(os.getpid())
    if started_at is not None:
        stamp["started_at"] = started_at
    return stamp
```

- [ ] **Step 5: Compare it in `owner_is_live`**

Replace the tail of `owner_is_live` (the block from `pid = owner.get("pid")` onward):

```python
    pid = owner.get("pid")
    if not isinstance(pid, int):
        return False
    if not process_is_alive(pid):
        return False

    # The pid exists. Whether it is the *same process* is a second question,
    # and only a stamp carrying a start time can answer it. A stamp without
    # one predates this check, so it keeps the behaviour it was written under.
    stamped = owner.get("started_at")
    if not isinstance(stamped, int):
        return True

    observed = process_start_time(pid)
    if observed is None:
        # Unknown, not dead. Guessing "dead" here lets one process heal
        # another's in-flight index, which is the corruption this module
        # exists to prevent.
        return True

    return observed == stamped
```

- [ ] **Step 6: Correct the module docstring**

In `ownership.py`, replace the `**Known limitation: pid reuse.**` paragraph with:

```text
**Pid reuse is detected where the platform can answer.** A pid identifies a
slot, not a process, and the OS reassigns it. The owner stamp therefore also
records the owner's *start time*, and a pid whose live process started at a
different moment is a reused slot whose real owner is gone — recoverable, not
protected. `GetProcessTimes` answers this on Windows and `/proc/<pid>/stat`
on Linux, both already reachable without a new dependency; macOS has no such
source and keeps the pid-only behaviour, as does any stamp written before
this key existed. In every unanswerable case the run is left alone, because
guessing "dead" costs data and guessing "alive" costs only a delayed cleanup.
```

- [ ] **Step 7: Run the tests to verify they pass**

```powershell
uv run pytest tests/integration/test_crash_reporting.py -q
```

Expected: PASS, including the four pre-existing ownership tests. Those four are the regression guard for Step 5 — if `test_recovery_leaves_a_job_owned_by_this_process_alone` breaks, the token fast-path was disturbed.

- [ ] **Step 8: Mutation-check the new guard**

Two of the four new tests were written against behaviour that partly exists, so verify each fails for the right reason:

1. In `owner_is_live`, change `return observed == stamped` to `return True`. Run the tests. Expected: `test_a_reused_pid_does_not_keep_a_dead_owner_alive` **fails**, the other three pass.
2. Restore it, then change it to `return False`. Expected: `test_a_matching_start_time_still_reports_the_owner_alive` **fails**.
3. Restore. All four pass.

Record both observed failures in the handoff. A guard never seen failing is not a guard.

- [ ] **Step 9: Run the full gate**

```powershell
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run pytest -q
```

Expected: clean, clean, and 2148+ passed / 3 skipped with exit code **read from pytest**, not assumed.

> Note: `test_a_genuinely_killed_process_is_recovered_and_can_reindex` is a known Windows flake under full-suite load (`sqlite3.OperationalError: disk I/O error`, recorded in `documentation/memory.md`). If it fails, re-run it in isolation before treating it as caused by this task.

- [ ] **Step 10: Commit**

```bash
git add src/codeatlas/indexing/ownership.py tests/integration/test_crash_reporting.py
git commit -m "fix(recovery): detect pid reuse via process start time

A pid identifies a slot, not a process. The owner stamp now records the
owner's start time, so a reassigned pid no longer keeps a dead run's
repository blocked from reindexing. Windows uses GetProcessTimes and Linux
/proc/<pid>/stat, both already reachable without a new dependency; a stamp
without the key keeps the behaviour it was written under.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `relation_path_correctness` measures the wrong thing (ADR-0037)

**The contradiction, stated exactly.** `runner.py:301` scores relation paths with `_precision(predicted_relations, expected_relations)`. ADR-0020 **mandates** that a graph answer emit *every* supporting edge. So when the engine emits a true edge the corpus did not happen to declare, precision falls — this metric penalises the engine for obeying an accepted decision. ADR-0034 and ADR-0035 both recorded the symptom (q005 and q015 capped at 0.5 while emitting only correct edges) without naming the cause.

This is the ADR-0027 shape exactly: the number was low because the *instrument* was wrong, not because the engine was.

**Files:**
- Modify: `src/codeatlas/evaluation/runner.py` (`QueryScore`, `score_query_case`, `EvaluationMetrics`, `_null_metrics`, the Markdown table, aggregation)
- Create: `docs/adr/0037-relation-path-recall.md`
- Modify: `docs/adr/README.md`
- Test: `tests/evaluation/test_runner.py`

> **Correction made during execution review (2026-08-10).** The plan first named
> `tests/evaluation/test_runner_metrics.py` and invented `_query_case` /
> `_query_prediction` helpers. **Neither exists.** The file is
> `tests/evaluation/test_runner.py`, and its convention is to load a *real*
> corpus case via `load_dataset(DATASET_ROOT)` and construct a `QueryPrediction`
> against it. Tests below follow the real convention. Using q015 is better than
> a synthetic case anyway: `src.client IMPORTS total` is declared, the engine
> also emits the true-but-undeclared `total REFERENCES Order`, and that is
> precisely the ADR-0020-versus-precision conflict this task exists to correct.

**Interfaces:**
- Produces: `QueryScore.relation_path_recall: Confidence` and `EvaluationMetrics.relation_path_recall: MetricValue = None`.
- `relation_path_correctness` is **retained and unchanged** on both models, so every one of the six tracked baselines keeps its current value and meaning. This is not optional — it is the ADR-0003 / ADR-0027 precedent and the reason no baseline needs regenerating for the old number.

- [ ] **Step 1: Write the failing test**

Append to `tests/evaluation/test_runner.py`, following that file's existing
convention — load the real case, then build a `QueryPrediction` against it:

```python
def _case(case_id: str) -> QueryCase:
    """The real corpus case with this id.

    Real rather than synthetic on purpose: q015 is the actual shape this
    metric gets wrong, so a stand-in would prove less.
    """
    for case in load_dataset(DATASET_ROOT).query_cases:
        if case.id == case_id:
            return case
    raise AssertionError(f"no such case: {case_id}")


def _relation_prediction(
    case_id: str, relation_paths: list[str]
) -> QueryPrediction:
    return QueryPrediction(
        case_id=case_id,
        ranked_symbols=[],
        ranked_evidence=[],
        relation_paths=relation_paths,
        claims=[],
        abstained=False,
        duration_ms=1.0,
    )


def test_an_extra_true_relation_does_not_reduce_recall() -> None:
    """ADR-0020 requires emitting every supporting edge; recall must not punish it.

    q015 is the real case: it declares `src.client IMPORTS total`, and the
    engine also emits `total REFERENCES Order` -- true, undeclared, and
    mandated. Precision halves for that. Recall must not.

    Both numbers are asserted, because the precision figure is retained
    deliberately and a change to it would silently move six baselines.
    """
    case = _case("q015")
    prediction = _relation_prediction(
        "q015",
        ["src.client IMPORTS total", "total REFERENCES Order"],
    )

    score = score_query_case(case, prediction)

    assert score.relation_path_recall == 1.0
    assert score.relation_path_correctness == 0.5


def test_a_missing_relation_still_reduces_recall() -> None:
    """Recall must not be a metric that can only go up.

    q017 declares two exports. Predicting one is half the answer, and a
    metric that scored that 1.0 would be measuring nothing.
    """
    case = _case("q017")
    prediction = _relation_prediction("q017", ["src.orders EXPORTS Order"])

    score = score_query_case(case, prediction)

    assert score.relation_path_recall == 0.5
    assert score.relation_path_correctness == 1.0
```

Add `QueryCase` to the `codeatlas.evaluation.dataset` import block at the top of
the file if it is not already there.

- [ ] **Step 2: Run to verify it fails**

```powershell
uv run pytest tests/evaluation/test_runner_metrics.py -q -k relation
```

Expected: **FAIL** with `AttributeError: 'QueryScore' object has no attribute 'relation_path_recall'`.

- [ ] **Step 3: Add the field to `QueryScore`**

In `runner.py`, beside `relation_path_correctness: Confidence` (line ~149):

```python
    relation_path_correctness: Confidence
    # ADR-0037. Precision penalises the engine for emitting a true edge the
    # corpus did not declare -- which ADR-0020 *requires* it to do. Recall asks
    # the question the corpus can actually answer: did every declared relation
    # appear? The precision number is retained unchanged so no tracked baseline
    # changes meaning, the same treatment ADR-0003 gave `valid_evidence_rate`.
    relation_path_recall: Confidence = 0.0
```

- [ ] **Step 4: Compute it in `score_query_case`**

Replace line ~301:

```python
    relation_correctness = _precision(predicted_relations, expected_relations)
    relation_recall = _recall(predicted_relations, expected_relations)
```

and add `relation_path_recall=relation_recall,` to the `QueryScore(...)` construction beside `relation_path_correctness=relation_correctness,`.

If `_recall` does not already exist beside `_precision` in this module, add it directly above `_precision`, matching that function's signature and empty-set handling exactly:

```python
def _recall(predicted: set[str], expected: set[str]) -> float:
    """Share of expected items that were predicted.

    Mirrors `_precision`'s handling of an empty denominator so the two are
    read the same way: no expectation is not a perfect score, it is no score.
    """
    if not expected:
        return 0.0
    return len(predicted & expected) / len(expected)
```

- [ ] **Step 5: Aggregate it**

In `EvaluationMetrics`, beside `relation_path_correctness: MetricValue`:

```python
    relation_path_correctness: MetricValue
    # ADR-0037. Defaulted to `None` so an artifact written before this record
    # still loads and scores exactly as it did.
    relation_path_recall: MetricValue = None
```

In `_null_metrics`, beside `relation_path_correctness=0.0`, add `relation_path_recall=0.0` — explicitly `0.0` and not the `None` default, for the reason the neighbouring comment already gives about `containing_evidence_recall_at_10`.

In the aggregation block (~line 601), beside `relation_scores`:

```python
    relation_recall_scores = [
        score.relation_path_recall
        for score, case in zip(query_scores, dataset.query_cases, strict=True)
        if case.expected_relations and score.measured
    ]
```

and in the returned `EvaluationMetrics(...)`, beside `relation_path_correctness=_mean(relation_scores),`:

```python
        relation_path_recall=_mean(relation_recall_scores),
```

In the Markdown table (~line 448), beside the correctness row:

```python
        (
            "Relation path recall",
            _format_metric(report.metrics.relation_path_recall),
        ),
```

- [ ] **Step 6: Run to verify it passes**

```powershell
uv run pytest tests/evaluation/test_runner_metrics.py -q -k relation
```

Expected: PASS.

- [ ] **Step 7: Measure, and record the number before deciding anything**

```powershell
uv run python scripts/run_evaluation.py --dataset tests/evaluation/cases
```

Record `relation_path_correctness` (expected: unchanged at 0.6364) and the new `relation_path_recall`. **Do not set a gate target for recall in this task.** ADR-0034 decomposed this metric into four causes and two remain (lexical intents emitting no paths, q027/q029; and q010's modelling question, Task 3). A threshold over a metric with unsettled causes is exactly what ADR-0023 says cannot be reasoned about. Record the value and say it is ungated and why.

- [ ] **Step 8: Regenerate the affected baselines**

Only `relation_path_recall` is new, so only artifacts that carry it move, and only by gaining a key:

```powershell
uv run python scripts/run_evaluation.py --dataset tests/evaluation/cases --baseline docs/evaluation/baseline-phase-3
uv run python scripts/run_evaluation.py --dataset tests/evaluation/cases --baseline docs/evaluation/baseline-phase-4
```

Use whatever regeneration invocation `scripts/check_phase4.ps1` itself uses — read it first rather than guessing the flag names. **`baseline-phase-1` and `-2` are frozen history and must not be touched** (their gate scripts are marked SUPERSEDED and exit 5 by design). Confirm `git diff` on the regenerated files shows *only* an added key and no changed value; a changed value means Step 4 disturbed the precision path and must be fixed, not accepted.

- [ ] **Step 9: Write ADR-0037**

Create `docs/adr/0037-relation-path-recall.md` from `docs/adr/0000-template.md`, status `accepted`. It must state:
- the contradiction with ADR-0020 in one sentence;
- that precision is retained so no historical figure changes meaning;
- that recall is **deliberately ungated** until ADR-0034's remaining two causes are settled;
- that **no engine behaviour changed**, and this must never be cited as uplift.

Add the ledger row to `docs/adr/README.md`.

- [ ] **Step 10: Full gate, then commit**

```powershell
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
uv run pytest -q
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
```

```bash
git add src/codeatlas/evaluation/runner.py tests/evaluation/test_runner_metrics.py docs/adr/ docs/evaluation/
git commit -m "feat(evaluation): score relation paths by recall (ADR-0037)

Precision penalised the engine for emitting a true edge the corpus did not
declare, which ADR-0020 requires it to do. Recall is added beside it; the
precision number is retained so no tracked baseline changes meaning. No
engine behaviour changed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Does `IMPORTS` target the module or the bound class? (ADR-0038)

> **CONFIRM WITH THE USER BEFORE STARTING.** This is a modelling ruling, not a defect fix. The recommendation below is mine; the decision is theirs. ADR-0035 deliberately left q010 half-fixed rather than settle it in a naming change.

**The question.** For `from .idempotency import IdempotencyStore`, the corpus declares the edge targets the **module** (`src.payments.idempotency`); the engine records the **class** the statement actually binds (`IdempotencyStore`). q010 scores 0.0000 on that one disagreement.

**Recommended ruling: the engine is right; the expectation is corrected.**

Three reasons, in order of weight:
1. **ADR-0021 depends on the engine's reading.** Its import-and-call rule requires the imported owner to be a *class*, never a module — precisely so that `import orders` cannot vouch for every symbol inside it. That constraint was caught by the ADR-0016 invariant corpus when the first implementation got it wrong. Re-pointing `IMPORTS` at the module would reopen the hole ADR-0021 closed.
2. **The statement binds a name.** `from x import Y` puts `Y` in the namespace, not `x`. An edge claiming otherwise describes something the code does not do.
3. It satisfies the ADR-0035/0036 rule: the corrected expectation names an identifier the engine can produce, and the validator from ADR-0036 will enforce it from then on.

**Files:**
- Modify: `tests/evaluation/cases/queries.json` (q010, target endpoint of one relation string only)
- Create: `docs/adr/0038-imports-target-the-bound-symbol.md`
- Modify: `docs/adr/README.md`, regenerate `baseline-phase-3` and `-4`

- [ ] **Step 1: Confirm the ruling with the user.** Do not edit the corpus before this. If the user rules the other way, the work is an extraction change plus a `RESOLVER_VERSION` bump plus re-indexing — a different and much larger task that must not be started under this plan.

- [ ] **Step 2: Read q010 and confirm the disagreement is only the target**

```powershell
uv run python -c "import json; cases=json.load(open('tests/evaluation/cases/queries.json')); print(json.dumps([c for c in cases['query_cases'] if c['id']=='q010'], indent=2))"
```

Confirm the source endpoint is already qualified (ADR-0035 did that) and only the target is bare. If the source is also wrong, stop and report — that is a different finding.

- [ ] **Step 3: Verify the engine's symbol exists before writing it**

```powershell
uv run pytest tests/evaluation/test_expectations_name_real_symbols.py -q
```

This is ADR-0036's validator. It must be **green before** the edit (proving the current corpus is otherwise consistent) and green after (proving the new name resolves). If it is red before, fix that first — it means something else regressed.

- [ ] **Step 4: Correct the one endpoint**

Edit only the target of q010's `expected_relations` entry, from the bare module name to the class the import binds. Change nothing else in the file.

- [ ] **Step 5: Measure**

```powershell
uv run python scripts/run_evaluation.py --dataset tests/evaluation/cases
```

Expected: `relation_path_correctness` and `relation_path_recall` both rise; q010 moves off 0.0000. **Record the exact before/after.** If any metric other than the two relation metrics moves, stop — a one-endpoint corpus edit cannot legitimately move symbol resolution or evidence rates, and one that does means something is wired wrong.

- [ ] **Step 6: Write ADR-0038, regenerate baselines 3 and 4, run the full gate, commit**

The ADR must record the rejected alternative (re-pointing extraction at the module) and **why it was rejected — that it reopens the ADR-0021 hole** — because that is the reasoning a future author will need, not the conclusion.

```bash
git commit -m "fix(evaluation): IMPORTS names the symbol the statement binds (ADR-0038)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Close the `CODEATLAS_EPHEMERAL` CLI scope question (ADR-0039)

> **CONFIRM WITH THE USER.** The recommendation is **won't-fix, with the reasoning recorded** — the opposite of what the open item implies, so it deserves an explicit yes.

**The finding.** The item has been carried as "should `CODEATLAS_EPHEMERAL` cover CLI commands?" The answer is no, and the reason is structural rather than preferential: **ephemeral means "storage discarded when the process exits", and a CLI command exits immediately.** Each invocation would create its own empty session database, do its work against nothing, and destroy it. `codeatlas index <repository_id>` would fail with the repository unregistered, because the `repo add` that registered it ran in a *different* process against a *different* throwaway database. The mode is only coherent for a long-lived process, which is `serve`.

The half of this that was a real defect — that nothing told the user which database was in play — was fixed on 2026-08-09 by `_announce_database` (`cli/main.py:169`). What remains is a scope question whose answer is "the current scope is correct".

**Files:**
- Create: `docs/adr/0039-ephemeral-scope-is-the-server.md`
- Modify: `src/codeatlas/cli/main.py` (docstring at `_ephemeral_requested` only), `docs/adr/README.md`, `docs/operations/ephemeral-sessions.md`

- [ ] **Step 1: Confirm the won't-fix ruling with the user.**

- [ ] **Step 2: Write a test that pins the boundary**

This ruling is only durable if something enforces it. Add to `tests/end_to_end/test_ephemeral_session_isolation.py`:

```python
def test_a_cli_command_ignores_the_ephemeral_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ADR-0039: ephemeral scope is the server, and that is deliberate.

    A CLI process exits immediately, so a session database would be created
    empty, used for one command, and destroyed — and the `repo add` that
    registered a repository would be invisible to the `index` that followed
    it. The variable is therefore honoured by `serve` alone.

    This asserts the *decision*, not an implementation detail: if a future
    change makes the CLI ephemeral, this test must be deleted deliberately
    along with the ADR, not quietly adjusted.
    """
    monkeypatch.setenv("CODEATLAS_EPHEMERAL", "1")
    database = tmp_path / "codeatlas.db"

    result = _run_cli(["repo", "add", str(_fixture_repo()), "--database", str(database), "--json"])

    assert result.exit_code == 0
    assert database.exists(), "the CLI wrote the database it was given"
```

Match the existing helpers in that file rather than inventing `_run_cli` / `_fixture_repo` if equivalents already exist.

- [ ] **Step 3: Run it, and mutation-check it**

It will pass immediately, because the behaviour already exists — which makes it worthless until proven otherwise. Mutation-check: make `_services` (`cli/main.py:199`) route through `_ephemeral_requested(flag=False)` and confirm the test **fails**. Restore. Record the observed failure in the handoff.

- [ ] **Step 4: Replace the docstring at `_ephemeral_requested` with the ruling**

```python
def _ephemeral_requested(*, flag: bool) -> bool:
    """Whether this run should use a throwaway session database.

    Read at exactly one call site, inside `serve`, and that scope is the
    decision recorded in ADR-0039 rather than an oversight. Ephemeral means
    storage discarded when the process exits; a CLI command exits at once, so
    every invocation would get its own empty database and the `repo add` that
    registered a repository would be invisible to the `index` that followed
    it. The mode is only coherent for a long-lived process.

    The real defect here — that nothing said which database was in play — is
    fixed separately by `_announce_database`.
    """
```

- [ ] **Step 5: Write ADR-0039, update `docs/operations/ephemeral-sessions.md`, run the gate, commit**

---

### Task 5: The closeout — give `PLAN.md` a terminal state

**Why this is a task and not paperwork.** Right now `docs/plans/PLAN.md` says "Active task: none … awaiting user instruction" while carrying a seven-item open tail that has stayed seven items long for three days. That is an open project with no end condition. This task converts the tail into a **register**: every item either closed, or deferred with a stated reason and a named trigger for reopening it.

**Files:**
- Modify: `docs/plans/PLAN.md` (Active Work block + a new "Deferred Register" section + the handoff)
- Modify: `documentation/memory.md`, `documentation/phases.md`, `documentation/PRD.md`, `README.md`

- [ ] **Step 1: Write the deferred register into `PLAN.md`**

One row per item. Every row states the reason and what would reopen it. Copy these dispositions:

| Item | Disposition | Reopens when |
| --- | --- | --- |
| Unsigned executable | **Deferred — not an engineering task.** Needs a purchased code-signing certificate. | A certificate is purchased. |
| Five Chromium Playwright skips | **Deferred — upstream defect.** Firefox runs all five; coverage is not lost. | The upstream renderer bug is fixed. |
| Packaged tree 1.05 GB | **Accepted at the Phase 7 activation gate.** The torch cost was known and approved. | A deterministic-only second artifact is wanted. |
| Grow symbol corpus toward 50 cases (ADR-0033) | **Deferred — multi-day.** 13+ cases each needing gold ranges. Nothing is *wrong* today; 0.98 is simply inexpressible at 27 cases, which ADR-0033 documents at the constant. | Someone commits the days. |
| RRF coarse-chunk bias (ADR-0028) | **Deferred — needs corpus-wide measurement,** not a one-case fix. ADR-0030 records that the obvious lever trades an evidence hit for a symbol hit. | The module-granularity ruling lands. |
| Phase 4 `containing_evidence_rate` 0.6667, `containing_evidence_recall_at_10` 0.8305 | **Deferred — cause unknown.** Given ADR-0017/0018/0022/0027, the prior is that the instrument is wrong again, not the engine. Must be investigated before it is called a defect. | Someone investigates per-case. |
| Phase 4 `changed_symbol_precision` 0.9375 | **Closed as structural.** c020–c022 split one physical diff into three single-symbol cases that count each other's symbols against them; the other 21 score 1.0. Fully explained in `docs/evaluation/phase-4-baseline-environment.md`. | Never — the corpus is not edited (ADR-0003). |
| ADR-0030 module-granularity ruling | **Open — a product question,** not a defect: when a concept is documented at module level, does the module satisfy a conceptual question? Nothing fails today. | The user rules. |

- [ ] **Step 2: Rewrite the `Active Work` block**

Set `Active phase` and `Active task` to **`none — closed`**, with `Next gate` reading: *"None. Phases 0–7 complete; the closeout of 2026-08-10 dispositioned every open item. New work requires an explicit user decision."*

- [ ] **Step 3: Correct the two known doc-drift items**

- `README.md:352` says "the eight accepted architecture decisions" — it is now 39. Fix the count, or better, drop the number so it cannot go stale again.
- `documentation/memory.md` header says `Last updated: 2026-08-09` while carrying 2026-08-10 entries. Set it to the closeout date.

- [ ] **Step 4: Update `phases.md` "Still Open" and `PRD.md` "Current Status"** to point at the register rather than restating it. Two copies of a status list is how they drift — the same duplication lesson as `--format pr` and `_SEVERITY_ORDER`.

- [ ] **Step 5: Final full gate on the packaged path**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

`check_phase7` gates more than `check_phase4` and is the one that historically goes unrun (ADR-0022 finding 5, recurring in ADR-0027). It must be the last thing executed before the closeout handoff.

- [ ] **Step 6: Append the closeout handoff to `PLAN.md` and commit**

The handoff must record, per the schema: the four ADRs added (0037–0039 plus any from Task 3/4), that **no migration and no contract change** occurred, the exact gate commands with exit codes read from the tools, and the register as the terminal state.

---

## Self-Review

**Spec coverage.** Every item from my closeout recommendation is assigned: pid-reuse → Task 1; relation-path instrument → Task 2; q010 ruling → Task 3; ephemeral scope ruling → Task 4; the two doc-drift fixes and the terminal state → Task 5. Code signing, Chromium, package size, corpus growth, RRF, and Phase 4's two evidence rates are dispositioned in Task 5's register rather than silently dropped. ADR-0030 is left explicitly open as a user ruling.

**Placeholder scan.** No "TBD", no "add error handling", no "similar to Task N". Every code step carries the actual code. Two deliberate exceptions, both flagged inline rather than hidden: Task 2 Step 8 and Task 3 Step 6 say to read the regeneration flags out of `check_phase4.ps1` rather than guessing them, because guessing a baseline-regeneration flag is how a frozen artifact gets overwritten.

**Type consistency.** `process_start_time(pid: int) -> int | None` is defined in Task 1 Step 3 and used in Steps 4, 5, and the tests in Step 1 with that exact signature. `_recall(predicted: set[str], expected: set[str]) -> float` mirrors the existing `_precision`. `relation_path_recall` is spelled identically on `QueryScore` (Step 3), in `score_query_case` (Step 4), on `EvaluationMetrics`, in `_null_metrics`, and in the aggregation (Step 5).

**Known risk, stated rather than designed around.** Tasks 3 and 4 are rulings I am recommending, not defects I am fixing. Both are marked CONFIRM-WITH-USER, and Task 3 names what changes if the user rules the other way (an extraction change plus a `RESOLVER_VERSION` bump plus re-indexing — out of scope for a one-day closeout).

**What this plan does not do.** It does not close Recall@10 on the deterministic corpus, grow the corpus, tune RRF, shrink the package, or sign the binary. Those are deferred with reasons in Task 5's register. A closeout that pretended otherwise would be the "fake success" `AGENTS.md` Section 21 forbids.
