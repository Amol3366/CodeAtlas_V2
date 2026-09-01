# Design: the register tail after the Deferred Register Program

- Status: proposed, awaiting user review
- Date: 2026-09-02
- Decision owners: user/product (asked for every remaining item to be planned)
  and implementing agent
- Related: ADR-0058 (`relation_path_recall` gated at 1.0), ADR-0071 and
  ADR-0074 (the query-backed identity lineage), ADR-0073 ruling 4 and DR-09
  (the `TRACE_FLOW` audit), ADR-0064 (preflight cost, and the synthetic
  profile's blindness), `docs/plans/PLAN.md` (the register itself)

## Context

The Deferred Register Program closed on 2026-09-02 with all nine tasks
complete and merged (`9a445ba`). This design covers what the register still
carries afterwards.

The register holds **26 rows whose disposition column reads `OPEN`. Only nine
are live**; the rest are archived originals, or rows whose closure sits in a
later column and whose `OPEN` text is retained history. That ratio is itself
the reason DR-01b existed, and it is why this design was written by parsing
the table rather than by grepping for the word.

## The finding that shaped this design

**Two of the six items that looked like remaining work are not remaining
work.** Both were reported as open on the strength of a register row, and both
rows are stale. This is the fourth time in two programs that a task premise
has failed on first contact with a command, so it is recorded here as the
design's opening fact rather than as a footnote.

### 1. The threshold this register asks someone to choose was chosen

Row 121 reads *"STILL OPEN ... this is now a live decision rather than a
blocked one"*, with the trigger *"Someone chooses the threshold against the
24-case denominator."*

**ADR-0058 chose it on 2026-08-17** — `relation_path_recall`, gated
**absolutely at 1.0** — with the user recorded as decision owner ("asked for
the target to be set"). It is implemented at `runner.py:861` and carries a
forty-line argument for why an absolute gate is the right *shape* here, so the
denominator arithmetic the row asks about never decided anything.

What is genuinely wrong is smaller, and it is a **comment**, not a gate. That
argument still says *"The denominator is 24 ... 21 declare one edge, and one
each declare two, three and five."* Measured now:

| | Then | Now |
| --- | ---: | ---: |
| Cases declaring relations | — | **35** |
| Measured cases (the denominator) | 24 | **27** |
| Declared edges | — | **44** |
| Distribution | 21/1/1/1 | **30 x1, 3 x2, 1 x3, 1 x5** |

DR-07 (ADR-0076) moved it. The row should be **closed citing ADR-0058**, and
the comment corrected — not left as an open invitation to re-decide a settled
gate against numbers that are wrong.

### 2. The query-backed engine already emits signatures

The follow-up hanging off row 93 reads: *"the query-backed engine emits no
`signature`, so its disambiguator is an ordinal ... teaching it signatures
converts that to stable identity for four languages."*

`parsing/registry.py` records otherwise, twice:

- **1.8.0 (ADR-0071):** Java and Scala emit a signature — parameter types
  only, never names. **Go and Rust deliberately emit `None`: measured, a
  signature separates none of the collisions they actually produce.**
- **1.9.0 (ADR-0074):** a `discriminator` joins the signature in identity, and
  all four query-backed languages supply one.

So "teach them signatures" is **done for the two languages where it helps, and
measured away for the other two.** The proposed remedy is already shipped. The
live remainder is only the residual it left, and that residual is a
*measurement* question, not a build.

## What is actually left

Nine live rows, sorted by what they need rather than by what they are about.

### Needs an instrument before it can need a fix (1)

**A question beginning with the word "Trace" is not routed to the trace
channel.** Every rule in `conversations/intent.py` is anchored at both ends and
admits one trailing subject token, so `Trace the flow from mount.` reaches the
trace channel and `Trace order data from frontend to backend.` falls through to
`text`. Measured on q032's own fixture, the trace channel returns top-1
`loadOrder` with both expected ranges contained; the text channel a real user
reaches ranks `Order flow` first and gets top-1 **wrong**.

The corpus cannot see this, and not by accident: `engine_adapter._query_term`
feeds the declared symbol rather than the question, because Phase 1 measured
resolution accuracy and said so. **The harness bypasses the classifier by
design, so the product measures a channel a real user cannot reach for this
phrasing.**

Widening the regex without an instrument would be tuning against one hand-run
example. The instrument is cheap and general: **re-run the corpus with each
case routed by `classify(case.question)` instead of by its declared intent, and
report the delta.** One variable changes — the channel — because the routed run
keeps the corpus's own subject rather than the classifier's extracted target.
Subject extraction is a second axis and is deliberately not confounded with
this one.

That produces a number for routing as a whole, not just for trace, and it is
what makes the widening ruling answerable. It is the DR-09 precedent: *a claim
about agreement is made by running the tool, not by reasoning about the
corpus.*

### Needs evidence, and deliberately proposes no mechanism (1)

**783 collision groups remain on the ordinal**, of which ~718 are two
declarations sharing a name, a kind *and* one enclosing scope. ADR-0074 took
separation from 221 to 419 of 1202 groups; 1202 − 419 = 783 is that residual,
not a pre-existing count.

**No mechanism is proposed, on purpose.** The register says it may not be an
identity defect at all — if `Align.F` renders one qualified name for two
members a reader would call distinct, the qualified name is the defect — and
guessing at a mechanism is what produced ADR-0072's five-fold error. The
honest next step is to **classify the residual**, which
`report_symbol_collisions.py` can already almost do: it buckets by
`(qualified_name, kind)` and knows which groups separate. It cannot yet say
*what the unseparated ones look like*.

### Buildable, and closes a defect that has recurred twice (1)

**A `-Semantic`-gated artifact goes stale unnoticed.** DR-01b built the cheap
half: `test_tracked_artifact_metric_keys.py` catches a *schema* drift with no
extras installed. The expensive half was left as a ruling — "should `-Semantic
--check` stop being opt-in?"

**It should not, and the ruling as phrased has no good answer.** Gate condition
2 requires an installation without the optional extras to behave exactly like
Phases 0-6; `check_phase7.ps1` is shaped around that and says so in its header.
Making the semantic block mandatory would make the deterministic gate depend on
torch, "which is precisely the regression the condition exists to catch".

The real gap is narrower than the ruling. Both stale incidents shared one
signature — **added metric keys, no value change** — and that is now caught.
What is still uncaught is an artifact going stale because **its inputs moved**:
DR-06 added the `delivery_scheduler` fixture and four semantic cases, which
changes what those artifacts should say, and nothing fails until someone opts
in.

Inputs can be hashed **without installing anything.** Stamp the semantic
dataset's content digest into the artifact when it is generated, and assert in
an ordinary test that the stamp matches the corpus on disk. A corpus edit
without a regeneration then fails in every routine run, naming the artifact.
That closes the row on its merits instead of trading it against gate
condition 2.

### Owed a measurement, now unblocked (1)

**Ranking sensitivity.** 22 of 23 cases added on 2026-08-15 are not
reversal-sensitive. The row's own instruction is *"re-measure after DR-08, not
before"*, because ADR-0075 made traversal depth explicit and depth is exactly
what decides whether a returned symbol is a distractor. **DR-08 is done**, so
the measurement is owed. Like DR-09's, it should be a committed tool: the count
in this row has already been wrong once (0 of 23, when q053 made it 1).

### Owed a brief; the ruling is the user's (2)

- **Re-gate Phase 4 on the realistic profile?** `measure_phase4_perf.py`
  already grows a `--profile realistic` tree, and the ≤ 2 s refresh target is
  missed there from 80 modules up while the tracked synthetic baseline passes.
  Whether the gate should move is a scope decision about the gate itself, and
  it needs the miss curve measured across sizes before anyone rules.
- **Close the `TRACE_FLOW` row as a working convention?** DR-09's audit
  recommends yes: `TRACE_FLOW` agrees with the classifier on 1 of 5 cases
  against `EXACT_SYMBOL`'s 0 of 36, so the label is not systemically wrong and
  the row's framing was the defect. The brief exists; only the ruling is
  missing.

### Nothing to build, and that is the finding (3)

Three flakes: the Firefox cross-suite conversation leak, the concurrent
full-suite failure, and one `check_phase7` run that exited 1 while printing
every step as passing. **Each already has a DR-01 capture recipe and none has
reproduced.** Chasing an unreproduced flake without a capture produces a guess,
which is what the recipes exist to prevent. They stay open, unworked, until one
recurs — and this design says so explicitly, so the next reader does not read
the silence as an oversight.

## Shape of the work

Seven tasks. **Four are instruments, one is a guard, one is hygiene, one is a
brief.** No product behaviour changes anywhere in this plan, and no version
constant moves, so **no reindex.** The one change that would alter product
behaviour — widening the classifier — is deliberately not planned: it is
conditional on a ruling that RW-01's number exists to inform.

That asymmetry is intentional and worth stating. This tail is mostly
measurement because the register's remaining rows are mostly *claims that were
never re-run*. Two of them turned out to be false today.

## Non-goals

- **No corpus edits to move a number** (ADR-0003). RW-01 reroutes cases at
  runtime and writes nothing back.
- **No mechanism for the 783.** RW-05 classifies and stops.
- **No new gate conditions.** RW-06 produces a brief; re-gating is the user's.
- **No flake archaeology.** See above.
