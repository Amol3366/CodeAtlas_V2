# Extra Build — the remaining work, in the order to do it

Status: current as of 2026-08-16, after WS-3, WS-4 and **Task 1 (q035)** closed.

**Authority note.** This file is a **work plan**, not a status list. The single
authoritative record of what is open is the **Deferred Register in
`docs/plans/PLAN.md`**; `AGENTS.md` is the release-blocking contract. Where this
file and the register disagree about *whether* something is open, the register
wins and this file is the bug.

It exists because the register answers "what is open and why" but not "how would
someone actually do it" — which files, which traps, what counts as done. That is
what is written here, per task. **Deliberately no status column**, because
`documentation/memory.md` already records the lesson that two copies of a status
list is how they drift.

**Relationship to the post-closeout program.** The workstream numbering (WS-2,
WS-5, WS-6) is
`docs/superpowers/plans/2026-08-14-post-closeout-program.md`, and each task below
names its WS where one applies. That file remains the record of *why* the work
was scoped this way and what its decision gates were; this file is the current
*execution order*. **If they disagree about sequence, this file is newer; if they
disagree about scope or rationale, the program plan wins.** When the program is
finished, delete this file rather than leaving it to rot.

Ordering is execution order. Task 1 is first because a release gate currently
has no margin and Task 1 is what is consuming it.

---

## Start here tomorrow

1. ~~**Task 1 — q035.**~~ **DONE 2026-08-16 — ADR-0050.** The gate margin is
   back: `exact_symbol_resolution` **1.0000 (50/50)**. Two corpus lines, no
   source change. Read the finding under Task 1 below before starting anything
   else — the obvious half of the fix **passed its own mutation-check**.
2. **Task 2 — q006** is now first, and it is the only candidate *engine* finding
   this project has produced in nine investigations. ADR-0050 does not touch it.
3. After that the order is open: Tasks 3–7 are independent.

---

## Where things stand

Phases 0–7 complete with user-approved gates; the project was closed out
2026-08-10 and everything since is post-gate work. Of the post-closeout program,
**WS-0, WS-1, WS-3 and WS-4 are closed**, along with both process defects (gate
exit codes, test isolation). **WS-2, WS-5 and WS-6 remain.**

Corpus: **63 query cases / 28 change cases** over **7 fixtures**, with a scored
symbol-intent denominator of **50**.

**All gates pass, and both gate scripts now run to completion:**
`uv run pytest -q` **2240 passed / 3 skipped**, ruff, mypy on 352 files,
`check_phase4.ps1 -SkipSync` **exit 0**, `check_phase7.ps1 -SkipSync -Semantic`
**exit 0** — the latter including the semantic suites, the uplift baseline, the
rerank artifact and Playwright (15 passed, 7 Chromium skips). Exit codes read
from the process.

> **Quote the flags whenever you claim a gate passed.** `-SkipSync` without
> `-Semantic` never reaches the Phase 7 semantic baseline or the rerank
> artifact — which is exactly how **two** stale artifacts survived two days of
> green runs on 2026-08-16. A gated artifact behind an opt-in flag is not gated.

> **Do not run two gate scripts at once.** The 2026-08-15 `.test-tmp` fix made
> temp *directories* safe and the one-at-a-time rule was retired **generally**;
> that looks too broad. Two concurrent full suites gave 3 failures that did not
> reproduce solo (2240 passed, exit 0). The packaged e2e tests bind a loopback
> port and share one `dist/`. Unconfirmed mechanism — see the register.

### Phase 4 baseline, refreshed 2026-08-16 after ADR-0050

