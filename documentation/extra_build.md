# Extra Build — the remaining work, in the order to do it

Status: current as of 2026-08-15

**Authority note.** This file is a **work plan**, not a status list. The single
authoritative record of what is open is the **Deferred Register in
`docs/plans/PLAN.md`**; `AGENTS.md` is the release-blocking contract. Where this
file and the register disagree about *whether* something is open, the register
wins and this file is the bug.

It exists because the register answers "what is open and why" but not "how would
someone actually do it" — which files, which traps, what counts as done. That is
what is written down here, per task. **Deliberately no status column**, because
`documentation/memory.md` already records the lesson that two copies of a status
list is how they drift.

**Relationship to the post-closeout program.** The workstream numbering (WS-2
through WS-6) is
`docs/superpowers/plans/2026-08-14-post-closeout-program.md`, and each task
below names its WS so the two can be matched. That file remains the record of
*why* the work was scoped this way and what its decision gates are; this file is
the current *execution order*, re-sequenced now that WS-0 and WS-1 are closed.
Two documents describing an order is exactly the drift this project keeps
paying for, so the split is deliberate and narrow: **if they disagree about
sequence, this file is newer; if they disagree about scope or rationale, the
program plan wins.** When the program is finished, delete this file rather than
leaving it to rot.

Ordering is execution order, not priority: each item is placed where its
dependencies are satisfied.

---

## Where things stand

Phases 0–7 complete with user-approved gates; the project was closed out
2026-08-10 and everything since is post-gate work. The post-closeout program
(`docs/superpowers/plans/2026-08-14-post-closeout-program.md`) has **WS-0 and
WS-1 closed**, along with both process defects (gate exit codes, test
isolation).

Corpus: **63 query cases / 28 change cases** over **7 fixtures**, with a scored
symbol-intent denominator of **50**.

Current Phase 4 baseline, for the three items below that argue from it:

| Metric                               |  Value | Target | State                                             |
| ------------------------------------ | -----: | -----: | ------------------------------------------------- |
| `exact_symbol_resolution`          | 1.0000 |   0.98 | met — and 0.98 finally*means* 0.98 at 50 cases |
| `containing_evidence_rate`         | 0.6885 |   1.00 | **unmet**                                   |
| `containing_evidence_recall_at_10` | 0.8824 |   0.90 | **unmet**                                   |
| `changed_symbol_precision`         | 0.9464 |   0.95 | unmet, closed as structural                       |
| `symbol_recall_at_10`              | 0.8879 |   0.90 | ungated on this profile (ADR-0023)                |
| `relation_path_recall`             | 0.9130 |     — | deliberately ungated until Task 3                 |

---

## The rule that governs almost all of this

**The standing prior is that the instrument is wrong, not the engine.** Seven
consecutive investigations of this shape have ended that way: ADR-0017, 0018,
0024, 0027, 0038, the 2026-08-13 document-section false report, and both
register rows corrected on 2026-08-15.

So: **investigate per case before calling anything a defect**, and expect the
measurement apparatus to be at fault first. Two of the tasks below exist only
because that prior was not applied earlier.

---

## Task 1 — Phase 4 evidence rates, per case (WS-4)

**Cost:** 1–2 days. **Blocked by:** nothing. WS-1 was its prerequisite and is
done.

**Why now.** The only remaining work that targets unmet gate targets.
`containing_evidence_rate` is 0.6885 against 1.00 and
`containing_evidence_recall_at_10` is 0.8824 against 0.90 — the latter is closer
than it has ever been, though by denominator growth on 2026-08-15 rather than by
any engine change, and it must not be quoted as improvement.

**Where to work**

- `src/codeatlas/evaluation/runner.py` — `score_query_case`, and the evidence
  scoring around lines 596–680
- `docs/evaluation/baseline-phase-4.json` — **aggregates only**, which is the
  first obstacle: it cannot answer a per-case question
- `tests/evaluation/cases/queries.json` — the gold evidence declarations

**Approach**

1. Get per-case output. The artifact does not store it, so this needs an
   evaluation run that emits per case. A working shape already exists in the
   2026-08-15 handoff: build predictions with `predict_exact_symbols`, then call
   `score_query_case` per case and read `containing_evidence_count` and
   `predicted_evidence_count`.
2. Rank cases by uncredited evidence (`predicted - containing`) and look at the
   worst ten *individually* before forming any theory.
3. For each, decide which of three things is true: the gold range is wrong by
   the corpus's own convention; the metric asks the wrong question; or the
   engine genuinely cites the wrong lines. **Only the third is an engine
   defect**, and the prior says it is the least likely.

