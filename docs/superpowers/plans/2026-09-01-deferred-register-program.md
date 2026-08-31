# Deferred Register Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close or correct every open row in the Deferred Register, and land the
three symbol-identity mechanisms ADR-0071 named but did not start.

**Architecture:** The audit runs first and may shrink everything after it. The
identity work adds one new `LanguageAdapter` hook — `discriminator()` — feeding
`ensure_unique_symbol_ids` alongside the existing `signature`, appended to the
id hash **only when present** so each language's ids move in its own task and
nowhere else. No schema change: a discriminator is an id-construction input like
the ordinal, not stored evidence like the signature.

**Tech Stack:** Python 3.12, `uv`, tree-sitter query-backed parsers, SQLite,
pytest, Ruff, MyPy, PowerShell gate scripts.

**Spec:** `docs/superpowers/specs/2026-09-01-deferred-register-program-design.md`

## Global Constraints

- **`AGENTS.md` is the contract** and overrides this plan. `docs/plans/PLAN.md`
  is the canonical status; append handoffs, never rewrite them.
- **Test-first for executable behaviour.** A test that has never failed has not
  been shown to test anything.
- **Do not claim a test passed unless it was executed in this environment.**
- **Gate before claiming completion:** `scripts/check_phase4.ps1 -SkipSync` must
  exit 0, and `scripts/check_real_repos.ps1` must exit 0 for Tasks 3–5.
- **Baseline to compare against** (2026-09-01, clean tree at `7c8250f`):
  `GATE_EXIT_CODE=0`, 2398 passed, 3 skipped, lint clean, types clean over 389
  files.
- **Every identity change bumps `PARSER_BUNDLE_VERSION`** in
  `src/codeatlas/parsing/registry.py:59` (currently `"1.8.0"`) with a comment in
  the same style as the 1.8.0 block above it, and **forces a reindex**.
- **`SCHEMA_VERSION` stays 14.** If any task believes it needs a migration, stop
  and re-open the design rather than adding one.
- **A register row is closed only with a citation** to the record that
  superseded it.

## File Structure

| File | Responsibility | Tasks |
| --- | --- | --- |
| `scripts/report_symbol_collisions.py` | **New.** Reproducible collision census over the five real repositories — the instrument ADR-0071's numbers were taken with, which was never committed | 1 |
| `docs/plans/PLAN.md` | Register rows corrected; handoffs appended | 1–6 |
| `docs/adr/0072-*.md` … `0074-*.md` | One ADR per identity mechanism | 3, 4, 5 |
| `src/codeatlas/domain/symbols.py:41` | `ensure_unique_symbol_ids` — gains an optional parallel `discriminators` argument | 3 |
| `src/codeatlas/parsing/query_backed/profile.py:59` | `LanguageAdapter` protocol — gains `discriminator()` | 3 |
| `src/codeatlas/parsing/query_backed/engine.py:231` | `TagsBackedParser` — collects discriminators and passes them through | 3 |
| `src/codeatlas/parsing/query_backed/languages/scala.py:53` | `ScalaAdapter.discriminator` — declaration form | 3 |
| `src/codeatlas/parsing/query_backed/languages/rust.py` | `RustAdapter.discriminator` — the trait | 4 |
| `src/codeatlas/parsing/query_backed/languages/go.py` | `GoAdapter.discriminator` — enclosing scope | 5 |
| `src/codeatlas/parsing/registry.py:59` | `PARSER_BUNDLE_VERSION` bump | 3, 4, 5 |
| `tests/unit/test_symbol_identity_collisions.py` | Regression tests for each mechanism | 3, 4, 5 |
| `scripts/measure_phase4_perf.py` | Realistic profile: Markdown-heavy, realistic file sizes | 2 |

---

### Task 1: Register staleness audit

**Files:**
- Create: `scripts/report_symbol_collisions.py`
- Modify: `docs/plans/PLAN.md` (register rows + appended handoff)
- Test: `tests/unit/test_report_symbol_collisions.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `report_collisions(root: Path) -> CollisionReport` where
  `CollisionReport` is a frozen dataclass with fields
  `groups: int`, `separated: int`, `ordinal: int`,
  `by_language: dict[str, tuple[int, int, int]]`. Tasks 3–5 use it to prove a
  mechanism's class falls to zero.

- [ ] **Step 1: Write the failing test for the census**

```python
# tests/unit/test_report_symbol_collisions.py
"""The instrument ADR-0071's numbers were taken with, now committed.

ADR-0071 reports 1202 collision groups over five repositories, 221 separated
by signature and 981 left on the ordinal. Those numbers came from an ad-hoc
probe that was never committed, so no later task can reproduce or contradict
them. This module tests the committed replacement.
"""

