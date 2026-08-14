# Post-Closeout Program — Everything Still Open

> **For agentic workers:** This is a **program**, not a single plan. Each workstream below produces working, verifiable software on its own and gets its own plan file when it is picked up. WS-1 is planned to task level here because it is the largest and the one whose design decisions bind the others. Use superpowers:executing-plans or superpowers:subagent-driven-development per workstream, not across them.

**Goal:** Close out everything the Deferred Register still carries, in an order where each step's result is usable before the next begins.

**Architecture:** Six workstreams. Two are blocked on a product ruling only the owner can give, and those rulings are asked once, up front, rather than discovered mid-task. One (WS-1) is multi-day and is the reason the others keep recurring. Two are deliberately *not* being done and are listed so nobody re-proposes them.

**Tech Stack:** Python 3.12, pytest, the existing evaluation runner and dataset models. No new dependency in any workstream.

**Spec:** The Deferred Register in `docs/plans/PLAN.md` is the authority for what is open. Where this program and the register disagree, the register wins and this file is the bug.

## Global Constraints

Apply to every workstream. Copied from `AGENTS.md`, the register, and lessons paid for in the last week.

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live status; append handoffs, never rewrite them.
- **Test-first.** No production code without a test observed failing first, and mutation-check every fix.
- **Revert a mutation from a file copy, never `git checkout --`.** It has twice reverted the fix along with the mutation (ADR-0022, ADR-0042).
- **Never run two gates, or a gate and a pytest, concurrently.** They share `.test-tmp` and collide with `FileExistsError`. A gate that fails that way is void, not a result — this cost a wasted run on 2026-08-13.
- **Do not edit the tree you are measuring.** A preflight over a live working tree is not atomic; a file caught mid-write reads as empty and reports every symbol in it deleted. This produced 496 false findings on 2026-08-13.
- **ADR-0003: the corpus is never edited to move a number.** *Adding* coverage is legitimate; *changing* an expectation requires the ADR-0031/0036 justification — the expectation named something the engine cannot produce, or contradicted itself.
- Declare any change to `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION`, or `CHUNKER_VERSION` explicitly: it makes every snapshot stale and forces a re-index.
- Gates before any completion claim, run one at a time: `uv run pytest -q`, `ruff check src tests scripts apps`, `mypy --no-incremental src tests scripts apps`, `check_phase4.ps1 -SkipSync`, `check_phase7.ps1 -SkipSync`. Record exact commands and exit codes read from the tools.

---

## Decision Gates — needed before WS-3 and WS-5

Both are product questions. Neither has a technically-correct answer, and each determines the whole implementation of its workstream. **Ask once, before starting either.**

**Gate A — an oversized tracked file.** `GitDiffAdapter.archive` raises `ScanLimitExceededError` when any tracked file exceeds `max_file_bytes` (2 MB), so one committed 3 MB CSV makes a repository impossible to preflight. The directory scan merely skips the same file with a `TOO_LARGE` warning.

- *Skip it, like the scanner does* — consistent with ADR-0044's ruling that preflight sees only what it would index; the file becomes invisible to preflight.
- *Keep refusing* — a preflight that silently ignores part of the tree is arguably worse than one that declines; but then the refusal needs a better error and a documented remedy.

**Gate B — module granularity (ADR-0030).** When a concept is documented at module level and the corpus declares the method implementing it, does the module satisfy the question? Nothing fails today (`symbol_recall_at_10` 0.9286 against 0.90). The ruling unblocks the RRF coarse-chunk work in WS-5, whose obvious lever trades an evidence hit for a symbol hit.

---

## Sequencing

| # | Workstream | Cost | Blocked by | Why here |
| --- | --- | --- | --- | --- |
| **WS-0** | Housekeeping | 15 min | — | Trivial, and one item is an unrecorded observation that will otherwise be rediscovered |
| **WS-1** | Grow the evaluation corpus | 3–5 days | — | Six defects have argued for it; everything else keeps being found by hand |
| **WS-2** | Subject and file path on `Finding` | ½–1 day | — | Self-contained, additive, no migration |
| **WS-3** | Oversized tracked file | ½ day | **Gate A** | Small once ruled |
| **WS-4** | Phase 4 evidence rates, per case | 1–2 days | WS-1 preferred | Better done *after* the corpus grows, or it investigates a 27-case artifact |
| **WS-5** | Module granularity + RRF bias | 1–2 days | **Gate B** | The lever needs corpus-wide measurement, which WS-1 improves |
| **WS-6** | Lexical intents and relation paths | ½–1 day | — | Last of ADR-0034's four causes; gates `relation_path_recall` |

