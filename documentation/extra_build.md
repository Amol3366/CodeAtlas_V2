# Extra Build — the remaining work, in the order to do it

Status: current as of 2026-08-17, after WS-3, WS-4, WS-5 and **Tasks 1, 2, 3, 5 and 7** closed.

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

Ordering is execution order. **Tasks 1 and 2 are done**; the remaining tasks are
independent, so the order below is a suggestion rather than a dependency chain.

---

## Start here tomorrow

**Tasks 1, 2, 3, 5 and 7 are done** (ADR-0050, 0051, 0054, 0055, 0056).
**Everything still open is blocked on a ruling** — there is no longer a task
you can start without a decision.

1. **Task 4 is the ruling to ask for first**, because ADR-0055 just answered the
   same question shape for `trace`: what does a traversal-derived answer carry?
   Task 4 asks it for *lexical* answers. Three cases, not two — q024 joined
   after ADR-0053.
2. **The rest of Task 6 needs a different ruling** — whether a corpus
   expectation should declare transitive (depth-2) results.

**ADR-0056 is `proposed`, not `accepted`.** It recommends closing the RRF item
on the measurement below; per the ADR workflow only the user moves it to
`accepted`.

**Before writing or trusting any test, read the boxed findings under Tasks 1, 2,
3 and 5.** Between them they record five ways something can look like coverage
and not be:

- a whole-file evidence item satisfies any line in that file (Task 2);
- `exact_symbol_resolution` feeds the expected symbol in as the query, so it
  cannot detect a *wrong* expectation (Task 2);
- no name-based metric separates two same-named symbols (Task 1);
- asserting on rendered output cannot see a React key collision (Task 3);
- **a mutation that cannot apply is indistinguishable from a test that cannot
  catch it** (Task 5) — two of four looked green for that reason alone.

None of these was found by review. All five were found by mutation, and three
were found only after a *first* mutation attempt came back green.

**And one about measurement rather than testing, from Task 7:** *check which
corpus a metric is computed over before believing that corpus grew.* WS-1 took
`cases` from 27 to 50 and the fusion measurement still runs on 14, because
`_fuse` is gated on `SEMANTIC_INTENTS` and never sees the corpus that grew.

---

## Where things stand

Phases 0–7 complete with user-approved gates; the project was closed out
2026-08-10 and everything since is post-gate work. Of the post-closeout program,
**WS-0, WS-1, WS-3 and WS-4 are closed**, along with both process defects (gate
exit codes, test isolation). **WS-2 closed 2026-08-17 (ADR-0054), WS-5 the same
day (ADR-0056). Only WS-6 remains**, blocked on the Task 4 ruling.

Corpus: **64 query cases / 28 change cases** over **7 fixtures**, with a scored
symbol-intent denominator of **50**.

**All gates pass, and both gate scripts run to completion:**
`uv run pytest -q` **2254 passed / 3 skipped**, ruff, mypy on 352 files,
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

### Phase 4 baseline, refreshed 2026-08-17 after ADR-0055

| Metric | Value | Target | State |
| --- | ---: | ---: | --- |
| `exact_symbol_resolution` | **1.0000** | 0.98 | met — 50/50; **margin restored, and it is exactly one miss wide** |
| `containing_evidence_recall_at_10` | **1.0000** | 0.90 | met — every case scores |
| `primary_evidence_recall_at_10` | 0.9368 | 0.90 | met |
| `containing_evidence_rate` | 0.7537 | — | **ungated** (ADR-0048); reported |
| `changed_symbol_precision` | 0.9464 | 0.95 | unmet, closed as structural — **still the only unmet target** |
| `abstention_correctness` | 1.0000 | — | ungated |
| `mean_reciprocal_rank` | 1.0000 | — | ungated |
| `symbol_recall_at_10` | 0.8917 | 0.90 | ungated on this profile (ADR-0023) |
| `ndcg_at_10` | 0.9173 | — | ungated |
| `relation_path_recall` | **0.8750** | — | deliberately ungated until Task 4; was reported 0.9130 before ADR-0053 |

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
real engine defect eventually gets waved past.**

**It is now nine, and Task 2 was the test of it.** q006 was carried as the one
candidate engine finding and investigated on the assumption it might be real —
the engine's claim text read against the lines it cites, the evidence
construction traced to its source, the product's classifier actually run. It
still ended at the instrument. *Nine is not permission to stop checking; it is
nine chances to have stopped and been wrong.*

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

## Task 2 — q006 ✅ DONE 2026-08-16 (ADR-0051)