from __future__ import annotations

from pathlib import Path

from scripts.report_symbol_collisions import report_collisions


def test_a_java_overload_pair_is_one_group_separated_by_signature(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Gson.java"
    source.write_text(
        "class Gson {\n"
        "  void toJson(String s) {}\n"
        "  void toJson(int i) {}\n"
        "}\n",
        encoding="utf-8",
    )
    report = report_collisions(tmp_path)
    assert report.groups == 1
    assert report.separated == 1
    assert report.ordinal == 0


def test_a_scala_companion_pair_is_one_group_left_on_the_ordinal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Thing.scala"
    source.write_text("trait Thing\nobject Thing\n", encoding="utf-8")
    report = report_collisions(tmp_path)
    assert report.groups == 1
    assert report.separated == 0
    assert report.ordinal == 1
```

- [ ] **Step 2: Run the tests and confirm they fail for the right reason**

Run: `uv run pytest tests/unit/test_report_symbol_collisions.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scripts.report_symbol_collisions'`.
A failure for any other reason means the harness is wrong, not the code.

- [ ] **Step 3: Implement the census**

Walk the tree with the existing parser registry, group symbols by the
pre-disambiguation `symbol_id`, and classify each group of size > 1 by whether
its members carry distinct signatures.

```python
# scripts/report_symbol_collisions.py
"""Reproducible collision census (ADR-0071's numbers, as a committed tool).

A collision is two symbols in one file sharing a qualified name and a kind --
the four inputs to `symbol_id` reduce to those two once the repository and the
path are fixed. Grouping on the emitted `symbol_id` would report zero forever,
because `ensure_unique_symbol_ids` has already made them distinct by the time
`parse` returns.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path

from codeatlas.parsing.registry import ParseRequest, default_registry

_LANGUAGE_BY_SUFFIX = {
    ".java": "java",
    ".scala": "scala",
    ".go": "go",
    ".rs": "rust",
    ".py": "python",
}


@dataclasses.dataclass(frozen=True)
class CollisionReport:
    groups: int
    separated: int
    ordinal: int
    by_language: dict[str, tuple[int, int, int]]


def report_collisions(root: Path) -> CollisionReport:
    registry = default_registry()
    tallies: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for path in sorted(root.rglob("*")):
        language = _LANGUAGE_BY_SUFFIX.get(path.suffix)
        if language is None or not path.is_file():
            continue
        parser = registry.parser_for(language)
        if parser is None:
            continue
        result = parser.parse(
            ParseRequest(
                repository_id="census",
                snapshot_id="census",
                file_id=str(path),
                relative_path=str(path.relative_to(root)),
                language=language,
                content=path.read_bytes(),
            )
        )
        buckets: dict[tuple[str, str], list[str | None]] = defaultdict(list)
        for symbol in result.symbols:
            buckets[(symbol.qualified_name, symbol.kind.value)].append(
                symbol.signature
            )
        for signatures in buckets.values():
            if len(signatures) == 1:
                continue
            tally = tallies[language]
            tally[0] += 1
            if len(set(signatures)) == len(signatures):
                tally[1] += 1
            else:
                tally[2] += 1
    by_language = {
        language: (tally[0], tally[1], tally[2])
        for language, tally in sorted(tallies.items())
    }
    return CollisionReport(
        groups=sum(tally[0] for tally in by_language.values()),
        separated=sum(tally[1] for tally in by_language.values()),
        ordinal=sum(tally[2] for tally in by_language.values()),
        by_language=by_language,
    )
```

`by_language` is what Tasks 3–5 assert against — a total alone cannot show that
Scala fell to zero while Java did not move.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `uv run pytest tests/unit/test_report_symbol_collisions.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Reproduce ADR-0071's numbers over the five real repositories**

Run the census over gson, cobra, gin, ripgrep and scalaz — the same five
`scripts/check_real_repos.py` uses.

Expected, from ADR-0071: **1202 groups, 221 separated, 981 ordinal**; gson
99/52/47, scalaz 1077/169/908, ripgrep 21/0/21, gin 4/0/4, cobra 1/0/1.

**If the totals differ, that is a finding, not a bug to hide.** Record the
measured numbers and reconcile them against ADR-0071 in the handoff.

- [ ] **Step 6: Establish what gson's 47 unseparated Java groups are**

ADR-0071 names remedies for Scala, Go and Rust — **934 of the 981** — and none
for these 47. Sample them from the census and record what construct produces
them (overloads differing only by generic parameter, `cfg`-gated duplicates, or
something else). Produce a one-paragraph finding, not a fix.

- [ ] **Step 7: Audit every open register row**

For each row carrying an `OPEN` disposition, apply the three checks in the spec:
dated cross-check against later ADRs, trigger liveness, and re-measurement where
a number exists. Two are already known and must land in this pass:

  - the row claiming *"632 s of a 635 s preflight is `parse_base` +
    `parse_target`"* — **closed, citing ADR-0064**, which corrects ADR-0060,
    ADR-0061 and ADR-0062 and measures parsing at 2.5%;
  - the row asking for a ruling on *what invalidates a stored parse* —
    **withdrawn**, citing ADR-0063 (arithmetic) and ADR-0064 (proportion). The
    ruling is not answered because the change it authorises pays nothing.

Also correct `src/codeatlas/domain/symbols.py:67`, whose docstring still says
"The query-backed tier reports `signature is None` for every language" — untrue
since ADR-0071 for Java and Scala.

- [ ] **Step 8: Disambiguate the `~~original entry~~` notation**

Mark every archived-original row explicitly (the nested-config row closed by
ADR-0041 is the worked example), so a reader cannot mistake a closed defect for
an open one by reading top-down.

- [ ] **Step 9: Write the capture recipes and the decision brief**

Three capture recipes — concurrent-suite failure, the phantom `check_phase7`
`exit 1`, the Firefox cross-suite leak — each naming the exact artefacts to
keep (full output, `.e2e-tmp` database, exit code, step log). Then the decision
brief: the **four** rulings in the spec's "Open questions", each with evidence
and options, for the user. A fifth — what invalidates a stored parse — is
withdrawn by Step 7 rather than put to the user.

- [ ] **Step 10: Run the gate**

Run: `scripts/check_phase4.ps1 -SkipSync`
Expected: `GATE_EXIT_CODE=0`, 2400 passed (2398 + the two new tests), lint and
types clean.

- [ ] **Step 11: Commit**

```bash
git add scripts/report_symbol_collisions.py tests/unit/test_report_symbol_collisions.py docs/plans/PLAN.md src/codeatlas/domain/symbols.py
git commit -m "audit(register): census committed, two preflight rows closed on ADR-0064"
```

---

### Task 2: Preflight — re-measure, then decide

**Files:**
- Modify: `scripts/measure_phase4_perf.py`
- Modify: `docs/evaluation/phase-4-baseline-environment.md`
- Modify: `docs/plans/PLAN.md`

**Interfaces:**
- Consumes: Task 1's corrected rows.
- Produces: measured warm p95 on a real repository, and a realistic-profile
  perf harness. No interface other tasks depend on.

- [ ] **Step 1: Re-measure preflight and `impact` on a real repository**

Run each three times and take the median, on an otherwise idle machine.
ADR-0064 recorded preflight at **21.56 s** post-fix, against **635.59 s**
before. The live register row records `impact` runs of 10–12 minutes observed
2026-08-13 — **five days before that 29x**, so they are expected to be stale.

Record the numbers whatever they are. If preflight has regressed above ~60 s,
the resolution row's trigger has fired and Step 4 becomes mandatory.

- [ ] **Step 2: Give the perf harness a realistic profile**

`measure_phase4_perf.py` generates ~15-line Python modules and no Markdown.
ADR-0064 showed the consequence: `DOCUMENTS` is 117,471 of 160,687 references
on a real repository, the generated corpus has none, and the resolution exponent
of 1.14 fitted on it was **no evidence at all**. Add a profile with realistic
file sizes and a Markdown-heavy tree, so the dominant reference class is
present.

- [ ] **Step 3: Re-run the sweep on the realistic profile and record the exponent**

Expected: an exponent materially above 1.14 if the quadratic term is now
present. If it is not above 1.14, say so — the generated corpus may still be
missing the term, and that is the finding.

- [ ] **Step 4: Profile resolution's residual 3.55 s, or decline in writing**

ADR-0064 invites this explicitly: 3.55 s across 161,343 references "is not
obviously optimal". Profile it. **If the measurement says no change pays,
decline it in writing** and close the row citing the measurement — declining
with evidence is a complete outcome here.

- [ ] **Step 5: Run the gate**

Run: `scripts/check_phase4.ps1 -SkipSync`
Expected: `GATE_EXIT_CODE=0`. Note the wall-clock and whether the machine was
idle, which the 2026-09-01 baseline could not claim.

- [ ] **Step 6: Commit**

```bash
git add scripts/measure_phase4_perf.py docs/evaluation/phase-4-baseline-environment.md docs/plans/PLAN.md
git commit -m "perf: realistic harness profile, and preflight re-measured post-ADR-0064"
```

---

### Task 3: Scala companion declaration form (908 groups)

**Files:**
- Create: `docs/adr/0072-a-companion-is-identified-by-its-declaration-form.md`
- Modify: `src/codeatlas/domain/symbols.py:41`
- Modify: `src/codeatlas/parsing/query_backed/profile.py:59`
- Modify: `src/codeatlas/parsing/query_backed/engine.py:231`
- Modify: `src/codeatlas/parsing/query_backed/languages/scala.py:53`
- Modify: `src/codeatlas/parsing/registry.py:59`
- Test: `tests/unit/test_symbol_identity_collisions.py`

**Interfaces:**
- Consumes: `report_collisions` from Task 1.
- Produces:
  - `LanguageAdapter.discriminator(self, node: Any, source: bytes) -> str | None`
  - `ensure_unique_symbol_ids(symbols, parser_bundle_version, discriminators=None)`
    where `discriminators: tuple[str | None, ...] | None` is positionally
    parallel to `symbols`.
  Tasks 4 and 5 implement `discriminator` on their own adapters and change
  nothing else.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_symbol_identity_collisions.py — append

def test_a_scala_companion_pair_keeps_its_ids_when_a_sibling_is_inserted() -> None:
    """`trait Thing` and `object Thing` collide, and the ordinal is unstable.

    Neither declares parameters, so both yield `signature is None` (ADR-0071)
    and identity falls to document order. Insert a third same-named declaration
    above them and the later member's id moves, which reports a symbol as
    deleted and re-added when nothing about it changed. The declaration form
    separates them; a signature never can.
    """
    before = _parse_scala("trait Thing\nobject Thing\n")
    after = _parse_scala("class Thing\ntrait Thing\nobject Thing\n")

    object_before = _only(before, kind="object", name="Thing")
    object_after = _only(after, kind="object", name="Thing")
    assert object_before.symbol_id == object_after.symbol_id
```

Write `_parse_scala` and `_only` as module-local helpers in the same file,
following the parse helpers already there.

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -k companion -v`
Expected: FAIL — the two ids differ, because the inserted `class Thing` shifts
the object's ordinal from 1 to 2.

- [ ] **Step 3: Add the `discriminator` hook to the protocol**

```python
# src/codeatlas/parsing/query_backed/profile.py — in LanguageAdapter

    def discriminator(self, node: Any, source: bytes) -> str | None:
        """A non-parameter fact that separates a collision group, or ``None``.

        The companion to ``signature``, for the collisions a signature cannot
        reach: a Scala ``trait`` against its ``object``, a Rust method under two
        traits, a Go type declared inside two different functions. Measured over
        five real repositories, those are 934 of the 981 groups a signature
        leaves on the ordinal (ADR-0071).

        **Not stored.** A discriminator is an id-construction input like the
        ordinal, not evidence like the signature, so it needs no column and no
        migration. It does change identity, so any adapter that starts returning
        one bumps ``PARSER_BUNDLE_VERSION``.
        """
        ...
```

- [ ] **Step 4: Thread it through `ensure_unique_symbol_ids`**

```python
# src/codeatlas/domain/symbols.py

def ensure_unique_symbol_ids(
    symbols: tuple[SymbolRecord, ...],
    parser_bundle_version: str,
    discriminators: tuple[str | None, ...] | None = None,
) -> tuple[SymbolRecord, ...]:
```

and inside the loop, replacing the two lines that build the key and the id:

```python
        signature = symbol.signature or ""
        discriminator = "" if discriminators is None else (discriminators[index] or "")
        key = (symbol.symbol_id, signature, discriminator)
        ordinal = seen_signature.get(key, 0)
        seen_signature[key] = ordinal + 1
        if symbol.symbol_id not in seen_group:
            seen_group.add(symbol.symbol_id)
            continue
        parts = [symbol.symbol_id, signature]
        if discriminator:
            parts.append(discriminator)
        parts.append(str(ordinal))
        new_symbol_id = f"sym_{stable_hash(*parts)}"
```

**The conditional append is the load-bearing line.** Appending unconditionally
would move every already-stored disambiguated id in every language at once,
which is exactly the attribution ADR-0071 refused to give up. With it, only ids
whose adapter returns a discriminator move — so Task 3 moves Scala, Task 4 moves
Rust, Task 5 moves Go, and each is separately attributable.

Widen `seen_signature`'s annotation to `dict[tuple[str, str, str], int]`.

- [ ] **Step 5: Collect discriminators in the engine**

At `engine.py:231`, where `signature=self._adapter.signature(node, request.content)`
is built, collect the parallel discriminator per symbol and pass the tuple to
`ensure_unique_symbol_ids` at `engine.py:71`. The tuple must be built in the same
order as `symbols`, or the parallel index is meaningless.

- [ ] **Step 6: Implement `ScalaAdapter.discriminator`**

```python
# src/codeatlas/parsing/query_backed/languages/scala.py

    def discriminator(self, node: Any, source: bytes) -> str | None:
        """The declaration form: `trait`, `object`, `class`, or None.

        A companion pair declares no parameters, so ADR-0071's signature is
        None for both and the ordinal carries identity alone. The form is what
        actually differs, and it is stable under a sibling being inserted above.
        908 of the 981 groups a signature leaves on the ordinal are these.
        """
        form = node.type.removesuffix("_definition").removesuffix("_declaration")
        return form or None
```

Verify the node type names against the Scala grammar before trusting the string
surgery above; if the grammar names them differently, map explicitly rather than
stripping suffixes.

- [ ] **Step 7: Run the test and confirm it passes**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -v`
Expected: PASS, including every pre-existing test in the module.

- [ ] **Step 8: Prove the census moved and the counts did not**

Run the Task 1 census over scalaz. Expected: **908 ordinal groups fall to 0**
for companion pairs. Then run `scripts/check_real_repos.ps1` and confirm the
symbol counts are **identical** to the ADR-0070/0071 run —
gson 312/4414, cobra 65/854, gin 130/2045, ripgrep 229/4320, scalaz 590/17795.

**An identity change must move ids and not counts.** A changed count means the
parser started or stopped emitting symbols, which is a different bug.

- [ ] **Step 9: Bump `PARSER_BUNDLE_VERSION` to 1.9.0**

```python
# src/codeatlas/parsing/registry.py — above the constant, in the existing style
# 1.9.0 (ADR-0072): Scala emits a `discriminator` -- the declaration form -- so
# a companion `trait`/`object` pair no longer depends on document order. 908 of
# the 981 groups ADR-0071 left on the ordinal. Every Scala symbol row
# disambiguated by the 1.8.0 bundle is stale. RESOLVER_VERSION unchanged.
PARSER_BUNDLE_VERSION: str = "1.9.0"
```

- [ ] **Step 10: Write ADR-0072**

Record: the measurement before and after, that 908 groups were addressed and
**47 Java groups remain with no named mechanism**, that no migration was needed
because a discriminator is not stored, and that users must reindex.

- [ ] **Step 11: Run the gate and commit**

```bash
scripts/check_phase4.ps1 -SkipSync   # expect GATE_EXIT_CODE=0
git add src tests docs/adr/0072-a-companion-is-identified-by-its-declaration-form.md docs/plans/PLAN.md
git commit -m "feat(identity): a Scala companion is identified by its declaration form (ADR-0072)"
```

---

### Task 4: Rust trait discriminator (21 groups)

**Files:**
- Create: `docs/adr/0073-a-rust-method-is-identified-by-its-trait.md`
- Modify: `src/codeatlas/parsing/query_backed/languages/rust.py:124`
- Modify: `src/codeatlas/parsing/registry.py:59`
- Test: `tests/unit/test_symbol_identity_collisions.py`

**Interfaces:**
- Consumes: `LanguageAdapter.discriminator` and the `discriminators` argument
  from Task 3. No further change to `symbols.py` or `engine.py`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_two_trait_impls_of_one_method_name_get_distinct_ids() -> None:
    """`Display::fmt` and `Debug::fmt` are byte-identical but for the trait.

    ADR-0071 measured this as the sharpest case a signature cannot reach: both
    declare `(&self, f: &mut fmt::Formatter)`, so the parameter types are equal
    and only the enclosing `impl`'s trait differs.
    """
    symbols = _parse_rust(
        "struct S;\n"
        "impl fmt::Display for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { Ok(()) }\n"
        "}\n"
        "impl fmt::Debug for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result { Ok(()) }\n"
        "}\n"
    )
    fmts = [symbol for symbol in symbols if symbol.qualified_name.endswith("fmt")]
    assert len(fmts) == 2
    assert fmts[0].symbol_id != fmts[1].symbol_id
```

- [ ] **Step 2: Run it and confirm it fails for the right reason**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -k two_trait -v`

Expected: this may already **pass** on the ordinal — the second member is
already re-identified by ordinal, so the ids already differ. **If it passes,
the test is wrong, not the code.** Rewrite it as the stability test the Scala
one is: insert a third `impl` block above, and assert the *later* member's id is
unchanged. Only that failure demonstrates what the trait actually buys.

- [ ] **Step 3: Implement `RustAdapter.discriminator`**

```python
# src/codeatlas/parsing/query_backed/languages/rust.py

    def discriminator(self, node: Any, source: bytes) -> str | None:
        """The trait of the enclosing `impl`, or None outside a trait impl.

        Replaces the `None` ADR-0071 recorded here. A signature separates none
        of Rust's collisions -- `Display::fmt` and `Debug::fmt` declare
        byte-identical parameters -- and the trait is on the enclosing `impl`
        node, not in the parameter list. 21 of the 981 groups ADR-0071 left on
        the ordinal (ripgrep).
        """
        current = node.parent
        while current is not None:
            if current.type == "impl_item":
                declared = current.child_by_field_name("trait")
                return None if declared is None else _text(declared, source)
            current = current.parent
        return None
```

Replace the existing `signature` docstring's claim that a discriminator is
unavailable — it now is.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -v`
Expected: PASS, whole module.

- [ ] **Step 5: Prove the census moved and the counts did not**

Run the census over ripgrep: **21 ordinal groups fall to 0**. Then
`scripts/check_real_repos.ps1` — ripgrep must still report **229/4320**, and
every other repository must be unchanged from Task 3's run.

- [ ] **Step 6: Bump `PARSER_BUNDLE_VERSION` to 1.10.0, write ADR-0073, gate, commit**

```bash
scripts/check_phase4.ps1 -SkipSync   # expect GATE_EXIT_CODE=0
git add src tests docs/adr/0073-a-rust-method-is-identified-by-its-trait.md docs/plans/PLAN.md
git commit -m "feat(identity): a Rust method is identified by its trait (ADR-0073)"
```

---

### Task 5: Go enclosing scope (5 groups)

**Files:**
- Create: `docs/adr/0074-a-go-local-type-is-identified-by-its-enclosing-function.md`
- Modify: `src/codeatlas/parsing/query_backed/languages/go.py:117`
- Modify: `src/codeatlas/parsing/registry.py:59`
- Test: `tests/unit/test_symbol_identity_collisions.py`

**Interfaces:**
- Consumes: `LanguageAdapter.discriminator` from Task 3.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
def test_a_go_local_type_is_identified_by_its_enclosing_function() -> None:
    """`type key struct{}` in two functions collides, and order decides.

    cobra declares it inside four different test functions, all flattening to
    one `key` (the original ADR-0069 reproduction). The enclosing function is
    a lexical ancestor the engine already walks; a signature is not available,
    since a type declaration has no parameters.
    """
    before = _parse_go(
        "package p\n"
        "func A() { type key struct{} }\n"
        "func B() { type key struct{} }\n"
    )
    after = _parse_go(
        "package p\n"
        "func Z() { type key struct{} }\n"
        "func A() { type key struct{} }\n"
        "func B() { type key struct{} }\n"
    )
    key_in_b_before = _only(before, kind="struct", enclosing="B")
    key_in_b_after = _only(after, kind="struct", enclosing="B")
    assert key_in_b_before.symbol_id == key_in_b_after.symbol_id
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -k go_local -v`
Expected: FAIL — inserting `func Z` above shifts `B`'s ordinal and moves its id.

- [ ] **Step 3: Implement `GoAdapter.discriminator`**

```python
# src/codeatlas/parsing/query_backed/languages/go.py

    def discriminator(self, node: Any, source: bytes) -> str | None:
        """The name of the enclosing function, or None at package scope.

        Replaces the `None` ADR-0071 recorded here. Go has no overloading, so a
        signature separates none of its collisions; what differs between two
        `type key struct{}` declarations is the function each sits in. 5 of the
        981 groups ADR-0071 left on the ordinal (4 gin, 1 cobra).
        """
        current = node.parent
        while current is not None:
            if current.type in {"function_declaration", "method_declaration"}:
                named = current.child_by_field_name("name")
                return None if named is None else _text(named, source)
            current = current.parent
        return None
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `uv run pytest tests/unit/test_symbol_identity_collisions.py -v`
Expected: PASS, whole module — including the four-functions-one-`key` case that
ADR-0069 was found with.

- [ ] **Step 5: Prove the census moved and the counts did not**

Census over gin and cobra: **5 ordinal groups fall to 0**. Then
`scripts/check_real_repos.ps1` — gin **130/2045**, cobra **65/854**, unchanged.

At this point the census total should read **981 - 908 - 21 - 5 = 47 ordinal
groups remaining, all Java, all in gson** — the gap Task 1 characterised and no
task in this plan closes.

- [ ] **Step 6: Bump `PARSER_BUNDLE_VERSION` to 1.11.0, write ADR-0074, gate, commit**

```bash
scripts/check_phase4.ps1 -SkipSync   # expect GATE_EXIT_CODE=0
git add src tests docs/adr/0074-a-go-local-type-is-identified-by-its-enclosing-function.md docs/plans/PLAN.md
git commit -m "feat(identity): a Go local type is identified by its enclosing function (ADR-0074)"
```

---

### Task 6: Corpus fixture shapes

**Files:**
- Create: fixture directories under `tests/evaluation/cases/` following the
  existing group layout
- Modify: `src/codeatlas/evaluation/dataset.py` if a new fixture shape needs a
  loader change
- Modify: `docs/plans/PLAN.md`
- Test: `tests/evaluation/test_dataset.py`

**Interfaces:**
- Consumes: Task 1's audit, which may have closed some of these rows already.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Re-read the five rows this task covers**

They are, per the spec: a Git-backed change case; a fixture whose route literal
sits alone on its line; a second semantic fixture; a fixture where a matched
symbol's edge sits outside every returned chunk; and an audit for same-named
symbols resting on name-based metrics alone.

**If Task 1 closed any of them, do not build it.** Confirm against the current
register before writing a fixture.

- [ ] **Step 2: For each surviving row, add the fixture and a test that fails without it**

Each fixture must be added with a test that **fails before the fixture exists**.
A fixture whose test passes on the first run has demonstrated nothing — this is
the mutation standard the 2026-08-07 `POST /v1/models/test` work established,
and the register already carries one row about a corpus fix that restored a
number without restoring the measurement.

- [ ] **Step 3: Run dataset validation and the gate**

Run: `uv run pytest tests/contract tests/evaluation -q`, then
`scripts/check_phase4.ps1 -SkipSync`.
Expected: `GATE_EXIT_CODE=0`, and **every baseline still reproduces
byte-for-byte**. A new fixture that moves a baseline number is a finding to
report, not a baseline to regenerate.

- [ ] **Step 4: Commit**

```bash
git add tests/evaluation docs/plans/PLAN.md
git commit -m "test(evaluation): fixture shapes the corpus could not previously express"
```

---

## Not in this plan, and why

- **The three flakes** (concurrent suite, phantom `check_phase7` `exit 1`,
  Firefox cross-suite leak) get capture recipes in Task 1 and no task. Two have
  no reproduction; planning a fix for an unreproduced flake is fiction.
- **The unsigned executable, the Chromium skips, the 1.05 GB tree.** A purchase,
  an upstream browser defect, and a cost accepted at the Phase 7 gate.
- **Phase 7 recall@10 0.6667 and Phase 4 `changed_symbol_precision` 0.9375.**
  Both approved as missed by the user at their gates. Reopening either is a new
  task with its own approval.
- **A mechanism for gson's 47 Java groups.** Task 1 characterises them; nothing
  here fixes them, because no remedy has been designed and inventing one inside
  another task is how ADR-0069's follow-up produced a claim that took a full
  task to disprove.