## Progress — updated 2026-08-14 (resume here)

| Item | State |
| --- | --- |
| WS-0 | **done** — `5f255b8`, `860c726` |
| WS-1 Task 1 (`expected_findings` counts) | **done** — `fc7af34`, merged `7f834c0` |
| WS-1 Task 2 (document-section case c025) | **done** — `f28a300`, merged `06bcff2` |
| WS-1 Task 3 (blind-spot cases) | **done** — `a6dba3c`. Three of four; 3c is inexpressible, see below |
| WS-1 Task 4 (symbol cases toward 50) | **next** |
| WS-1 Task 5, WS-2 … WS-6 | not started |

The corpus is **28 change cases / 40 query cases**.

### What Task 3 changed about the plan

**3c cannot be written and was not.** `predict_changes` compares two
`DirectoryStateView`s (`engine_adapter.py:581`); ADR-0044's fix is inside
`GitBlobStateView`, which the corpus never constructs. Both directory sides
already apply the same ignore rules, so a tracked-but-ignored file is absent
from both states and the case would pass with the fix reverted. It is a
register row now, not a case. **Expressing it needs a Git-backed fixture
shape, which is a WS of its own, not a case.**

**Two more stale premises, so assume the next one is stale too.** 3a's target
already existed (c012 edits a nested YAML leaf and has counted since Task 1),
so c026 was retargeted to `app.toml` — untouched by any case, and on
ADR-0041's parsed-value path rather than YAML's subtree-text path. And 3d's
first draft used a Markdown file, where line endings dissolve into the parsed
section text before the diff sees them; it only bites on a code file. **The
mutation check caught that**, which is the argument for mutation-checking
every case that passes first time.

**Budget was accurate**: half a day, driven by the guard exemptions rather
than the counts. The nine hardcoded counts were found in one `grep` pass as
planned. Three *guards* then needed narrow exemptions — the corpus LF check,
the empty-prediction check, and `Row.change` — none of which the plan
anticipated, and each of which had to keep its value rather than be widened.

### What Task 2 changed about the plan

**Adding one change case is a six-file edit, not a two-file one.** It touched
**nine** hardcoded counts across five files, found over *three* separate
full-suite runs. Task 3's four cases are therefore **half a day, not an hour**.

Before starting 3a, find every count in one pass instead of three:

```bash
grep -rnE "(^|[^0-9])(24|25)([^0-9]|$)" tests/ --include=*.py | grep -iE "change|case"
```

Per case, the full checklist:

1. variant tree (`base/` + `target/` overlays under `cases/variants/<fixture>/<slug>/`)
2. the case in `cases/changes.json` — **insert surgically**; a `json.dumps`
   rewrite reformats all 2030 lines
3. `expected_change_count` in `cases/dataset.json`
4. a `Row` in `tests/unit/test_findings.py` — **appended last**, because two
   tests index `ROWS` positionally
5. a `Case` in `tests/unit/test_impact_cases.py` (plus its fixture symbol map)
6. regenerate `baseline-phase-0`, `-3`, `-4`; **never** `-1` or `-2`

### Two fixes worth doing before Task 3

Both are small, both address things that cost time today, and neither is
required:

- **`exit 0` at the end of `check_phase7.ps1`.** It prints "verification
  completed" and exits with whatever the last native command left, so its log
  and its exit code can disagree — which is how several runs today were read as
  green without `$?` being captured.
- **A lockfile around `.test-tmp`, plus clean-on-start.** Four void runs in two
  days: three from concurrent pytest, one from residue left by the previous
  gate. Task 3 is four more cycles of that exact shape.

### Still open from today, unattributed

One `check_phase7` run exited 1 while printing every step as passing, and did
not reproduce on a clean `main` or on a re-run with the same changes. **Not
diagnosed, not guessed at.** If it recurs, chase it before trusting a green.

