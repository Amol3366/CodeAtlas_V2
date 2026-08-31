# Design: closing the Deferred Register

- Status: proposed, awaiting user review
- Date: 2026-09-01
- Decision owners: user/product (asked for each remaining item to be planned)
  and implementing agent
- Related: ADR-0060, ADR-0061, ADR-0062, ADR-0063, ADR-0064 (the preflight
  lineage), ADR-0069, ADR-0070, ADR-0071 (the symbol-identity lineage),
  `docs/plans/PLAN.md` (the Deferred Register itself)

## Context

Every phase task board is `complete`. The post-ADR-0069 program closed on
2026-08-31 with all six tasks done, and its handoff records that nothing is in
progress and nothing waits on the user. What remains is entirely in the
**Deferred Register** in `docs/plans/PLAN.md`: about twenty rows carrying an
`OPEN` disposition, each with a stated reason and a named trigger.

The register was created at the 2026-08-10 closeout precisely so the project
would have an end condition instead of a permanently seven-item list. This
design turns its open tail into a plannable program without breaking that
property: **nothing here is silently dropped, and a row leaves the register only
with a citation.**

## The finding that shaped this design

Exploration of one cluster — preflight performance, three rows — found that
**two of the three are stale**, and the mechanism is worth stating because it
will recur.

Both rows are dated 2026-08-18 and were written against ADR-0060's attribution
of preflight cost. **ADR-0064 was accepted later the same day and explicitly
corrects ADR-0060, ADR-0061 and ADR-0062.** A timer named `parse_base` was read
as timing parsing; it wraps `_analyze_state`, which lists, reads, parses *and*
resolves. Timed separately on the same view:

| Stage | Seconds | Share |
| --- | ---: | ---: |
| `list_files` | 1.25 | 0.4% |
| `read_file` (+ hash) | 0.07 | 0.0% |
| `parse` | 8.14 | **2.5%** |
| `resolve` | **310.24** | **97.0%** |

ADR-0064 then fixed resolution: **preflight 635.59 s -> 21.56 s** (median of
three), cold index ~343 s -> 32.64 s, resolution 313.97 s -> 3.55 s.

Consequences for the register as written:

- The row claiming *"632 s of a 635 s preflight is `parse_base` +
  `parse_target`"* is **factually superseded**. Its trigger — "someone designs
  the parse-reuse path" — is dead work: ADR-0064 puts content-keying the parse
  stage at a best case of **~1.3% of preflight**.