**It was not an engine defect.** Nine investigations, nine instruments.

**Both halves of what this file recorded were false.** `claim` *does* have an
outgoing edge — `CALLS add` at line 8 — and evidence is built one per edge from
`edge.start_line` (`graph_queries.py:305-318`), so nothing "falls back to a
chunk or lexical hit". And the engine's claim is *"IdempotencyStore.claim calls
add at idempotency.py:8"*, which line 8 proves exactly. It does not *answer the
question*, which is a different thing and not an §4.1 violation.

Line 7, `return "duplicate"`, holds **no relation**, so under ADR-0047 no
correct `TRACE_FLOW` can cite it. The product's own `classify()` routes that
question to **`text`**, and the lexical result `5-9` contains line 7. Re-typed
to `CONCEPTUAL`; `containing_evidence_recall_at_10` 0.9824 → **0.9941**.

> **q064 had to be added in the same change.** `TRACE_FLOW` is a symbol intent,
> so re-typing q006 alone drops the `exact_symbol_resolution` denominator
> **50 → 49**, where one miss scores 0.9796 and **fails**. Check the denominator
> before changing any case's intent — not just before adding one.

**Three ways a case scores without measuring what it claims**, all found by
mutation on 2026-08-16. Treat them as a checklist when writing or trusting a case:

1. **A whole-file evidence item satisfies any line in that file.** q006's
   expected line moved 7 → 1 with **no metric change**, because lexical also
   returns `idempotency.py:1-9`.
2. **`exact_symbol_resolution` cannot detect a wrong expectation** — it feeds
   `expected_symbols[0]` in as the query and checks it comes back.
3. **No name-based metric separates two same-named symbols** (ADR-0050).

## Task 3 — Subject and file path on `Finding` ✅ DONE 2026-08-17 (ADR-0054)

**The recorded task was the symptom.** It described a rendering problem: two
legitimate findings sharing a code render identically and collide on
`FindingsList`'s React key. Reproducing it found an **engine defect** underneath.

**`_finding_citations` keyed changed symbols on `qualified_name` alone.** Two
modules each defining `total` collapsed to whichever the dict comprehension saw
last, so **the finding about `billing.py` cited lines in `orders.py`** — a §4.1
violation, and **ADR-0042's own rule ("pair within the file first") reaching a
surface that ruling did not touch**. The ambiguity started earlier still:
`FindingDraft.subject` was a bare string.

**Two corrections to what this file said.** Construction is in
`application/change_analysis.py`, not `analysis/findings.py`. And "no migration
is needed" was right for the wrong reason — findings *are* persisted, in
`change_findings`, which has no such columns. The fields are **derived from the
citation** by one helper both the fresh and rehydration paths call, so storing
them was unnecessary *and* would have created a second copy that can disagree.

> **Look for what already carries the fact before adding a field to hold it.**
> Every finding cites exactly one evidence item, and `_cite` had labelled it
> with the subject since Phase 4. The data was there the whole time.

**Six surfaces, and SARIF needed nothing** — it already carries the location in
`artifactLocation`, so mapping to the standard was satisfied by fixing the
citation. Markdown, PR and the CLI verdict gained a subject line; JSON follows
from the model; the web list renders the pair and keys on it.

**The web test had no teeth, and only a mutation showed it.** Asserting both
findings *render* stayed green when the key was reverted — React renders both
children whatever the key, and a duplicate surfaces only as a console warning.
Rewritten to spy on `console.error`, it fails.

> **Assert on the mechanism the defect produces, not on what you hope it
> disturbs.** The rendered output was never going to show a key collision.

## Task 4 — Lexical intents populate relation paths (WS-6)

**Cost:** ½–1 day of work, but **blocked on a design decision**. **Investigated
2026-08-17**; the premise checked out — the first time this session that it did.

**Why.** The last of ADR-0034's four causes. The declared edges **are stored and
resolved** (`Order flow DOCUMENTS get_order`, `healthPath REFERENCES health`,
`Sample Service DOCUMENTS service.port`), and the lexical answers return
`relation_paths: []`. Verified by probe, not assumed.

**It is three cases, not two.** q024 joins q027 and q029: it was **never
measured** until ADR-0053 added `CONCEPTUAL` to `SUPPORTED_INTENTS`, so it could
not appear in this list. `relation_path_recall` is **0.8750**, not the 0.9130
this file used to quote.

**ADR-0034 named it a design decision, not a defect:** "Whether a lexical answer
should carry stored relations is a design decision, not a defect to fix
quietly." That ruling has not been given, and it is what blocks the work.