**WS-1 first among the substantial ones**, because WS-4 and WS-5 are both measurements and measuring against a corpus this thin is what produced five instrument-not-engine findings.

---

## WS-0: Housekeeping

- [x] **Delete four merged branches** — done 2026-08-14

```bash
git branch -d document-sections-not-deleted line-endings-are-not-a-change \
              preflight-duplicate-findings preflight-sees-what-it-indexes
```

All are fully merged into `main`; `-d` (not `-D`) refuses if that is ever untrue. The 2026-08-10 closeout pruned merged branches for the same reason: `git branch` should not imply unmerged work.

- [x] **Record the preflight performance observation in the Deferred Register** — done 2026-08-14

Mentioned twice on 2026-08-13 and never written down. Row to add:

```markdown
| **Preflight takes >15 minutes on a 664-file repository** | **OPEN — an observation, not yet a measured defect.** The declared target is warm p95 ≤ 10 s, but that is on the declared *fixture* profile; nobody has measured a real codebase. `docs/operations/change-analysis.md` already explains the cost — the engine parses **both full states** on every analysis, O(repository) not O(change), and the snapshot-reuse path ADR-0005 decision 2 describes was never implemented. Observed 2026-08-13 during ADR-0044 verification: one `impact` run exceeded a 10-minute budget and a second took ~12 minutes | Someone measures it properly, or a user reports it |
```

- [x] **Commit** — `860c726`

```bash
git add docs/plans/PLAN.md
git commit -m "docs: record the preflight runtime observation on a real repository"
```

---

## WS-1: Grow the evaluation corpus

**Goal:** The corpus can see the classes of defect that have been escaping it, and `exact_symbol_resolution`'s 0.98 target becomes arithmetically expressible.

**Why:** Six defects were invisible to it — ADR-0016 (tiered test edges), ADR-0029 (memberless containers), ADR-0041 (nested config keys), ADR-0042 (duplicate findings), ADR-0043 (CRLF), ADR-0044 (tracked-but-ignored files) — plus the 2026-08-13 false report, where the corpus had no document change case to catch a regression with. Every one was found by hand on a real repository.

**Current state, measured 2026-08-14:** 40 query cases (16 `EXACT_SYMBOL`, 6 `CONFIG_LOOKUP`, 5 `TRACE_FLOW`, 4 `DOCUMENT_LOOKUP`, 3 `DEPENDENCIES`, 2 `CALLERS`, 1 each `RELATED_TESTS` / `EXPORTS` / `CONCEPTUAL` / `POLICY`), 24 change cases, 6 fixtures (`python_app`, `tsjs_app`, `docs_config`, `mixed_app`, `git_changes`, `malicious_unsupported`), each with a parallel tree under `cases/variants/`.

### The risk this workstream carries, stated before it starts

**Adding cases will move the aggregates, and may turn a green gate red.** That is the *point* — ADR-0033 records that 0.98 across 27 cases silently means 27/27, and widening the denominator is what makes the target mean something. But a red gate is a real outcome that needs a decision, not a surprise mid-task.

**Rule for this workstream:** if a threshold fails after adding cases, **do not adjust the threshold and do not adjust the case.** Record the new number, name the cases that fail, and stop for a ruling. ADR-0032 and ADR-0033 are the precedent for how that conversation goes.

### Task 1: Make `expected_findings` count

`expected_findings` is a **set of codes**, and a set cannot count. This is why c012 emitted two `CONFIG_VALUE_CHANGED` findings for one edit **from Phase 4 until 2026-08-11** with no metric ever seeing it, and c014 the same for `PACKAGE_SCRIPT_CHANGED`. Every duplicate-finding defect added afterwards is invisible for the same reason. Do this first: it changes what all later cases can assert.

**Files:**
- Modify: `src/codeatlas/evaluation/dataset.py` (the `ChangeCase` model)
- Modify: `src/codeatlas/evaluation/runner.py` (finding comparison)
- Modify: `tests/evaluation/cases/changes.json` (24 cases)
- Test: `tests/evaluation/test_dataset.py`, `tests/evaluation/test_change_adapter.py`