- The row claiming preflight is still O(repository) is **half stale**. The
  observation survives, and ADR-0064 restates it ("21.56 s is a much better
  constant on the same curve"), but the vehicle it names — stored-index symbols
  plus a ruling on when they may be trusted — was killed twice: by **ADR-0063**
  on arithmetic (only the target is indexed; the base is an unindexed commit),
  and by **ADR-0064** on proportion. **The ruling that row asks for should be
  withdrawn, not answered.**
- The row recording 10–12 minute `impact` runs is **live but cheap**: those
  observations are from 2026-08-13, five days before a 29x improvement.

This is not the first time. The 2026-08-21 register audit found five stale rows
in a single day. Two more were found here in one cluster, in about ten minutes,
with four clusters unexamined. **Planning work off unaudited rows would repeat
the failure the last two handoffs both recorded: the task's premise was the
defect.**

### A second, smaller finding: the register's notation is ambiguous

An item titled `~~original entry~~` means two different things:

- **Live, reworded.** The preflight rows above: the title was superseded, the
  `OPEN` disposition is current.
- **Archived original.** The nested-config-keys row: the defect was closed by
  ADR-0041 in the row *above* it, which ends "Original diagnosis follows", and
  the struck row preserves the original `OPEN` prose as history.

Only the pointer in the preceding row distinguishes them. An auditor reading
top-down will mistake a closed defect for an open one — this design nearly did.
Task 1 makes the distinction explicit rather than positional.

## Program shape

One program, six tasks, executed in this order. Cluster order **B -> A -> C ->
D** was chosen because B is measured already, A is the largest real engineering,
C protects both, and D cannot be scheduled at all (below).

| # | Task | Cluster | Depends on |
| --- | --- | --- | --- |
| 1 | Register staleness audit | all | — |
| 2 | Preflight: re-measure, then decide | B | 1 |
| 3 | Scala companion declaration form | A | 1 |
| 4 | Rust trait discriminator | A | 3 |
| 5 | Go enclosing scope | A | 4 |
| 6 | Corpus fixture shapes | C | 1 |

Tasks execute in numbered order. Task 6 depends only on Task 1 and could be
pulled forward if Tasks 3–5 stall on a ruling; it is placed last because the
three reindexes are the program's user-visible cost and should not wait behind
fixture work.

### Task 1 — Register staleness audit

**Every open row, checked against what landed after it.** Three checks, cheapest
first:

1. **Dated cross-check.** List every ADR accepted after the row's date; ask
   whether any supersedes it. This is what caught the preflight rows.
2. **Trigger liveness.** The register is trigger-based, so a row whose reopen
   condition has already fired, become impossible, or now authorises work that
   pays nothing is dead regardless of whether its prose still reads plausibly.
   The parse-reuse row fails here even though its wording is unobjectionable.
3. **Re-measure — only where a row carries a number a cheap command can
   re-check.** The performance rows and the real-repository collision counts
   qualify. Nothing else does.

Full re-measurement everywhere was rejected: most rows carry a *stated limit*,
not a number, and re-running the suite to confirm that a fixture does not exist
costs hours to learn what reading the corpus tells you in a minute.

**Honesty standard.** A row may be closed only with a citation to the record
that superseded it. "Looks stale" closes nothing. That is the standard the
2026-08-21 audit used, and it is why its five closures held.

**Also produced by Task 1:**

- The `~~original entry~~` notation disambiguated, so an archived original is
  marked as one rather than inferred from the row above.
- A **capture recipe** for each of the three flakes in cluster D, so the next
  recurrence is diagnosable instead of merely noticed.
- A **decision brief** for the open rulings — framed, with evidence and options,
  for the user to answer. Expected to be the **four** listed under "Open
  questions" below, not five: the parse invalidation ruling is withdrawn by this
  task rather than put to the user.

**Done when:** every open row is confirmed live, corrected, or closed with a
citation; PLAN.md is appended to, never rewritten; a handoff records the audit
with its evidence.

### Task 2 — Preflight: re-measure, then decide

Scope depends on Task 1's output, but the shape is known:

- **Re-measure preflight and `impact` end to end on a real repository** with the
  current tree. The live row's own trigger is "someone measures it properly."
- **Give `measure_phase4_perf.py` a realistic profile** — realistic file sizes
  and a Markdown-heavy tree. Until this exists, no perf claim from that harness
  is evidence: ADR-0064 showed its generated corpus emits no Markdown, so the
  entire quadratic term was structurally absent and a cleanly fitted exponent of
  1.14 was **no evidence**, not weak evidence.
- **Profile resolution's residual 3.55 s**, which ADR-0064 explicitly invites:
  "worth re-measuring rather than reasoned about." Decline it in writing if the
  measurement says it does not pay.

**No optimisation is scheduled here.** Whether any is warranted is what the
measurement decides. Committing to a fix before measuring is the exact error
ADR-0060 through ADR-0062 made three times.

**Done when:** warm p95 is measured on a real codebase against its declared
target, the harness profile is realistic, and resolution's residual is either
profiled or declined with reasoning.

### Tasks 3–5 — Symbol identity (ADR-0071's three mechanisms)

ADR-0071 measured that a signature separates only what overloading produces:
**221 of 1202 collision groups (18.4%)**. The remaining **981** need three
different mechanisms, and ADR-0071 records why they must stay separate —
bundling would hide which mechanism moved which ids, the same reason ADR-0069
kept this work out of its own fix.

| Task | Mechanism | Groups it addresses |
| --- | --- | ---: |
| 3 | Scala companion `trait`/`object` **declaration form** | **908** (scalaz) |
| 4 | Rust two-trait impls: **the trait** | 21 (ripgrep) |
| 5 | Go function-local types: **enclosing scope** | 5 (4 gin, 1 cobra) |
| — | **Java: no mechanism named** | **47** (gson) |

Each is its own ADR, its own `PARSER_BUNDLE_VERSION` bump, and **its own
reindex** — a real cost imposed on users three times, accepted deliberately in
exchange for attributable id movement.

Ordered by payoff: Scala first at 908 groups, then Rust at 21, then Go at 5.

**The three mechanisms do not cover the 981.** They account for 934. The
remaining **47 are Java groups in gson that a signature did not separate** —
gson had 99 collision groups and signature separated 52 — and **ADR-0071 names
no remedy for them.** This design does not invent one; it records the gap so it
is not mistaken for covered work. Establishing what those 47 actually are is a
cheap probe, and it belongs in Task 1's re-measurement rather than in a task
that presumes a fix.

**Done when, for each:** the collision groups of that mechanism's class fall to
**zero** on the repository that carries them, the totals above are reproduced
rather than assumed, symbol *counts* are unchanged (the ADR-0070/0071 check — an
identity change must move ids and not counts), and
`scripts/check_real_repos.ps1` exits 0.

### Task 6 — Corpus fixture shapes

Five open rows share one root cause: the corpus cannot see certain defects
because it lacks a **fixture shape**, not because it lacks cases. They collapse
into one task —

- a Git-backed change case (the corpus cannot express an ADR-0044-shaped
  defect);
- a fixture whose route literal sits alone on its line (the per-edge claim merge
  is unexercised);
- a second semantic fixture (the fusion corpus never grew);
- a fixture where a matched symbol's edge sits outside every returned chunk
  (ADR-0057's withheld-step branch is unreachable);
- an audit for same-named-symbol cases resting on name-based metrics alone.

**The `TRACE_FLOW` audit is deliberately not folded in.** ADR-0051 raised it and
declined to settle it; all six cases must be audited together, and it may turn
out to be an engine defect rather than a corpus limit. It stays a separate item
pending the ruling in Task 1's brief.

## What is deliberately not a task

**Cluster D — test-infrastructure flakes.** Three rows: concurrent full-suite
runs failing where the same tree passes solo; one `check_phase7` run that exited
1 while printing every step as passing; a `restart-persistence` cross-suite state
leak seen once on Firefox and not reproduced in three attempts. Two of the three
have no reproduction. "Chase it when it recurs" is the correct disposition, and
a plan built on an unreproduced flake is fiction. Task 1 gives each a capture
recipe instead. The phantom `exit 1` is the one that matters most — it
undermines every green gate claim, including the one recorded as this program's
baseline.

**Cluster F — accepted and non-engineering.** The unsigned packaged executable
needs a certificate, which is a purchasing decision. Seven Playwright tests
skipped on Chromium across five spec files are an unresolved upstream renderer
crash; Firefox runs all of them. The 1.05 GB packaged semantic tree was accepted
at the Phase 7 activation gate. None is plannable work, and writing plans for
them would be theatre.

**The two missed gate targets stay as recorded.** Phase 7 recall@10 **0.6667**
against >=0.90, and Phase 4 `changed_symbol_precision` **0.9375** against >=0.95,
ruled structural. Both were approved as missed by the user at their gates. They
are not reopened by this program; a future decision to chase either is a new
task with its own approval.

## Baseline

`scripts/check_phase4.ps1 -SkipSync` was run on 2026-09-01 against a clean tree
at `7c8250f`, before any work in this program:

```text
GATE_EXIT_CODE=0
Contract schema freshness   ok
Tests                       2398 passed, 3 skipped, 1 warning in 1402.84s
Lint                        All checks passed!
Types                       Success: no issues found in 389 source files
Dataset validation, Phase 0/3/4 baselines, ADR-0016 invariants   ok
```

2398 rather than the 2397 in the 2026-08-31 handoff is the expected +1 from
`6cc97e9`; its passing means the README figure and the collected count agree.

**One caveat recorded rather than explained away:** 1402.84 s against 486.78 s
on 2026-08-31, 2.9x slower, with unrelated reads running against the repository
throughout. Every correctness check passed, so this is read as machine load, not
regression — but it is *read*, not measured. The register already carries a
2026-08-21 retraction where exactly this was written up as a perf regression
before being withdrawn. A solo re-run belongs in Task 2, not in an assumption.

## Risks

- **The audit shrinks the program.** Task 1 may dissolve items in clusters A, C
  or D as it dissolved two in B. This is the intended outcome, not a failure;
  the six-task shape is provisional until Task 1 reports.
- **Three reindexes in sequence.** Tasks 3–5 each force users to reindex.
  Bundling them would remove two of the three, and ADR-0071 rejected that
  because it would hide which mechanism moved which ids. The cost is accepted
  with that reasoning on the record.
- **Task 1 depends on judgement, not a command.** Its output is only as good as
  its citations, which is why the honesty standard is stated as a hard rule
  rather than an aspiration.

## Open questions for the user

Answered as part of Task 1's decision brief, not before it:

1. May a `CALLERS`/dependency expectation name its own subject? (q005, q053 lose
   recall for declaring it.)
2. Should a case declaring no relations score relation precision at all?
3. What is the convention for declaring transitive results in a graph
   expectation?
4. `TRACE_FLOW` — audit all six cases together, and rule whether the label is
   systemically wrong.

**Expected to be withdrawn rather than asked:** "what invalidates a stored
parse", per the finding above.