| Metric | Value | Target | State |
| --- | ---: | ---: | --- |
| `exact_symbol_resolution` | **1.0000** | 0.98 | met — 50/50; **margin restored, and it is exactly one miss wide** |
| `containing_evidence_recall_at_10` | 0.9824 | 0.90 | met |
| `primary_evidence_recall_at_10` | 0.9353 | 0.90 | met |
| `containing_evidence_rate` | 0.7520 | — | **ungated** (ADR-0048); reported |
| `changed_symbol_precision` | 0.9464 | 0.95 | unmet, closed as structural — **still the only unmet target** |
| `abstention_correctness` | 1.0000 | — | ungated |
| `mean_reciprocal_rank` | 1.0000 | — | ungated |
| `symbol_recall_at_10` | 0.8879 | 0.90 | ungated on this profile (ADR-0023) |
| `ndcg_at_10` | 0.9145 | — | ungated |
| `relation_path_recall` | 0.9130 | — | deliberately ungated until Task 4 |

> **`exact_symbol_resolution` has one miss of headroom, and that is all.** ADR-0033
> predicted 0.98 would become expressible at 50 cases, because 50 is the first
> size tolerating one miss. It now reads 1.0000, so a single future miss scores
> 0.9800 and still passes — but a second gives 0.9600 and the gate fails.
> **Adding scored symbol-intent cases changes the denominator**, so compute the
> new one before adding any (see Task 6).

---

## The rule that governs almost all of this

**State, per finding, whether it is a faulty instrument or an absent decision.
They need different fixes.**

The standing prior — *the instrument is wrong, not the engine* — has now held
eight times: ADR-0017, 0018, 0024, 0027, 0038, the 2026-08-13 document-section
false report, and both register rows corrected on 2026-08-15. **But it was
applied too broadly on 2026-08-15 and the user corrected it.** Of the two WS-4
findings:

- the `target/` ignore collision was a **faulty instrument** — the fixture
  declared evidence in a file no index could contain;
- the graph-evidence convention was an **absent decision** — nobody had ever
  ruled what a graph answer cites, and the corpus and the engine were each
  internally consistent the whole time.

**A prior confirmed eight times gets applied as a reflex, and a reflex is how a
real engine defect eventually gets waved past.** Task 2 exists because that was
avoided once, narrowly.

**The corollary, learned twice on 2026-08-16:** derive an expectation from the
claim, never from the engine's output. Both WS-4 step predictions failed
(0.9765 → 0.9588, then ≈1.0000 → 0.9706) precisely *because* the corrections
were derived independently. Copying the engine's lines would have matched both
predictions exactly and buried q006. **When a prediction fails, the model was
wrong and that is information. When it succeeds because you fitted the
expectation to the output, you have learned nothing.**

---

## Task 1 — q035 ✅ DONE 2026-08-16 (ADR-0050)

Kept rather than deleted, because the *way* it went wrong is reusable and Task 6
depends on the lesson.

**What was ruled.** Two corrections to q035, on different authorities:
`query_subject: "target.processor.process"` (additive — the field's own comment
sanctions it) and `expected_evidence` → the reference site `4-4`, a **ninth
instance of ADR-0047**. q035 could not be among ADR-0047's eight because it was
abstaining and emitted nothing to compare. `exact_symbol_resolution` 0.9800 →
**1.0000**. No source file changed; two corpus lines.

**Finding 1 — this file was wrong, and it cost the cheapest option.** The text
above used to say a disambiguating `query_subject` "may not be expressible"
because "`find_exact` resolves by name and there is no file-scoped selector".
**It has four tiers, and tier 2 is `module_path || '.' || qualified_name`**
(`storage/sqlite/stores.py:463`). `target.processor.process` resolves to exactly
one symbol. The claim had never been tested against the store — it was reasoned
about and written down. *Probe the store before recording a capability limit.*

**Why nobody noticed: the ambiguity message does not disambiguate.** It reads
"matches 2 symbols: process, process. Ask again with a qualified name", printing
`qualified_name` — identical for both. Still open, now its own register row.

**Finding 2 — the fix passed its own mutation-check. This is the one to
remember.** Declaring `query_subject` restored the number. Repointing it at
`base.service.process`, the **wrong side**, scored **identically** — because
`expected_symbols` is `["process"]` and both fixture sides define that name.
The case would have passed while tracing the wrong file.

