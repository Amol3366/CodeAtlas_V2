# Document Sections Report As Deleted — Investigation and Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Editing a large Markdown file must not report its unchanged sections as deleted. Today, editing two Markdown documents produced **524 `SYMBOL_DELETED` findings at high severity** for headings that exist in both states, driving `overall_risk` to `high`.

**Architecture:** Diagnose before fixing. The cause is **not known**, and the last five investigations of this shape found the *instrument* at fault rather than the engine (ADR-0017, 0018, 0024, 0027, 0038). Task 1 corrects a wrong published claim; Task 2 builds a seconds-long reproduction so the loop is not the 15-minute real preflight; Task 3 identifies the cause with the harness; Tasks 4–5 fix and re-measure. **Task 3 may conclude the fix belongs somewhere this plan does not predict** — that is an acceptable outcome, and Task 3's deliverable is a written cause, not a code change.

**Tech Stack:** Python 3.12, pytest, the existing `analysis/symbol_diff.py` and `parsing/document_parser.py`. No new dependency.

**Spec:** No separate spec. This is a defect found on 2026-08-13 while verifying ADR-0044; the Deferred Register entry in `docs/plans/PLAN.md` and the Evidence section below stand in for one. A new ADR is written in Task 5 if the fix changes a modelling decision.

## Global Constraints

- `AGENTS.md` is the release-blocking contract; `docs/plans/PLAN.md` is live status. Append handoffs, never rewrite them.
- **Test-first.** No production code without a test observed failing first. Mutation-check every fix, and run the mutation from a **file copy** — `git checkout --` has twice reverted the fix along with the mutation (ADR-0022, ADR-0042).
- Do not edit the evaluation corpus to move a number (ADR-0003). If an expectation is wrong, fix it on the ADR-0031/0036 test: an expectation must name something the engine can produce.
- Gates before any completion claim: `uv run pytest -q`, `uv run ruff check src tests scripts apps`, `uv run mypy --no-incremental src tests scripts apps`, `powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync`, and `check_phase7.ps1 -SkipSync`. Record exact commands and exit codes read from the tools.
- **Never run a gate concurrently with another pytest invocation.** Both use `.test-tmp` and collide with `FileExistsError`; a gate that fails this way is void, not a result.
- If a version constant changes (`PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION`, `CHUNKER_VERSION`), say so explicitly — it makes every snapshot stale and forces a re-index.

## Evidence Already Gathered

Measured on 2026-08-13 against this repository. Do not re-derive these; start from them.

| Fact | Value |
| --- | --- |
| Findings from editing 7 files | 526 total: **524 `SYMBOL_DELETED`**, 2 `DOCUMENT_CHANGED` |
| Matching `SYMBOL_ADDED` findings | **0** |
| `overall_risk` | `high` |
| Sections in the two edited Markdown files | `PLAN.md` **497**, `memory.md` **8** |
| Section names are unique within `PLAN.md` | yes — 0 duplicates |
| Both views parse an identical `PLAN.md` to | **497 symbols, 0 diagnostics**, byte-identical reads |

**The deletion count is within noise of the total section count of the edited files.** This is not a few names failing to match — it is the shape of *nothing pairing at all* for those files. A cause that explains only some sections is the wrong cause.

**Ruled out already:**

- **Text decoding.** The first report of this defect claimed "a decode step is corrupting the em dash," from a title that printed as `2026-07-25T15:15:00Z � P0-SETUP started`. **That was the terminal, not the product.** The JSON on disk holds `"2026-07-25T15:15:00Z — P0-SETUP started"` — the em dash is intact, and the file contains no U+FFFD and no cp1252 `0x97`. Task 1 corrects the record. Do not spend time here.
- **A parse failure on one side.** Both sides produce 497 symbols with zero diagnostics.
- **ADR-0044.** `PLAN.md` is neither ignored nor binary, so no filter that record added can reach it.

**Leading hypotheses, in the order Task 3 should test them:**

