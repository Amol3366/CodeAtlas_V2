# Symbol Corpus to Fifty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the scored symbol-intent corpus from 27 cases to 50, so that `exact_symbol_resolution`'s 0.98 release target can finally express a single miss instead of silently meaning "no failures tolerated".

**Architecture:** A sixth supported fixture, `symbol_breadth`, built for one purpose: enough distinct symbol shapes to ask 23 more questions of. Existing fixtures are left byte-identical, so no existing case changes what it retrieves against and no metric moves for a reason unrelated to this work. The new cases spread across all six symbol-shaped intents rather than piling onto `EXACT_SYMBOL`, because the current 27 are 16/27 `EXACT_SYMBOL` and the graph intents are the thin ones.

**Tech Stack:** Python 3.12, pytest 9.1.1, the existing evaluation runner and dataset models. **No new dependency. No `src/` change except one tuple entry.**

**Spec:** WS-1 Tasks 4–5 of `docs/superpowers/plans/2026-08-14-post-closeout-program.md`, and the Deferred Register row "Grow the symbol corpus toward 50 cases" in `docs/plans/PLAN.md`. ADR-0033 is the record that states why 50 is the number.

## Global Constraints

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live status; append handoffs, never rewrite them.
- **ADR-0003: the corpus is never edited to move a number.** *Adding* coverage is legitimate; *changing* an existing expectation requires the ADR-0031/0036 justification — the expectation named something the engine cannot produce, or contradicted itself. **This plan adds only. It must not touch any existing case.**
- **ADR-0036: every expectation must name a symbol the engine can resolve**, because `expected_symbols[0]` *is* the query the harness issues. `tests/evaluation/test_expectations_name_real_symbols.py` enforces this and picks up new fixtures automatically.
- **Test-first**, and mutation-check anything that passes on its first run. A case that cannot fail measures nothing.
- **Revert from a file copy, never `git checkout --`** (ADR-0022, ADR-0042).
- No change to `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION`, `CHUNKER_VERSION`, `SCHEMA_VERSION` (14), or `contract_version` (1.1). Nothing here touches the engine, so no snapshot goes stale.
- Gates before any completion claim: `uv run pytest -q`, `ruff check src tests scripts apps`, `mypy --no-incremental src tests scripts apps`, `check_phase4.ps1 -SkipSync`, `check_phase7.ps1 -SkipSync`. **These may now be run concurrently** — the shared-`.test-tmp` collision was fixed 2026-08-15 and the "one at a time" rule is retired.

---

## Findings that change this plan

Measured 2026-08-15, before writing it. **The program plan's Task 4 cannot work as written**, for two independent reasons.

**Finding 1 — the target needs 23 more cases, not ~13.** `exact_symbol_resolution` is the mean of `exact_symbol_resolved` over cases whose intent is in `SYMBOL_INTENTS` and whose `expected_symbols` is non-empty and measured (`runner.py:596-603`). That is **27** cases today, confirmed by running the loader. The arithmetic:

| Scored cases | One miss scores | 0.98 expressible? |
| ---: | ---: | :--- |
| 27 (today) | 0.9630 | no |
| 40 (the plan's "~13 more") | 0.9750 | **no** |
| 49 | 0.9796 | no |
| **50** | **0.9800** | **yes** |

So the plan's own stated goal — "at ~50 cases the target is finally expressible" — is not reached by its own step. 50 is the first integer that works, and it is exactly 23 more.

**Finding 2 — the fixtures do not contain 23 more things to ask about.** Indexing all five supported fixtures with the real engine yields these non-module symbols:

| Fixture | Distinct non-module symbols |
| --- | ---: |
| `python_app` | 9 |
| `tsjs_app` | 4 |
| `mixed_app` | 5 |
| `git_changes` | 2 |
| **total symbol-shaped material** | **20** |

(`docs_config`'s 15 symbols are document sections and config keys, which are `DOCUMENT_LOOKUP`/`CONFIG_LOOKUP` — the *lexical* metric, not this one.)

The existing 27 cases already query those 20, several of them twice (q002/q009 both ask for `PaymentService.capture`; q014/q018 both `render`; q025/q030 both `get_order`; q033/q034 both `process`). **Adding 23 more cases against 20 symbols means asking the same questions again** — which inflates the denominator without adding coverage, and loosens a release target by padding. That is the mirror image of what ADR-0032 and ADR-0033 refused to do, and it must not be how 50 is reached.

**Hence a new fixture.** Ruled by the project owner 2026-08-15: a sixth supported fixture, leaving the existing five byte-identical so no existing case's retrieval changes.

**Finding 3, which makes the work smaller than it looks.** `SYMBOL_INTENTS` is `{EXACT_SYMBOL, CALLERS, DEPENDENCIES, EXPORTS, RELATED_TESTS, TRACE_FLOW}` (`dataset.py:134`). Every one of those counts toward `exact_symbol_resolution`, so the 23 new cases do **not** all have to be `EXACT_SYMBOL`. Today's 27 are 16 `EXACT_SYMBOL` against 2 `CALLERS`, 3 `DEPENDENCIES`, 1 `EXPORTS`, 1 `RELATED_TESTS`, 5 `TRACE_FLOW`. Spreading the new cases across the graph intents raises the count *and* fixes that imbalance.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `tests/evaluation/cases/fixtures/symbol_breadth/**` | **New.** Five source files chosen for symbol variety | 1 |
| `tests/evaluation/cases/dataset.json` | Declares the fixture, its snapshot members, and the new query count | 1, 2 |
| `src/codeatlas/evaluation/engine_adapter.py` | `SUPPORTED_FIXTURES` gains one entry | 1 |
| `tests/evaluation/cases/queries.json` | 23 new cases | 2 |
| `tests/evaluation/test_dataset.py`, `test_cli.py`, `test_runner.py` | Hardcoded counts, 40 → 63 | 2 |
| `docs/evaluation/baseline-phase-{0,3,4}.{json,md}` | Regenerated. **`-1` and `-2` stay frozen as history** | 2 |
| `docs/plans/PLAN.md`, `documentation/memory.md`, the program plan | Records | 3 |

The fixture is five small files rather than one large one because each targets a different extraction path, and a fixture file that mixes them makes a failure harder to attribute.

---

### Task 1: The `symbol_breadth` fixture

**Files:**
- Create: `tests/evaluation/cases/fixtures/symbol_breadth/src/orders/repository.py`
- Create: `tests/evaluation/cases/fixtures/symbol_breadth/src/orders/pipeline.py`
- Create: `tests/evaluation/cases/fixtures/symbol_breadth/src/web/handlers.ts`
- Create: `tests/evaluation/cases/fixtures/symbol_breadth/src/web/widgets.js`
- Create: `tests/evaluation/cases/fixtures/symbol_breadth/tests/test_pipeline.py`
- Modify: `tests/evaluation/cases/dataset.json` (fixtures array)
- Modify: `src/codeatlas/evaluation/engine_adapter.py` (`SUPPORTED_FIXTURES`)

**Interfaces:**
- Produces: a fixture id `symbol_breadth` with snapshot id `breadth-v1`, and the symbol inventory Task 2 writes its cases against.

**Fixture code is never executed** (`AGENTS.md` §4.4). It is read as text. It still has to *parse*, so it is written as real, valid code.

- [ ] **Step 1: Write the Python repository file**

`src/orders/repository.py`:

```python
"""Order persistence, kept deliberately small."""

from __future__ import annotations


class OrderRecord:
    """One stored order."""

    def __init__(self, order_id: str, total: int) -> None:
        self.order_id = order_id
        self.total = total


class OrderRepository:
    """Reads and writes `OrderRecord` values."""

    def __init__(self, rows: dict[str, OrderRecord]) -> None:
        self._rows = rows

    def get(self, order_id: str) -> OrderRecord | None:
        return self._rows.get(order_id)

    async def fetch_all(self) -> list[OrderRecord]:
        return list(self._rows.values())


def build_repository() -> OrderRepository:
    return OrderRepository({})
```

A plain class rather than a `@dataclass`: whether dataclass fields become symbols is not something this plan should assume, and an uncertain shape in a fixture makes every case built on it uncertain too.

- [ ] **Step 2: Write the Python pipeline file**

`src/orders/pipeline.py`:

```python
"""The order pipeline, and the enum it advances through."""

from __future__ import annotations

from enum import Enum

from src.orders.repository import OrderRepository


class OrderStage(Enum):
    """Stages an order passes through."""

    DRAFT = "draft"
    PLACED = "placed"


class OrderPipeline:
    """Advances an order to its next stage."""

    def __init__(self, repository: OrderRepository) -> None:
        self.repository = repository

    def advance(self, order_id: str) -> OrderStage:
        return OrderStage.PLACED


def run_pipeline(pipeline: OrderPipeline, order_id: str) -> OrderStage:
    return pipeline.advance(order_id)
```

`OrderStage` is here on purpose: an enum whose members are assignments is the shape ADR-0029 had to fix, and no fixture currently contains one.

- [ ] **Step 3: Write the TypeScript file**

`src/web/handlers.ts`:

```typescript
export interface OrderView {
  id: string;
  total: number;
}

export type OrderList = OrderView[];

export class OrderController {
  constructor(private readonly base: string) {}

  async load(id: string): Promise<OrderView> {
    return { id, total: 0 };
  }
}

export function formatTotal(view: OrderView): string {
  return `${view.total}`;
}

export const ORDERS_PATH = "/orders";
```

- [ ] **Step 4: Write the JavaScript file**

`src/web/widgets.js`:

```javascript
export function renderOrder(view) {
  return `<li>${view.id}</li>`;
}

export const renderList = (views) => views.map(renderOrder).join("");

export default function mount(node, views) {
  node.innerHTML = renderList(views);
}
```

An arrow function assigned to a const and a default export: two shapes `tsjs_app` does not contain.

- [ ] **Step 5: Write the test file**

`tests/test_pipeline.py`:

```python
from src.orders.pipeline import OrderPipeline
from src.orders.repository import OrderRepository


def test_pipeline_advances() -> None:
    pipeline = OrderPipeline(OrderRepository({}))
    assert pipeline.advance("o1")
```

This exists so `RELATED_TESTS` has something to resolve — import-and-call on a class, which is ADR-0021's `static_resolved` tier.

- [ ] **Step 6: Declare the fixture**

In `tests/evaluation/cases/dataset.json`, add to the `fixtures` array, after the `malicious_unsupported` entry:

```json
{"id":"symbol_breadth","root":"symbol_breadth","kind":"symbol-breadth","snapshots":[{"id":"breadth-v1","members":["src/orders/repository.py","src/orders/pipeline.py","src/web/handlers.ts","src/web/widgets.js","tests/test_pipeline.py"]}]}
```

**Edit the array surgically.** The file is hand-formatted; a `json.dumps` rewrite reformats every line and buries the change.

- [ ] **Step 7: Admit the fixture to scoring**

In `src/codeatlas/evaluation/engine_adapter.py`, add `"symbol_breadth"` to `SUPPORTED_FIXTURES`:

```python
SUPPORTED_FIXTURES = (
    "python_app",
    "docs_config",
    "mixed_app",
    "tsjs_app",
    "git_changes",
    "symbol_breadth",
)
```

The comment above that tuple records that it was frozen since Phase 1 and understated two metrics for four phases (ADR-0017). Leaving a new fixture out of it would repeat exactly that.

- [ ] **Step 8: Dump what the engine actually extracts**

**Do not write a single query case before running this.** The gold ranges in Task 2 must come from the engine, not from counting lines by eye — on 2026-08-14 a hand-declared evidence range was wrong and the engine's was right, and the corpus rule is that the engine wins unless it contradicts itself.

```bash
uv run python - <<'PYEOF'
import tempfile
from pathlib import Path
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest

root = Path("tests/evaluation/cases/fixtures/symbol_breadth")
with tempfile.TemporaryDirectory() as ws:
    with connect(Path(ws) / "e.sqlite") as conn:
        apply_migrations(conn)
        s = build_services(conn)
        repo = s.registration.register(RegisterRepositoryRequest(path=str(root)))
        s.indexing.index(repo.repository_id)
        rows = conn.execute(
            "SELECT f.relative_path, sy.kind, sy.qualified_name, sy.start_line, sy.end_line "
            "FROM symbols sy JOIN files f ON f.file_id = sy.file_id "
            "ORDER BY f.relative_path, sy.start_line"
        ).fetchall()
        print(f"{len(rows)} symbols")
        for r in rows:
            print(f"  {r[0]:34} {r[1]:16} {r[2]:32} {r[3]}-{r[4]}")
        print("--- relations ---")
        for r in conn.execute(
            "SELECT kind, source_hint, target_hint, derivation FROM relations ORDER BY kind"
        ).fetchall():
            print(f"  {r[0]:14} {r[1]} -> {r[2]}  [{r[3]}]")
PYEOF
```

**Record the output in the handoff.** It is the evidence that the fixture yields enough material; if it reports fewer than ~25 non-module symbols, stop and extend the fixture before writing cases, because the alternative is duplicate questions and that is what Finding 2 rules out.

- [ ] **Step 9: Confirm nothing existing moved**

Adding a fixture must not change what any existing case retrieves. Regenerate and diff:

```bash
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-4.json \
  --markdown-output docs/evaluation/baseline-phase-4.md
git diff --stat docs/evaluation/baseline-phase-4.json
```

Expected at this point: **no change at all.** The fixture exists and is admitted, but no case references it, and `predict_exact_symbols` only indexes fixtures a case names. A diff here means the fixture changed something it should not have — investigate before continuing.

- [ ] **Step 10: Commit**

```bash
git add tests/evaluation/cases/fixtures/symbol_breadth tests/evaluation/cases/dataset.json src/codeatlas/evaluation/engine_adapter.py
git commit -m "test(evaluation): a fixture built for symbol breadth"
```

---

### Task 2: Twenty-three cases

**Files:**
- Modify: `tests/evaluation/cases/queries.json` (append 23 cases, `q041`–`q063`)
- Modify: `tests/evaluation/cases/dataset.json` (`expected_query_count` 40 → 63)
- Modify: `tests/evaluation/test_dataset.py:25,27`, `tests/evaluation/test_cli.py:22,45`, `tests/evaluation/test_runner.py:190,227`
- Modify: `docs/evaluation/baseline-phase-{0,3,4}.{json,md}`

**Interfaces:**
- Consumes: fixture id `symbol_breadth`, snapshot id `breadth-v1`, and the symbol inventory from Task 1 Step 8.

- [ ] **Step 1: Find every hardcoded count in one pass**

Task 3's lesson was that adding one case touched nine counts found over three separate full-suite runs. Do it once:

```bash
grep -rnE "(^|[^0-9])(40|63)([^0-9]|$)" tests/ --include=*.py | grep -iE "quer|case"
```

Expected hits: `test_dataset.py:25`, `test_dataset.py:27`, `test_cli.py:22`, `test_cli.py:45`, `test_runner.py:190`, `test_runner.py:227`. Also check the fixture count, which becomes 7:

```bash
grep -rn "fixtures.*6\|6.*fixtures" tests/evaluation/*.py
```

- [ ] **Step 2: Write the cases, expectations first**

Append to the `cases` array in `tests/evaluation/cases/queries.json`, matching the existing hand-formatting exactly. **Declare each expectation before running anything**, then let Step 4 correct only what the engine contradicts.

The intent spread — chosen so the corpus stops being `EXACT_SYMBOL`-heavy:

| Intent | New cases | Ids |
| --- | ---: | --- |
| `EXACT_SYMBOL` | 10 | q041–q050 |
| `CALLERS` | 3 | q051–q053 |
| `DEPENDENCIES` | 3 | q054–q056 |
| `EXPORTS` | 3 | q057–q059 |
| `RELATED_TESTS` | 2 | q060–q061 |
| `TRACE_FLOW` | 2 | q062–q063 |
| **total** | **23** | |

One worked example, to fix the shape — `q041`, using the range the engine reported in Task 1 Step 8 (substitute the real numbers):

```json
{
    "id":  "q041",
    "repository_fixture":  "symbol_breadth",
    "snapshot_id":  "breadth-v1",
    "question":  "Where is OrderRepository defined?",
    "intent":  "EXACT_SYMBOL",
    "expected_abstention":  false,
    "expected_symbols":  [
                             "OrderRepository"
                         ],
    "expected_relations":  [

                           ],
    "expected_evidence":  [
                              {
                                  "file_path":  "src/orders/repository.py",
                                  "symbol":  "OrderRepository",
                                  "start_line":  14,
                                  "end_line":  24,
                                  "evidence_id":  "q041-e1",
                                  "snapshot_id":  "breadth-v1"
                              }
                          ],
    "warnings":  [

                 ],
    "limitations":  [

                    ],
    "forbidden_claims":  [
                             "OrderRepository writes to a database."
                         ]
}
```

The remaining 22 follow that shape. Two rules that are not obvious:

1. **A graph case needs `query_subject`.** For `CALLERS`, `DEPENDENCIES`, `EXPORTS` and `TRACE_FLOW`, `expected_symbols` is the *answer* and the subject is not in it (ADR-0018). "Who calls `renderOrder`?" expects `renderList` and `mount`, and must declare `"query_subject": "renderOrder"`. Omitting it makes the harness query the answer instead of the question.
2. **A relation expectation names qualified endpoints** (ADR-0035), and `IMPORTS` targets the *bound symbol*, not the module (ADR-0039). `src.orders.pipeline IMPORTS OrderRepository`, never `... IMPORTS repository`.

- [ ] **Step 3: Update the counts**

`dataset.json`: `"expected_query_count": 40` → `63`. Then the six test assertions found in Step 1, 40 → 63.

- [ ] **Step 4: Validate, and let the engine correct the ranges**

```bash
uv run python -m codeatlas.evaluation.cli validate --dataset tests/evaluation/cases
uv run pytest tests/evaluation -q
```

Expected: `status: valid`, 63 query cases, and `test_expectations_name_real_symbols` passing — that test indexes every fixture any case names, so it covers `symbol_breadth` automatically.

Where the engine disagrees with a declared range, **the engine is right unless the corpus contradicts itself** (ADR-0003, ADR-0031, ADR-0036). Correct the expectation on that reasoning and say so in the handoff; do not correct it because a metric improved.

- [ ] **Step 5: Confirm the denominator actually reached 50**

This is the whole point of the task and deserves its own check rather than being inferred from the metric:

```bash
uv run python -c "
from pathlib import Path
from codeatlas.evaluation.dataset import load_dataset, SYMBOL_INTENTS
from codeatlas.evaluation.engine_adapter import SUPPORTED_FIXTURES
d = load_dataset(Path('tests/evaluation/cases'))
n = len([c for c in d.query_cases
         if c.intent in SYMBOL_INTENTS and c.expected_symbols
         and c.repository_fixture in SUPPORTED_FIXTURES])
print('scored symbol-intent cases:', n)
print('one miss would score:', (n - 1) / n)
"
```

Expected: `50` and `0.98`. **If it is not 50, the task is not done** — 49 gives 0.9796 and the target stays inexpressible.

- [ ] **Step 6: Regenerate the three live baselines**

```bash
uv run python scripts/run_evaluation.py null-baseline --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-0.json --markdown-output docs/evaluation/baseline-phase-0.md
uv run python scripts/run_phase3_baseline.py --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-3.json --markdown-output docs/evaluation/baseline-phase-3.md
uv run python scripts/run_phase4_baseline.py --dataset tests/evaluation/cases \
  --json-output docs/evaluation/baseline-phase-4.json --markdown-output docs/evaluation/baseline-phase-4.md
```

**`baseline-phase-1` and `-2` stay frozen as history. Do not regenerate them.**

- [ ] **Step 7: Read the new numbers before deciding anything**

```bash
git diff docs/evaluation/baseline-phase-4.json
```

**The threshold rule, which is the most likely thing to interrupt this task.** If `exact_symbol_resolution` now falls below 0.98:

- **do not adjust the threshold;**
- **do not adjust or remove the failing case;**
- record the number, name the cases that missed, and **stop for a ruling.**

ADR-0032 and ADR-0033 are the precedent for how that conversation goes. A real number below the target is the outcome ADR-0033 has been waiting for since the target became inexpressible — it is a result, not a regression.

Expect `symbol_recall_at_10` and the evidence rates to move as well, because 23 new cases join those denominators. Attribute each movement in the handoff, and say plainly that denominator growth is **not** improvement.

- [ ] **Step 8: Mutation-check the new cases**

23 cases that all pass on the first run prove nothing. Pick the two that carry the most weight — one `EXACT_SYMBOL` and one graph case — and break the behaviour each claims to measure:

```bash
cp src/codeatlas/evaluation/engine_adapter.py /tmp/engine_adapter.py.orig
```

Mutate `_ranked_symbols` to reverse its ordering, run
`uv run pytest tests/evaluation -q`, and confirm the affected cases fail. Restore **from the copy**:

```bash
cp /tmp/engine_adapter.py.orig src/codeatlas/evaluation/engine_adapter.py
grep -c MUTATION src/codeatlas/evaluation/engine_adapter.py   # expect 0
git diff --stat src/codeatlas/evaluation/engine_adapter.py    # expect empty
```

- [ ] **Step 9: Gates**

```bash
uv run pytest -q
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

Read every exit code from the process. The gate scripts now end `exit 0`, so their log and their exit code agree.

- [ ] **Step 10: Commit**

```bash
git add tests/evaluation/cases/queries.json tests/evaluation/cases/dataset.json tests/evaluation docs/evaluation
git commit -m "test(evaluation): twenty-three symbol cases, taking the scored corpus to fifty"
```

---

### Task 3: Close out WS-1

**Files:**
- Modify: `docs/plans/PLAN.md` (register row; append a handoff)
- Modify: `docs/superpowers/plans/2026-08-14-post-closeout-program.md` (Tasks 4–5, progress table)
- Modify: `documentation/memory.md`

- [ ] **Step 1: Replace the corpus register row**

```markdown
| ~~Grow the symbol corpus toward 50 cases~~ | **CLOSED 2026-08-15.** Scored symbol-intent cases 27 → **50**, so `exact_symbol_resolution`'s 0.98 finally tolerates one miss (0.9800) instead of silently requiring 27/27 — the condition ADR-0033 left open. It needed **23** cases, not the ~13 the program plan estimated, and it needed a **new fixture**: the five existing ones hold only ~20 distinct symbol-shaped targets between them, already queried by the existing 27, so more cases against them would have padded the denominator rather than added coverage. `symbol_breadth` leaves the other five byte-identical | — |
```

- [ ] **Step 2: Update the program plan**

Mark Tasks 4 and 5 done, and record the two corrections — 23 rather than 13, and a new fixture rather than more cases — so the next estimate starts from the measured shape.

- [ ] **Step 3: Append the handoff**

Newest entries go at the **top** of the Handoff Log. It must record: the symbol dump from Task 1 Step 8; the confirmed denominator of 50 from Task 2 Step 5; every moved metric with its attribution, stating plainly which moved by denominator growth rather than engine change; the mutation checks; and exact commands with exit codes.

- [ ] **Step 4: Append to `documentation/memory.md`**

The transferable lessons:
  1. **Check the arithmetic of a threshold before growing a corpus toward it.** "~13 more" would have landed on 40, where one miss still scores 0.975 and the target is as inexpressible as before.
  2. **Count the material, not the cases.** Five fixtures held ~20 distinct symbols; the corpus already asked about all of them.
  3. **Every symbol-shaped intent feeds `exact_symbol_resolution`**, not just `EXACT_SYMBOL` — so corpus growth and graph coverage are the same job.

- [ ] **Step 5: Commit and merge**

```bash
git add docs/ documentation/
git commit -m "docs: close WS-1 with the symbol corpus at fifty scored cases"
```

---

## Self-Review

**Spec coverage.** WS-1 Task 4 ("grow the symbol cases toward 50") is Tasks 1–2; its Step 4 threshold rule is Task 2 Step 7, kept verbatim including "stop and report". WS-1 Task 5 ("close out": run gates, update register rows, append a handoff naming what moved and why, mutation-check anything that passed first time) is Task 2 Steps 8–9 plus Task 3. The owner's 2026-08-15 ruling — a new dedicated fixture — is Task 1.

**Placeholder scan.** No TBDs. All five fixture files are given verbatim. The 23 cases are *not* all written out, and that is deliberate rather than a placeholder: their gold line ranges must come from the engine dump in Task 1 Step 8, and inventing 23 sets of line numbers here would produce exactly the hand-declared ranges that were wrong on 2026-08-14. What is fixed instead is the full shape of one case, the exact id-to-intent allocation for all 23, and the two non-obvious rules (`query_subject` on graph cases, qualified relation endpoints).

**Type consistency.** Fixture id `symbol_breadth` and snapshot id `breadth-v1` are introduced in Task 1 Step 6 and used in Task 2's case JSON and the Step 5 verification. `SUPPORTED_FIXTURES` is the tuple in `engine_adapter.py`; `SYMBOL_INTENTS` is the frozenset in `dataset.py`. Case ids `q041`–`q063` are allocated once, in Task 2 Step 2's table.

**Risks, stated rather than discovered.**

1. **The fixture may yield fewer symbols than 23 cases need.** Task 1 Step 8 checks this *before* any case is written, and says to extend the fixture rather than write duplicate questions.
2. **The threshold may go red.** That is the point of the task and the most likely interruption; Task 2 Step 7 states the rule up front so it is a decision rather than a surprise.
3. **Adding a fixture could disturb existing cases.** Task 1 Step 9 pins that to a no-op diff before any case references it, so a disturbance is caught while only one variable has changed.
4. **`query_subject` is easy to forget** on graph cases and fails in a confusing way — the harness queries the answer. Called out at the point of use.

**What this plan deliberately does not do.** It does not touch any existing case, fixture, or threshold; ADR-0003 forbids it and every metric movement here should be attributable to addition alone.