**Traps**

- **Graph answers cite the reference site, not the definition** (ADR-0003, and
  every existing graph case — q005 cites `10-10`). This exact mistake was made
  on 2026-08-15 while authoring new cases and cost 0.09 on this very metric.
- `containing_evidence_rate` is `containing / predicted`, so a case where the
  engine cites five items against one gold item scores 0.2 even when the right
  line is among them. Decide whether that is the intended question before
  treating a low value as a defect.
- ADR-0003: the corpus is never edited to move a number. Correcting an
  expectation requires the ADR-0031/0036 justification — it named something the
  engine cannot produce, or contradicted itself.

**Done when** every case in the bottom decile has a stated cause, each labelled
instrument or engine, and any threshold change is argued from those causes
rather than from the aggregate.

---

## Task 2 — Subject and file path on `Finding` (WS-2)

**Cost:** ½–1 day. **Blocked by:** nothing.

**Why.** A `Finding` carries no subject and no file path, so two *legitimate*
findings sharing a code and title render identically and collide on
`FindingsList`'s React key. Recorded as ADR-0042 follow-up 1.

**Where to work**

- `src/codeatlas/contracts.py` — the `Finding` model
- `src/codeatlas/analysis/findings.py` — populate the new fields
- `src/codeatlas/delivery/` — the JSON, Markdown and SARIF renderers
- `apps/web/src/features/change-analysis/` — `FindingsList`
- `tests/contract/` — cross-adapter coverage of all three renderers

**Approach.** Additive optional fields only, so `contract_version` stays `1.1`
and no migration is needed. Populate from the `SymbolChange` the finding was
derived from. Surface in all three renderers and the web list, and key the React
list on subject + path.

**Traps**

- **SARIF has its own location model.** Map to it rather than inventing a
  parallel field.
- Do not let this grow into a `Finding` redesign.
- Regenerate the frontend API types with `scripts/generate_web_types.ps1`; never
  hand-edit them.

**Done when** two same-code findings in different files render distinguishably
in JSON, Markdown, SARIF and the web app, with cross-adapter tests covering all
three renderers.

---

## Task 3 — Lexical intents populate relation paths (WS-6)

**Cost:** ½–1 day. **Blocked by:** nothing.

**Why.** The last of ADR-0034's four causes. q027 and q029 emit no relation
paths although their edges are stored, because lexical intents do not populate
them. This is what keeps `relation_path_recall` (0.9130) deliberately ungated —
ADR-0023's rule is that a threshold over an unsettled cause cannot be reasoned
about.

**Where to work**

- `src/codeatlas/application/graph_queries.py`
- `src/codeatlas/conversations/pipeline.py` — where the answer is assembled
- `tests/evaluation/cases/queries.json` — q027, q029

**Approach.** ADR-0020 already requires every graph answer to populate
`relation_paths`; extend that to lexical intents where edges exist. Then, and
only then, propose a gate target for `relation_path_recall` with all four
ADR-0034 causes settled.

**Traps**

- A lexical hit is evidence of *wording*, not behaviour. Emitting relation paths
  must not upgrade a lexical match's derivation.
- Adding the gate target is a **separate** decision from populating the paths.
  Do not bundle them.

**Done when** q027 and q029 emit their stored edges, and the ADR-0034 cause list
is fully discharged.

---

## Task 4 — Ranking sensitivity of the symbol corpus

**Cost:** hours. **Blocked by:** nothing. Best folded into Task 1 if that
touches ranking anyway.

**Why.** Mutation-checking the 23 cases added 2026-08-15 gave two answers:
dropping the top hit fails **18 of 23**, but reversing the ranking fails **0 of
23** — most return a single symbol, so a reversal is a no-op for them. The nine
cases that do catch a reversal are all older. Corpus growth therefore raised the
count without adding ranking coverage.

**Approach.** Add cases whose answer sets are large enough for order to matter,
and mutation-check them with a *ranking* mutation specifically — reversing
`_ranked_symbols` in `src/codeatlas/evaluation/engine_adapter.py`.

**Done when** a ranking reversal fails cases added after 2026-08-15, not only
ones from before it.

---

## ~~Task 5 — Oversized tracked file (WS-3)~~ — **done 2026-08-15**

Gate A was ruled **A3: skip it, and declare the omission**, and WS-3 is
delivered. See **ADR-0045**. `archive` skips and names oversized entries,
`read_blob` still raises (it is asked for one specific blob), and the engine
emits a `FILE_TOO_LARGE` warning plus a limitation naming the files.