1. **`file_id` differs between the two states**, so ADR-0042's within-file pairing in `_pair_within_files` (`symbol_diff.py:241`) matches nothing and every occurrence falls out. This best fits "no pairing at all" plus "no additions".
2. **One side's Markdown symbols never reach the graph** that `_diff_input` (`engine.py:412`) reads, even though the parser produces them.
3. **A `DOCUMENT_SECTION`-specific branch** in `_classify_key` or `_fold_nested_changes` drops the added half, turning an add+delete pair into a bare delete.

---

### Task 1: Correct the published cause

The register and `documentation/memory.md` both assert a decoding defect that does not exist. They are committed and pushed, and the register is what the next person reads. Correct it before doing anything else — a wrong lead in the authority costs more than the bug.

**Files:**
- Modify: `docs/plans/PLAN.md` (the Deferred Register row for this item)
- Modify: `documentation/memory.md` (the ADR-0044 entry's paragraph on this finding)

- [ ] **Step 1: Replace the register row's cause sentence**

Remove the sentence beginning `One title renders as` and its `so **a decoding step is corrupting the em dash**` clause. Replace with:

```markdown
The mojibake in the first report (`2026-07-25T15:15:00Z � P0-SETUP started`) was **the reporting terminal, not the product** — the JSON on disk holds `—` intact, with no U+FFFD and no cp1252 `0x97` anywhere in the file. That lead is dead; do not follow it. What the numbers say instead: the two edited Markdown files hold **505 sections** between them against **524 deletions**, so this is *nothing pairing at all*, not a few names mismatching.
```

Change the `Reopens when` cell to:

```markdown
Someone reproduces it in-process on a two-heading Markdown file — see `docs/superpowers/plans/2026-08-13-document-sections-report-as-deleted.md`
```

- [ ] **Step 2: Correct the same claim in memory.md**

Replace the sentence `One title reads ... **a decode step is corrupting an em dash**, which would make a section name unequal to its own twin. Start there, not at the pairing logic.` with:

```markdown
      The em dash in that title was **my terminal**, not the product — the JSON
      holds `—` intact. I published a cause I had not verified and it was
      wrong; the correction is the lesson. What the numbers actually say is that
      **505 sections produced 524 deletions**, so nothing paired at all.
```

- [ ] **Step 3: Commit**

```bash
git add docs/plans/PLAN.md documentation/memory.md
git commit -m "docs: correct the published cause of the document-section deletions

The mojibake was the reporting terminal, not a decode defect in the
product: the JSON on disk holds — intact, with no U+FFFD and no
cp1252 0x97. A cause published without verification sends the next
reader down a dead path, which is more expensive than the bug."
```

---

### Task 2: A reproduction that runs in seconds

The only current reproduction is a real preflight over this repository, which takes **more than 15 minutes** — the engine parses both full states on every analysis, O(repository) not O(change), which `docs/operations/change-analysis.md` already documents. No diagnosis loop can run at that speed. Build the harness first.

**Files:**
- Create: `tests/unit/test_document_section_diff.py`
- Reference (do not modify): `tests/unit/test_symbol_diff.py:24-60` for the `_parse` / `_input` convention this file follows

**Interfaces:**
- Consumes: `compute_symbol_changes(base: SymbolDiffInput, target: SymbolDiffInput) -> tuple[SymbolChange, ...]` from `codeatlas.analysis.symbol_diff`; `DocumentParser().parse(ParseRequest(...)) -> ParseResult` with `.symbols`
- Produces: `_sections(markdown: str, path: str = "docs/notes.md", file_id: str | None = None) -> tuple[FileRecord, tuple[SymbolRecord, ...]]`, used by Tasks 3 and 4

- [ ] **Step 1: Write the failing test**

```python
"""Editing a Markdown document must not delete the sections it keeps.

A real preflight over this repository reported 524 `SYMBOL_DELETED`
findings for headings present in both states. These tests reproduce that
in-process, because the engine parses both full states on every analysis
and the real loop is a quarter of an hour.
"""

from __future__ import annotations

from codeatlas.analysis.symbol_diff import SymbolDiffInput, compute_symbol_changes
from codeatlas.contracts import ChangeKind, SymbolKind
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.domain.symbols import SymbolRecord
from codeatlas.parsing.document_parser import DocumentParser
from codeatlas.parsing.registry import ParseRequest

_PATH = "docs/notes.md"


def _sections(
    markdown: str,
    path: str = _PATH,
    file_id: str | None = None,
) -> tuple[FileRecord, tuple[SymbolRecord, ...]]:
    """Parse `markdown` into the section symbols the diff consumes."""
    content = markdown.encode("utf-8")
    resolved_id = file_id or f"file_{path}"
    record = FileRecord(
        file_id=resolved_id,
        relative_path=path,
        display_path=path,
        content_hash=f"hash_{len(content)}",
        size_bytes=len(content),
        line_count=content.count(b"\n") + (0 if content.endswith(b"\n") else 1),
        language="markdown",
        classification=FileClassification.DOCUMENTATION,
    )
    result = DocumentParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id=resolved_id,
            relative_path=path,
            language="markdown",
            content=content,
        )
    )
    return record, result.symbols


def _input(symbols: tuple[SymbolRecord, ...], record: FileRecord) -> SymbolDiffInput:
    return SymbolDiffInput(
        symbols=symbols,
        relations=(),
        file_paths={record.file_id: record.relative_path},
    )


_BEFORE = """# Title

## Kept One

Text.

## Kept Two

Text.
"""

_AFTER = """# Title

## Inserted

New text.

## Kept One

Text.

## Kept Two

Text.
"""


def test_inserting_a_section_does_not_delete_the_sections_it_keeps() -> None:
    base_record, base_symbols = _sections(_BEFORE)
    target_record, target_symbols = _sections(_AFTER)

    changes = compute_symbol_changes(
        _input(base_symbols, base_record),
        _input(target_symbols, target_record),
    )

    deleted = [
        change.qualified_name
        for change in changes
        if change.change_kind is ChangeKind.DELETED
    ]
    assert deleted == []
```

- [ ] **Step 2: Run it and record what happens**

Run: `uv run pytest tests/unit/test_document_section_diff.py -q`

**Either outcome is information, and the plan branches here:**

- **It fails** (deletions listed): the defect reproduces at the `compute_symbol_changes` boundary with identical `file_id`s on both sides. Hypothesis 1 is wrong; go to Task 3 Step 2.
- **It passes**: the defect is *not* in symbol pairing on matching ids, and the real preflight differs in some input the harness does not yet model. Go to Task 3 Step 1, which widens the harness rather than the guesswork.

Record the actual output in the handoff either way. A reproduction that does not reproduce is the most valuable result in this plan, because it eliminates the largest hypothesis.

- [ ] **Step 3: Commit the harness**

```bash
git add tests/unit/test_document_section_diff.py
git commit -m "test: reproduce document-section deletions in-process

The only prior reproduction was a 15-minute preflight over the whole
repository, which is not a diagnosis loop."
```

---

### Task 3: Name the cause in writing

**Deliverable: a written cause with the observation that proves it — not a code change.** Do not begin Task 4 until this is written down. Every one of the last five investigations of this shape produced a fix to the *measurement* rather than the engine, and the way that was caught each time was insisting on the cause before the patch.

**Files:**
- Modify: `tests/unit/test_document_section_diff.py` (add the discriminating tests below)

- [ ] **Step 1: Test hypothesis 1 — mismatched `file_id`**

Add this test. It models the one thing the Task 2 harness holds constant that the real engine may not: the two sides' file identity.

```python
def test_sections_pair_even_when_the_two_states_use_different_file_ids() -> None:
    """The base and target sides may not agree on a file's id.

    ADR-0042 made occurrences pair *within their file first*. If the id
    differs across states, nothing pairs within a file, which is the shape
    the real report showed: every section deleted, none added.
    """
    base_record, base_symbols = _sections(_BEFORE, file_id="file_base")
    target_record, target_symbols = _sections(_AFTER, file_id="file_target")

    changes = compute_symbol_changes(
        _input(base_symbols, base_record),
        _input(target_symbols, target_record),
    )

    deleted = [
        change.qualified_name
        for change in changes
        if change.change_kind is ChangeKind.DELETED
    ]
    assert deleted == []
```

Run: `uv run pytest tests/unit/test_document_section_diff.py -q`

If this fails while Task 2's test passes, **the cause is file identity, not Markdown** — and it affects every file kind, with Markdown merely being where it was noticed. Say so in the handoff; it widens the defect considerably.

- [ ] **Step 2: If neither test reproduces, compare the real inputs**

Run the two states through the engine's own path and diff the two symbol sets directly, rather than guessing what differs:

```bash
uv run python - <<'PY'
import sys; sys.path.insert(0, "src")
from pathlib import Path
from codeatlas.analysis.states import DirectoryStateView, GitBlobStateView
from codeatlas.parsing.document_parser import DocumentParser
from codeatlas.parsing.registry import ParseRequest

root = Path(".").resolve()
path = "docs/plans/PLAN.md"
out = {}
for side, view in (("base", GitBlobStateView(root, "HEAD~1")), ("target", DirectoryStateView(root))):
    content = view.read_file(path)
    result = DocumentParser().parse(ParseRequest(
        repository_id="repo_1", snapshot_id="s", file_id="f",
        relative_path=path, language="markdown", content=content))
    out[side] = {s.qualified_name: (s.symbol_id, s.kind, s.start_line) for s in result.symbols}
    print(side, "symbols:", len(out[side]))
only_base = set(out["base"]) - set(out["target"])
print("names only in base:", len(only_base), sorted(only_base)[:5])
same_name_different_id = [
    n for n in set(out["base"]) & set(out["target"])
    if out["base"][n][0] != out["target"][n][0]
]
print("same name, different symbol_id:", len(same_name_different_id), same_name_different_id[:5])
PY
```

`HEAD~1` is used deliberately: it is the last state in which `PLAN.md` differed from the working tree, which is the condition the defect was observed under.

- [ ] **Step 3: Write the cause into the plan file**

Append a `## Cause` section to this plan naming the mechanism and the observation that proves it. If the finding is that the engine is right and the *report* is wrong, say that plainly — it is the fifth-most-likely outcome by history and the most likely by base rate.

- [ ] **Step 4: Commit the diagnosis**

```bash
git add tests/unit/test_document_section_diff.py docs/superpowers/plans/2026-08-13-document-sections-report-as-deleted.md
git commit -m "test: identify the cause of the document-section deletions"
```

---

### Task 4: Fix it

**Files:** unknown until Task 3. The candidates, with what each would mean:

| If the cause is | Fix in | Note |
| --- | --- | --- |
| `file_id` mismatch across states | `src/codeatlas/analysis/symbol_diff.py:241` `_pair_within_files` — pair on `file_paths[file_id]` (the path) rather than the raw id | Affects all file kinds; add a Python-symbol test too |
| Symbols missing from one graph | `src/codeatlas/analysis/engine.py:412` `_diff_input` or its caller | Check whether unchanged files are populated on both sides |
| A `DOCUMENT_SECTION` branch dropping the add | `_classify_key` / `_fold_nested_changes` | ADR-0042 folds config ancestors on dotted path; sections may hit that |

- [ ] **Step 1: Confirm the Task 3 test is still failing**

Run: `uv run pytest tests/unit/test_document_section_diff.py -q`
Expected: FAIL, naming the deleted sections. If it now passes, something else changed — stop and find out what.

- [ ] **Step 2: Write the minimal fix**

Change only what the failing test requires. Do not restructure neighbouring code, and do not fix the oversized-tracked-file item or the ADR-0030 ruling while here — both are separate register entries with their own triggers.

- [ ] **Step 3: Run the file, then the full suite**

```bash
uv run pytest tests/unit/test_document_section_diff.py -q
uv run pytest -q
```
Expected: the new tests pass; **2197 passed, 3 skipped** or higher, with no test newly failing.

- [ ] **Step 4: Mutation-check the fix**

```bash
cp src/codeatlas/analysis/symbol_diff.py /tmp/symbol_diff.bak.py
# invert or neutralise the changed condition, then:
uv run pytest tests/unit/test_document_section_diff.py -q   # must FAIL
cp /tmp/symbol_diff.bak.py src/codeatlas/analysis/symbol_diff.py
uv run pytest tests/unit/test_document_section_diff.py -q   # must PASS
```

Restore **from the copy**, never with `git checkout --`: that has twice reverted the fix along with the mutation.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(analysis): a kept document section is not a deleted one"
```

---

### Task 5: Re-measure, record, and gate

**Files:**
- Create: `docs/adr/0045-<slug>.md` **only if** the fix changes a modelling decision. A pairing-key correction with no behaviour question does not need one; the handoff carries it.
- Modify: `docs/adr/README.md` (only if an ADR was written), `docs/plans/PLAN.md` (register row → CLOSED, plus the handoff entry), `documentation/memory.md`

- [ ] **Step 1: Re-measure on the real repository**

```bash
git stash push -u -m "measure-clean-tree"
# edit one heading into docs/plans/PLAN.md, then:
uv run codeatlas impact <repository_id> --db <scratch>/probe.db --format json > impact-after.json
git stash pop
```

Expect the deletion count to fall to 0 for sections that still exist. Budget 15+ minutes for the run and **state the tree state with the number** — a dirty-tree count and a clean-tree count are different measurements, and conflating them is how the first report of this defect became unreliable.

- [ ] **Step 2: Run the gates, one at a time**

```bash
uv run ruff check src tests scripts apps
uv run mypy --no-incremental src tests scripts apps
powershell -ExecutionPolicy Bypass -File scripts/check_phase4.ps1 -SkipSync
powershell -ExecutionPolicy Bypass -File scripts/check_phase7.ps1 -SkipSync
```

Never concurrently — they share `.test-tmp`. Expect all three baselines to reproduce byte-for-byte; if one moves, the fix changed engine behaviour on the corpus and the handoff must explain each moved metric before the work is complete.

- [ ] **Step 3: Note whether the corpus could see this**

State it explicitly either way. Four consecutive defects were invisible to the corpus (ADR-0016, ADR-0029, ADR-0042, ADR-0043) and ADR-0044 made five. **If the baselines do not move, that is the sixth instance and belongs in the handoff as evidence for growing the corpus**, not as reassurance.

- [ ] **Step 4: Close the register row and append the handoff**

Set the Deferred Register row to `CLOSED <date>` with the measured before/after. Append a handoff entry following the schema in `docs/plans/PLAN.md`: outcome, files, contracts/migrations, exact verification commands with exit codes read from the tools, mutation checks, limitations, and next task.

- [ ] **Step 5: Commit, merge, push**

```bash
git add -A
git commit -m "docs: record the document-section deletion fix"
git checkout main
git merge --no-ff <branch> -m "Merge branch '<branch>'"
git push origin main
```

---

## Self-Review

**Spec coverage.** No separate spec; the Evidence table is the requirement set. Every ruled-out cause has a task that keeps it ruled out (Task 1 corrects the decode claim in the record; Task 2's harness pins the parse-equality fact). Every leading hypothesis has a discriminating step in Task 3.

**Placeholders.** Task 4's files are genuinely unknown before Task 3 — that is a diagnosis dependency, not a placeholder, and the candidate table names the exact file and line for each branch. Every other step carries its real content.

**Type consistency.** `_sections` and `_input` are defined once in Task 2 and used unchanged in Tasks 3 and 4. `_sections` takes `file_id` as a keyword from the start, so Task 3 Step 1 needs no signature change. `ChangeKind.DELETED`, `SymbolKind.DOCUMENT_SECTION`, and `FileClassification.DOCUMENTATION` are the names the codebase uses.

**The risk this plan carries.** Task 3 may find that the engine is correct and the reported finding is a rendering or classification artifact. The plan is written so that outcome is a success with a two-line fix in Task 4, rather than a failure that invites forcing a change into the engine.

---

## Cause

**Not a product defect. The measurement was taken against a working tree that
was being rewritten while the analysis read it.**

The analysis ran from 16:20 to 16:32 on 2026-08-13. During those twelve minutes
the same session was editing `docs/plans/PLAN.md`, `documentation/memory.md`,
and `tests/integration/test_state_views.py` with scripts that write via
`Path.write_text`, which **truncates before it writes**. The analysis read
`PLAN.md` inside that window and saw an empty file.

### The observation that proves it

Feeding the engine the real base content and an **empty** target reproduces the
reported number exactly:

| Target state at read time | Findings |
| --- | --- |
| Empty (0 bytes) | **496 `SYMBOL_DELETED`** |
| Truncated mid-write (5 KB of 699 KB) | 491 `SYMBOL_DELETED` + 1 `DOCUMENT_CHANGED` |
| The real edited file | **2 `DOCUMENT_CHANGED`, 0 deletions** |

The reported artifact contains **496** `SYMBOL_DELETED` for `PLAN.md` out of 497
sections, with only 9 additions across all files. An exact match on a
four-digit-precision count is not a coincidence.

### What was eliminated on the way, and should stay eliminated

1. **Text decoding** — retracted in Task 1; the em dash was intact on disk.
2. **Symbol pairing at `compute_symbol_changes`** — inserting a section into a
   document deletes nothing, with matching **or mismatched** `file_id`s
   (both tests pass, Task 2 and Task 3).
3. **Parse divergence between the two views** — both parse `PLAN.md` to the same
   497 symbols, same ids, same names, zero diagnostics.
4. **Scale** — 50, 200, and 497 sections all behave correctly.
5. **The view pairing** — `GitBlobStateView` against `DirectoryStateView` in a
   real Git repository behaves correctly.
6. **The real content** — the actual before/after `PLAN.md` bytes produce 2
   findings and no deletions.

### The lesson, which is the part worth keeping

This is the **sixth** consecutive investigation of this shape to find the
instrument at fault rather than the engine (ADR-0017, 0018, 0024, 0027, 0038).
The plan predicted that outcome from base rate and was written so it would be a
success rather than a failure; that is why Task 3's deliverable was a written
cause and not a patch. **A plan that only accommodates the bug being real
produces a fix to an engine that was already correct.**

The specific trap: a 12-minute analysis over a live working tree is not an
atomic observation, and the observer was mutating the observed. Preflight has no
defence against this and arguably needs none — Git behaves the same way — but
the measurement discipline does: **do not edit the tree you are measuring.**

## Revised remaining work

Tasks 4 and 5 are replaced by Task 4' below. There is no engine fix, so there is
no ADR: nothing about the product's behaviour was decided or changed.

### Task 4': Record the finding and keep the guards

- [ ] Keep `tests/unit/test_document_section_diff.py`. Both tests pass today and
      neither is redundant: nothing else in the suite asserts that editing a
      Markdown document preserves its untouched sections, and the corpus has no
      change case over a document at all. They are the regression guard the
      absent corpus coverage would otherwise have provided.
- [ ] Add a third test pinning the truncation behaviour, so the diagnosis is
      reproducible rather than a paragraph someone has to trust.
- [ ] Close the Deferred Register row as **not a defect**, with the reproduction
      table above.
- [ ] Record the limitation in `docs/operations/change-analysis.md`: analysing a
      working tree that is being written produces findings about the write, not
      about the change.
- [ ] Run the gates, append the handoff, commit, merge, push.