> **No name-based metric can separate two same-named symbols.**
> `exact_symbol_resolution`, `mean_reciprocal_rank` and `abstention_correctness`
> all read the symbol's name. Only the evidence correction made q035
> discriminate, because the two sides' reference sites are in different *files*.

The obvious mutation — reverting the `query_subject` line — would have failed
correctly and taught nothing. **Pick a mutation that could plausibly be wrong in
the way the case is meant to catch**, not one that merely undoes the edit.

---

## Task 2 — q006: the engine cites a line that does not prove the claim

**Cost:** ½ day to investigate. **Blocked by:** nothing.

**Why it matters out of proportion to its size.** This is the **only candidate
engine finding** produced by nine investigations. Every other one was the
instrument. It surfaced only because the WS-4 corrections were derived from the
claim rather than copied from the engine, and the reflex would have buried it.

**The finding.** q006 asks "How are duplicate keys handled?" and names
`IdempotencyStore.claim`. The line that proves duplicate handling is
`return "duplicate"` — `idempotency.py:7`. **The engine cites line 8**,
`self._keys.add(key)`, which records a key rather than handling a repeat.

**Not proven to be a defect.** `claim` has no outgoing resolved relation, so the
trace has no edge to cite and the evidence is falling back to something else —
plausibly a chunk or lexical hit. Establish *why* line 8 is selected before
calling it wrong.

**Where to work:** `src/codeatlas/conversations/pipeline.py`,
`src/codeatlas/application/graph_queries.py`, and the retrieval channels behind
a `TRACE_FLOW` with no traversable edge.

**Done when** the selection of line 8 has a stated cause, labelled *faulty
instrument* or *absent decision* or — for the first time — *engine defect*.

---

## Task 3 — Subject and file path on `Finding` (WS-2)

**Cost:** ½–1 day. **Blocked by:** nothing.

**Why.** A `Finding` carries no subject and no file path, so two *legitimate*
findings sharing a code and title render identically and collide on
`FindingsList`'s React key. Recorded as ADR-0042 follow-up 1.

**Where to work**

- `src/codeatlas/contracts.py` — the `Finding` model
- `src/codeatlas/analysis/findings.py` — populate the new fields
- `src/codeatlas/delivery/` — the JSON, Markdown, PR and SARIF renderers
- `apps/web/src/features/change-analysis/` — `FindingsList`
- `tests/contract/` — cross-adapter coverage of every renderer

**Approach.** Additive optional fields only, so `contract_version` stays `1.1`
and no migration is needed. Populate from the `SymbolChange` the finding was
derived from. Surface in every renderer and the web list, and key the React list
on subject + path.

**Traps**

- **SARIF has its own location model.** Map to it rather than inventing a
  parallel field.
- Do not let this grow into a `Finding` redesign.
- Regenerate the frontend API types with `scripts/generate_web_types.ps1`; never
  hand-edit them.
- **There are four renderers, not three.** `text_report.py` is the CLI verdict
  and was the one that silently dropped limitations until 2026-08-15 (ADR-0045).
  Check it explicitly.

**Done when** two same-code findings in different files render distinguishably
in JSON, Markdown, PR, SARIF and the web app, with cross-adapter tests covering
each.

---

## Task 4 — Lexical intents populate relation paths (WS-6)

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
- Watch `containing_evidence_rate`: more emitted evidence lowers it. It is
  ungated now (ADR-0048), so this is worth noting in a handoff, not avoiding.

**Done when** q027 and q029 emit their stored edges, and ADR-0034's cause list is
fully discharged.

---

## Task 5 — q032: a two-hop trace carries no evidence for its far end

**Cost:** hours once ruled. **Blocked by:** a product decision.

**Why.** q032 traces frontend → backend. After ADR-0047 the frontend hop matches;
`backend.py:1-2` — the endpoint the flow actually reaches — is **never cited**,
so the case caps at **0.50**.

Either a trace answer should carry evidence at its far end, or a two-hop
expectation should not declare one. **A product question, not a defect**, and
adjacent to Task 4: both are about what a traversal-derived answer carries.