- [x] **Step 1: Write the failing test** — a case declaring one `CONFIG_VALUE_CHANGED` against an engine emitting two must **fail**, where today it passes.
- [x] **Step 2: Run it, watch it pass wrongly** (today's behaviour), confirming the gap is real before changing the model.
- [x] **Step 3: Extend `ChangeCase`.** It is a `ContractModel` with `extra="forbid"`, so a case cannot carry a new shape until the model does — this exact constraint blocked the ADR-0016 corpus work and sent it to a second surface instead. Prefer a backward-compatible representation (a list retaining duplicates) over a new field, so the 24 existing cases need no edit beyond those that were genuinely wrong.
- [x] **Step 4: Run the dataset validator.** `uv run python -m codeatlas.evaluation.cli validate --dataset tests/evaluation/cases` must report `status: valid`, 24 change cases.
- [x] **Step 5: Regenerate `baseline-phase-4`** and state in the handoff which metrics moved and why. If none moved, say that too — it means no current case has a duplicate, which is information.
- [x] **Step 6: Commit.**

### Task 2: A document change case

The gap that let the 2026-08-13 false report go unnoticed for a day: **no change case edits a Markdown document.** The `docs_config` fixture has documents, but no case changes one and asserts what should come out.

**Files:** `tests/evaluation/cases/variants/docs_config/…` (a new variant tree), `tests/evaluation/cases/changes.json`

- [x] **Step 1:** Add a variant that inserts one section into an existing document and edits the body of another.
- [x] **Step 2:** Declare `expected_changed_symbols` naming the inserted section (added) and the edited one (modified), and **no deletions**. Use bare headings — ADR-0031 is the single naming rule and ADR-0036 asserts expectations name symbols the engine can produce.
- [x] **Step 3:** Run `uv run pytest tests/evaluation -q`; the ADR-0036 validator must accept every new expectation.
- [x] **Step 4:** Regenerate the baseline, record movement, commit.

### Task 3: Change cases for the four blind spots

One case per class of defect that escaped. Each is small; together they are the return on this whole workstream.

- [x] **3a — nested configuration keys (ADR-0041).** Landed as **c026**, on `app.toml` rather than YAML: c012 already covered the YAML leaf and has asserted its count since Task 1. TOML takes ADR-0041's parsed-value path, which nothing else exercised.
- [x] **3b — a duplicate-prone name across files (ADR-0042).** Landed as **c027**. `cache.ttl` in two files, one edited. Mutation confirms the `2N` shape: four occurrences, two findings.
- [x] ~~**3c — a tracked-but-ignored file (ADR-0044).**~~ **Not written — structurally inexpressible**, and deliberately not committed as a case that always passes. The corpus compares two `DirectoryStateView`s; ADR-0044's fix is in `GitBlobStateView`, which no evaluation path builds. Now a Deferred Register row.
- [x] **3d — CRLF (ADR-0043).** Landed as **c028**, on a **code** file. A Markdown target does not work: a section's hash comes from parsed text, so line endings never reach the diff. Bytes written explicitly and held through checkout by one `-text` line in `.gitattributes`, backed by a test that they still differ.
- [x] **Step 4:** Dataset validator reports `status: valid`, 28 change cases. Baseline regenerated once, at the end.

### Task 4: Grow the symbol cases toward 50

**Files:** `tests/evaluation/cases/queries.json`, plus fixture additions where an existing fixture has nothing suitable.

- [ ] **Step 1:** Add ~13 `EXACT_SYMBOL` cases across the existing fixtures, each with a gold file-and-line range. Spread across Python, TS, and JS — today's 16 lean Python.
- [ ] **Step 2:** Run the ADR-0036 validator; every `expected_symbols[0]` must be a symbol `find_exact` can produce, because that string **is the query the harness issues**.
- [ ] **Step 3:** Regenerate `baseline-phase-4` and `baseline-phase-0`/`-3` as the gate requires. **`baseline-phase-1` and `-2` stay frozen as history — do not regenerate them.**
- [ ] **Step 4:** Report `exact_symbol_resolution` at the new denominator. If it drops below 0.98, **stop and report** rather than adjusting anything: at ~50 cases the target is finally expressible, and a real number below it is the outcome ADR-0033 was waiting for.
- [ ] **Step 5:** Commit.

### Task 5: Close out

- [ ] Run all gates, one at a time.
- [ ] Update the register rows for "Grow the symbol corpus toward 50 cases" and the corpus-blindness notes.
- [ ] Append a handoff naming, per metric, what moved and why — and explicitly whether any *new* case failed on first run. **A new case that passes immediately proves nothing**; the same argument as tests written after the code. Where a case passes first time, mutation-check it by breaking the behaviour it claims to measure.

---

## WS-2: Subject and file path on `Finding`

**The defect:** a `Finding` carries no subject and no file path, so two *legitimate* findings sharing a code and title render identically and collide on `FindingsList`'s React key. Recorded as ADR-0042 follow-up 1.

**Shape:** additive contract change — new optional fields on the `Finding` model, populated by the engine, surfaced in the JSON/Markdown/SARIF renderers and the web `FindingsList`. No migration; `contract_version` stays `1.1` if the fields are optional. Cross-adapter contract tests must cover all three renderers.

**Watch for:** SARIF has its own location model; map to it rather than inventing a parallel field. Do not let this grow into a `Finding` redesign.

---

## WS-3: Oversized tracked file — **needs Gate A**

Today's behaviour is pinned by `test_a_tracked_file_over_the_size_limit_fails_the_whole_comparison`. Whichever way Gate A goes, that test changes: either it becomes a skip-and-warn assertion, or it stays and gains a better error message plus a documented remedy. The ADR-0044 record already states the asymmetry, so this closes with a handoff rather than a new ADR unless the ruling changes product behaviour — which "skip it" would.

---

## WS-4: Phase 4 evidence rates, per case

`containing_evidence_rate` 0.6824 and `containing_evidence_recall_at_10` 0.8305, both unmet, cause unknown.

**The standing prior, now confirmed six times, is that the instrument is wrong rather than the engine** (ADR-0017, 0018, 0024, 0027, 0038, and the 2026-08-13 investigation). Investigate **per case** before calling anything a defect, and expect the artifact to be unhelpful: it stores aggregates only, so this needs an evaluation run with per-case output.

Prefer running after WS-1 — a per-case investigation over 27 cases tells you less than one over 50.

---

## WS-5: Module granularity and RRF bias — **needs Gate B**

ADR-0030 records that the obvious lever promotes the method the corpus declares **and** demotes the chunk currently providing a rank-1 containment hit: it trades an evidence hit for a symbol hit. So this needs corpus-wide measurement rather than a one-case fix, which is the second reason to do WS-1 first.

---

## Deliberately not doing

Listed so they are not re-proposed as work:

- **Code signing** — a purchasing decision, not an engineering task. The packaged executable stays unsigned and SmartScreen warns on first run.
- **Seven Chromium-skipped Playwright tests** — an upstream renderer defect on client-side navigation. Firefox runs all seven, so coverage is not lost. Re-count rather than copy the figure forward if it is ever quoted; it has understated itself twice.
- **The 1.05 GB packaged semantic tree** — accepted at the Phase 7 activation gate; the torch cost was known when the semantic layer was admitted.

---

## Self-Review

**Coverage.** Every open register row maps to a workstream: pid-reuse/relation-path/IMPORTS/ephemeral are already closed; oversized file → WS-3; markdown deletions → closed 2026-08-13; corpus growth → WS-1; `relation_path_recall` gate → WS-6; RRF bias and ADR-0030 → WS-5; Phase 4 evidence rates → WS-4; unsigned exe, Chromium skips, 1.05 GB → "deliberately not doing". `Finding` subject → WS-2. Preflight runtime → WS-0 adds the row it currently lacks.

**Placeholders.** WS-2 through WS-6 are specified to scope, risk, and exit criteria but not to step level — deliberate, because each gets its own plan when picked up, and step-level detail written days early against a moving codebase is fiction. WS-0 and WS-1 are the ones executable now and are at step level.

**Consistency.** `expected_findings` (Task 1) must land before 3b, which asserts a count — noted in 3b. WS-1 Task 4's threshold risk is stated in the workstream preamble rather than only at the step, because it is the decision most likely to interrupt execution.

**The honest risk.** WS-1 is 3–5 days of unglamorous data work whose visible output is "the same gates, still green, over more cases". Its value only shows up as defects it catches later — which is exactly the argument that went unmade for six defects.