The investigation also found the directory side had been omitting oversized
files *silently* since Phase 1 — the scanner recorded `TOO_LARGE` and nothing
carried it into a report. Both sides now declare.

## Task 6 — RRF coarse-chunk measurement (WS-5) — **reframed, not unblocked**

**Cost:** 1–2 days. **Blocked by:** nothing, but the shape changed.

Gate B was ruled **B1: a module-level answer satisfies a conceptual question**,
with **no ranking change**. See **ADR-0046**. So this is no longer "fix the RRF
coarse-chunk bias" — the coarse-chunk penalty stays unimplemented, and the
rank-1 containment hit s001 produces is preserved.

What remains is a **measurement**: does the bias cost anything now the corpus is
larger? ADR-0030's finding still stands — the obvious lever demotes the chunk
currently providing that rank-1 hit — so any proposal to change ranking has to
show corpus-wide numbers, not one case.

**Also permitted by the ruling, and worth doing first:** a conceptual expectation
that names only the implementing symbol may be **widened** to accept the module
that documents the concept. Widening only, never replacement, and only on the
ADR-0031/0036 justification. ADR-0003 still forbids editing the corpus to move a
number.

## Open, but waiting on a trigger rather than on effort

These are not scheduled. Each has a named condition in the register that
reopens it.

| Item                                                                                                                                                                                                                                                                                                | Trigger                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| **Preflight takes >15 min on a 664-file repository.** The engine parses *both* full states per analysis — O(repository), not O(change) — and the snapshot-reuse path ADR-0005 decision 2 describes was never implemented                                                                  | Someone measures it properly, or a user reports it                              |
| **A `check_phase7` run once exited 1 while printing every step as passing.** Exit 1 is the uncaught-throw signature; the trailing `exit 0` added 2026-08-15 can neither cause nor prevent it. Did **not** recur in the 2026-08-15 gate run — one clean data point, not a diagnosis | It recurs — chase it before trusting a green                                   |
| **The change corpus cannot express an ADR-0044-shaped defect.** `predict_changes` compares two `DirectoryStateView`s and never builds a Git repository, so `GitBlobStateView` never runs under the corpus                                                                               | Someone gives the corpus a Git-backed fixture shape — a workstream, not a case |
| **`relation_path_recall` has no gate target**                                                                                                                                                                                                                                               | Task 3 settles ADR-0034's last cause                                            |

---

## Deliberately not doing

Listed so they are not re-proposed as work.

- **Code signing** — a purchasing decision, not an engineering task. The
  packaged executable stays unsigned and SmartScreen warns on first run.
- **Seven Chromium-skipped Playwright tests** — an upstream renderer defect on
  client-side navigation. Firefox runs all seven, confirmed again in the
  2026-08-15 gate run, so coverage is not lost. **Re-count rather than copy the
  figure forward** if it is ever quoted; it has understated itself twice.
- **The 1.05 GB packaged semantic tree** — accepted at the Phase 7 activation
  gate; the torch cost was known when the semantic layer was admitted.
- **Phase 4 `changed_symbol_precision` 0.9464 vs 0.95** — closed as structural.
  c020–c022 split one physical diff into three single-symbol cases that count
  each other's symbols against them; the other cases score 1.0. The corpus is
  not edited to move a number (ADR-0003).

---

## Working rules for whoever picks these up

Copied from `AGENTS.md`, the register, and lessons paid for in the past week.

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live
  status; **append** handoffs, never rewrite them.
- **Test-first**, and **mutation-check every fix**. A test that passes on its
  first run proves nothing until you have watched it fail — and pick a mutation
  that matches the claim, or you get the false comfort Task 4 records.
- **Revert a mutation from a file copy, never `git checkout --`.** It has twice
  reverted the fix along with the mutation (ADR-0022, ADR-0042).
- **Do not edit the tree you are measuring.** A preflight over a live working
  tree is not atomic; a file caught mid-write reads as empty. This produced 496
  false findings on 2026-08-13.
- **ADR-0003: the corpus is never edited to move a number.** Adding coverage is
  legitimate; changing an expectation needs the ADR-0031/0036 justification.
- Declare any change to `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION` or
  `CHUNKER_VERSION` explicitly: it makes every snapshot stale and forces a
  re-index.
- Gates before any completion claim: `uv run pytest -q`,
  `ruff check src tests scripts apps`,
  `mypy --no-incremental src tests scripts apps`,
  `check_phase4.ps1 -SkipSync`, `check_phase7.ps1 -SkipSync`. Read exit codes
  from the process. **They may now be run concurrently** — the shared
  `.test-tmp` collision was fixed 2026-08-15 and the one-at-a-time rule is
  retired.