**Where to work:** `src/codeatlas/application/graph_queries.py` (the `trace`
path), `tests/evaluation/cases/queries.json` (q032).

---

## Task 6 — Ranking sensitivity of the symbol corpus

**Cost:** hours. **Blocked by:** nothing.

**Why.** Mutation-checking the 23 cases added 2026-08-15 gave two answers:
dropping the top hit fails **18 of 23**, but reversing the ranking fails **0 of
23** — most return a single symbol, so a reversal is a no-op for them. The nine
cases that *do* catch a reversal are all older. Corpus growth raised the count
without adding ranking coverage.

**Approach.** Add cases whose answer sets are large enough for order to matter,
and mutation-check them with a *ranking* mutation specifically — reversing
`_ranked_symbols` in `src/codeatlas/evaluation/engine_adapter.py`.

**Trap:** adding scored symbol-intent cases changes the
`exact_symbol_resolution` denominator. Task 1 restored the margin to 1.0000, but
that is **exactly one miss wide** — compute the new denominator before adding
anything.

**Second trap, added 2026-08-16 from Task 1 and it generalises this whole task.**
A same-named-symbol case cannot be caught by any *name-based* metric. When
mutation-checking a new case, check it against the metric that would actually
have to move, not against the aggregate — q035 scored identically whether the
right or the wrong symbol was traced, and only an evidence metric separated them.

**Done when** a ranking reversal fails cases added after 2026-08-15, not only
ones from before it.

---

## Task 7 — RRF coarse-chunk measurement (WS-5) — reframed, not blocked

**Cost:** 1–2 days. **Blocked by:** nothing; the shape changed.

Gate B was ruled **B1: a module-level answer satisfies a conceptual question**,
with **no ranking change** (ADR-0046). So this is no longer "fix the RRF
coarse-chunk bias" — the penalty stays unimplemented and s001's rank-1
containment hit is preserved.

What remains is a **measurement**: does the bias cost anything now the corpus is
larger? ADR-0030's finding stands — the obvious lever demotes the chunk
providing that rank-1 hit — so any proposal to change ranking must show
corpus-wide numbers, not one case.

**Also permitted by the ruling, and cheaper:** a conceptual expectation naming
only the implementing symbol may be **widened** to accept the module that
documents the concept. Widening only, never replacement, and only on the
ADR-0031/0036 justification. ADR-0003 still forbids editing the corpus to move a
number.

---

## Open, but waiting on a trigger rather than on effort

Not scheduled. Each has a named condition in the register that reopens it.

| Item | Trigger |
| --- | --- |
| **Preflight takes >15 min on a 664-file repository.** The engine parses *both* full states per analysis — O(repository), not O(change) — and the snapshot-reuse path ADR-0005 decision 2 describes was never implemented | Someone measures it properly, or a user reports it |
| **A `check_phase7` run once exited 1 while printing every step as passing.** Exit 1 is the uncaught-throw signature; the trailing `exit 0` added 2026-08-15 can neither cause nor prevent it. Has **not** recurred in the three gate runs since | It recurs — chase it before trusting a green |
| **Concurrent gate runs fail; the same tree passes solo.** 3 failed / 2237 passed run together, 2240 passed alone. Which three was not captured, so the mechanism (loopback port + shared `dist/` in the packaged e2e tests) is a hypothesis | Someone reproduces it with full output captured |
| **The `-Semantic` step is opt-in, so two artifacts went stale unnoticed for two days** | Someone makes the semantic block non-optional, or accepts that `-SkipSync` alone is not a full gate |
| **The change corpus cannot express an ADR-0044-shaped defect.** `predict_changes` compares two `DirectoryStateView`s and never builds a Git repository, so `GitBlobStateView` never runs under it | Someone gives the corpus a Git-backed fixture shape — a workstream, not a case |
| **`relation_path_recall` has no gate target** | Task 4 settles ADR-0034's last cause |