**The complication a probe found, and the reason this cannot be a blind
implementation.** `Order flow` carries **eight** `DOCUMENTS` edges — two
resolved (`loadOrder`, `get_order`), six unresolved. The corpus declares one. So
emitting every stored path gives q027 recall 1.0 and precision 0.5, which is
ADR-0038's shape exactly: *precision penalising a second, true edge*. Decide
what a lexical answer emits before deciding what the corpus should declare.

**Where to work**

- `src/codeatlas/application/graph_queries.py`
- `src/codeatlas/conversations/pipeline.py` — where the answer is assembled
- `tests/evaluation/cases/queries.json` — q024, q027, q029

**Traps**

- A lexical hit is evidence of *wording*, not behaviour. Emitting relation paths
  must not upgrade a lexical match's derivation. The contract keeps
  `answer.claims` and `relation_paths` in separate fields with their own
  derivations, so this is achievable — but only if the claims are left alone.
- Adding the gate target is a **separate** decision from populating the paths.
  Do not bundle them.
- Watch `containing_evidence_rate`: more emitted evidence lowers it. Ungated
  (ADR-0048), so note it in a handoff rather than avoiding it.

**Done when** q024, q027 and q029 emit their stored edges, and ADR-0034's cause
list is fully discharged.

## Task 5 — q032 ✅ DONE 2026-08-17 (ADR-0055)

**Ruled:** a resolved `ROUTES_TO` edge additionally cites the **handler's
definition** — an explicit exception to ADR-0047, on ADR-0019's `EXPORTS`
precedent. A route *names* its target, and unlike an export its literal and its
target sit in different files and usually different languages, so the near side
alone cannot show what the flow reaches. q032 **0.50 → 1.00**, and
`containing_evidence_recall_at_10` reaches **1.0000** — every case now scores.

**Reproducing it found a defect the row did not mention.** Evidence is
deduplicated by region, correctly, but claims were built from the *surviving
pairs* — so the second edge on a shared line lost its claim. `ROUTES_TO` and the
`fetch` call carrying it both sit on `frontend.ts:2`, so **the engine dropped
its only resolved, cross-language edge and kept two unresolved browser globals,
by iteration order.** Fixed as a consequence: a route that cites its own
destination no longer shares a region.

> `_verb` had no `ROUTES_TO` entry either, so the claim would have read
> *"loadOrder relates to get_order"* — the generic fallback on the one relation
> whose point is the boundary it crosses. Nobody had seen it because the claim
> was never rendered.

**This settles the last of ADR-0034's four causes for `trace`.** The lexical
half — q024, q027, q029 — is Task 4 and still needs its own ruling.

> **Two of four mutations could not be exercised by the fixture**, and both
> looked like passing guards. Over-applying the carve-out was a no-op because
> every non-route edge in `mixed_app` is unresolved; it now has a `python_app`
> test where a `CALLS` *is* resolved. Deleting the claim merge is still not
> caught, and that is recorded in the register rather than counted as coverage.
> **A mutation that cannot apply is indistinguishable from a test that cannot
> catch it.**

## Task 6 — Ranking sensitivity: the premise was wrong (partly done)

**Cost:** blocked on a ruling. **Investigated 2026-08-17.** It produced an engine
defect (ADR-0052) and a correction to its own model; the cases it asks for
cannot be written until a convention is ruled.

**The stated approach is wrong.** This section used to say "add cases whose
answer sets are large enough for order to matter". **Size is not the
mechanism** — q060 returns *five* symbols and is not ranking-sensitive, because
all five are expected. `exact_symbol_resolution` checks
`ranked_symbols[0] in set(expected_symbols)`, so if every returned symbol is
expected, any order passes.

**Sensitivity requires a distractor** — a returned symbol *outside*
`expected_symbols`. Measured over the whole corpus, distractor presence and
reversal sensitivity are **the same 9 cases**, exactly:

| | Count |
| --- | ---: |
| Reversal-sensitive, all older (q003–q029) | 9 |
| …symbol-intent (q003, q005, q015) | 3 |
| …lexical-intent (CONFIG/DOCUMENT) | 6 |
| Reversal-sensitive among the 24 newer cases | **0** |
| Cases returning a distractor | **9 — the same 9** |

**And the only source of distractors is second-hop traversal** (`max_depth` 2).
So for a correctly-specified *direct* graph case, ranking sensitivity is
**structurally unavailable**: ADR-0020 has the corpus declare every edge
endpoint, which leaves nothing to mis-rank. Two consequences worth stating:

> **`exact_symbol_resolution` is a resolution gate, not a ranking gate.** It
> cannot be made ranking-sensitive by adding well-specified symbol cases.
> Ranking genuinely lives in the **lexical** intents, where retrieval returns
> more than the corpus declares and ADR-0026 already rules on order.

**The three sensitive symbol cases are sensitive because they are
under-specified**, not by design. q005 expects the *subject* as an answer and
omits a real transitive caller; q015 expects `render`, which `client.js` defines
rather than imports. Fixing them would take symbol-intent ranking coverage to
**zero**.

**What is blocked:** whether a `CALLERS` / `DEPENDENCIES` expectation should
declare transitive results. Until that is ruled, new cases cannot be written to
be sensitive without declaring less than the truth.

**Where to work:** `tests/evaluation/cases/queries.json` (q003, q005, q015),
`src/codeatlas/retrieval/graph.py` (`TraversalLimits.max_depth`).

**Done when** the convention is ruled and a ranking reversal fails cases added
after 2026-08-15 — or it is recorded that symbol-intent ranking coverage is
structurally unavailable and the lexical side carries it.

## Task 7 — RRF coarse-chunk measurement (WS-5) ✅ DONE 2026-08-17 (ADR-0056)

**Measured corpus-wide at three penalty strengths. The lever is a pure loss —
every metric that moves, moves down.** Reproduce with
`uv run python scripts/measure_rrf_penalty.py --ab` (needs `semantic-local`;
**never add it to a gate**, §4.3).

| Metric | baseline | scale 0.50 | scale 0.25 | fine-first |
| --- | ---: | ---: | ---: | ---: |
| `containing_evidence_recall_at_10` | **1.0000** | 0.9333 | 0.8667 | 0.8667 |
| `primary_evidence_recall_at_10` | **0.8000** | 0.7333 | 0.7333 | 0.7333 |
| `symbol_recall_at_10` | **0.9286** | 0.8571 | 0.8571 | 0.8571 |
| `mean_reciprocal_rank` | **0.6977** | 0.6888 | 0.6888 | 0.6888 |
| `ndcg_at_10` | **0.7530** | 0.7304 | 0.7304 | 0.7304 |

**ADR-0030 predicted a trade. There is no trade** — `symbol_recall_at_10` falls
*too*, so the lever loses on both sides of the exchange it was meant to balance.

**The finding ADR-0030 did not anticipate:** s013's expected answer
`OrderStatus` (`models.py:6-12`) **is itself a class chunk**, so the penalty
demotes the answer it exists to promote, **7 → 28**. s001 loses its only
containment hit **1 → 11**, as predicted. The one gain in the whole corpus is
s007, **8 → 7** — already inside the top 10, so it cannot improve any Recall@10,
and its ~0.001 of MRR is swamped by the losses.

Incidence today: a coarse chunk outranks the declared evidence in **2 of 14
cases**, both still inside the top 10, so **the bias costs zero recall.**

> **The premise was false, and this is the sixth time.** The task said "now the
> corpus is larger". It is not. `_fuse` is gated on `SEMANTIC_INTENTS`
> (`{PROJECT_OVERVIEW, TEXT}`) and `predict_exact_symbols` attaches no fusion,
> so **WS-1's 27 → 50 growth landed on a corpus fusion never touches.** The only
> corpus that reaches it is `semantic_cases` — **14 cases, one fixture,
> byte-identical since 2026-07-31**. Check which corpus a change is measured on
> before believing it grew. **Task 4 is still the only premise in this program
> that checked out.**

> **The "cheaper" widening option is not available.** ADR-0046 permits widening
> only on the ADR-0031/0036 justification — the expectation named something the
> engine cannot produce, or contradicted itself. **s001 names
> `InventoryLedger.reserve`, which the engine does produce, at symbol rank 12.**
> Neither test is met, so widening it would be editing the corpus to move a
> number (ADR-0003). s001 stays as written.

**Also corrected:** ADR-0028's second recorded cost, s004, **no longer
reproduces** — `tax_for` is rank 1 and `pricing.py:1-42` is rank 5. Deliberately
not attributed; ADR-0026 and ADR-0029 are both plausible and separating them
needs a bisect this did not do. Its first, s013 at rank 7, is unchanged.

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
| **The corpus fusion runs on is 14 cases over one fixture**, byte-identical since 2026-07-31. Every fusion and ranking number — ADR-0028's, ADR-0030's, ADR-0056's — rests on it, and WS-1's growth never reached it | Someone gives `semantic_cases` a second fixture — a fixture shape, not a case |

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