---

## Deliberately not doing

Listed so they are not re-proposed as work.

- **Code signing** — a purchasing decision, not an engineering task. The
  packaged executable stays unsigned and SmartScreen warns on first run.
- **Seven Chromium-skipped Playwright tests** — an upstream renderer defect on
  client-side navigation. Firefox runs all seven, confirmed again on 2026-08-16,
  so coverage is not lost. **Re-count rather than copy the figure forward** if it
  is ever quoted; it has understated itself twice.
- **The 1.05 GB packaged semantic tree** — accepted at the Phase 7 activation
  gate; the torch cost was known when the semantic layer was admitted.
- **Phase 4 `changed_symbol_precision` 0.9464 vs 0.95** — closed as structural.
  c020–c022 split one physical diff into three single-symbol cases that count
  each other's symbols against them; the others score 1.0. The corpus is not
  edited to move a number (ADR-0003).
- **Loosening `_contains` to accept overlap** — refused in ADR-0047. Its
  directionality is correct; loosening it moves a number without settling
  anything.
- **Lowering `containing_evidence_rate`'s threshold** — refused in ADR-0048. It
  is ungated instead, because a threshold chosen to be passed says less than it
  appears to (ADR-0032, ADR-0033).

---

## Working rules for whoever picks these up

From `AGENTS.md`, the register, and lessons paid for over the past fortnight.

- `AGENTS.md` is the release-blocking contract. `docs/plans/PLAN.md` is live
  status; **append** handoffs, never rewrite them.
- **Test-first**, and **mutation-check every fix.** A test that passes on its
  first run proves nothing until you have watched it fail — and **pick a
  mutation that matches the claim**, or you get the false comfort Task 6
  records.
- **Derive an expectation from the claim, never from the engine's output.**
  See the governing rule above; this is what surfaced Task 2.
- **A failing prediction is information.** If a measured number does not match a
  predicted one, the model of the failure is wrong and everything downstream is
  suspect. Stop and say so.
- **Revert a mutation from a file copy, never `git checkout --`.** It has twice
  reverted the fix along with the mutation (ADR-0022, ADR-0042).
- **Do not edit the tree you are measuring.** A preflight over a live working
  tree is not atomic; a file caught mid-write reads as empty. This produced 496
  false findings on 2026-08-13.
- **ADR-0003: the corpus is never edited to move a number.** Adding coverage is
  legitimate; changing an expectation needs the ADR-0031/0036 justification.
- **When an exclusion stops being loud, check every surface that reported the
  loudness** (ADR-0045). Four renderers carry limitations; the CLI verdict was
  the one that silently did not.
- Declare any change to `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION` or
  `CHUNKER_VERSION` explicitly: it makes every snapshot stale and forces a
  re-index.
- Gates before any completion claim: `uv run pytest -q`,
  `ruff check src tests scripts apps`,
  `mypy --no-incremental src tests scripts apps`,
  `check_phase4.ps1 -SkipSync`, `check_phase7.ps1 -SkipSync`. **Read exit codes
  from the process, not the printed output.** They may be run **concurrently** —
  the shared `.test-tmp` collision was fixed 2026-08-15 and the one-at-a-time
  rule is retired.
- **`$?` after a pipe is the pipe's exit code, not the command's.** `cmd | tail`
  then `echo $?` reports `tail`, which always succeeds. This produced four false
  `EXIT=0` readings on 2026-08-16, one of them for a step that was actually
  failing. Capture into a variable first, or use `${PIPESTATUS[0]}`. It is the
  same class as the gate-script exit-code defect and it survives *because a
  false green looks exactly like a real one*.
- **A gate script aborts at its first failing step, so a red step-one hides
  everything after it.** When the pytest step fails, nothing downstream in
  `check_phase4` / `check_phase7` has run — do not report those gates as
  anything until their later stages are run directly.
- **Regenerate `baseline-phase-0`, `-3` and `-4` once, at the end of a change.**
  `-1` and `-2` stay frozen as history.
