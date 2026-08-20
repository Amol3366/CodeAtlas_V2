# Remaining Work

Status: proposed. Supersedes `2026-08-19-post-adr-0065-program.md`, whose P0 and
most of P1 are delivered.
Date: 2026-08-20
Authority: `AGENTS.md` is the contract. Live status is `docs/plans/PLAN.md`.

**What changed since the last plan.** Everything in P0 and three of four P1
items are done: the branch merged, both ADR-0065 limits ruled (ADR-0066,
ADR-0067), the Chromium failure reproduced and ruled, the package rebuilt twice
— which found and fixed a **critical** packaging defect — and Java and Scala
both measured. What follows is what is actually left.

**Premises checked, not assumed** (a stale premise is this project's
most-recorded planning failure — it has produced a wrong plan three times):

| Premise | Checked by | Result |
| --- | --- | --- |
| Which languages have corpus coverage | counting cases per fixture | Java 4q/1c, Scala 4q/0c, **Go and Rust have no fixture at all** |
| CRLF drift | `git ls-files --eol` | **resolved** — the one remaining is the deliberate ADR-0043 fixture (`attr/-text`) |
| Merged branch | `git branch --merged` | still present, safe to delete |
| Packaged zip | file date | **2026-08-17** — predates two rebuilds |
| Working tree | `git status` | clean, `main`, synced |

## Urgency scale

| Level | Meaning |
| --- | --- |
| **P1 — next** | Real capability or real risk, and nothing blocks it |
| **P2 — scheduled** | Worth doing, no clock |
| **P3 — deferred** | Named trigger reopens it; do not start |

There is deliberately **no P0**. Nothing is currently on fire, nothing is
blocked on a decision, and saying so is more useful than inventing urgency.

---

## P1 — next

### P1-A · Finish language coverage: Go and Rust cases · *work*

**Go and Rust have no evaluation fixture at all** — not thin coverage, none. Of
the four languages ADR-0065 shipped, two are measured and two are invisible to
every metric.

This is the same path walked twice now, and the traps are known: a new fixture
forces the `SUPPORTED_FIXTURES` decision; the two `ROWS` tables in
`test_findings.py` and `test_impact_cases.py` are **coverage** guards, not count
guards, so grepping the old number will not find them; four cardinality guards
and `test_threshold_granularity`'s denominator tripwire will fire.

**Go's cases must encode ADR-0066**, not work around it: an import expectation
should assert the edge is *recorded and external*, mirroring the inverted test,
so a future matching policy cannot land silently. **Rust is the only one of the
four whose imports resolve** (`crate` is a keyword), which is worth a case of
its own — it is the contrast that diagnosed Go.

**State the arithmetic before writing.** At 59 scored cases one miss clears
0.98; adding ~8 keeps that. The corpus has grown 51 → 59 without buying slack,
and that property should survive this too.

### P1-B · Change cases for Scala, Go and Rust · *work*

`scala_app` has **zero** change cases and `java_app` has one. Changed-symbol
detection is the headline ADR-0065 capability and is measured for exactly one
language.

Scala's is the most valuable: its body classification falls through to
`PUBLIC_BEHAVIOR_CHANGED` like Java's, but **nothing has ever exercised a Scala
diff**, and ADR-0067 changed what a Scala file yields.

### P1-C · Reconcile `AGENTS.md` with the implementation · *decision + work*

Carried unchanged from the last plan and still the only item needing a decision:

| § | Contract says | Implementation |
| --- | --- | --- |
| 5 | "Python, TypeScript, and JavaScript source" | seven languages since ADR-0065 |
| 12.2 | `POST /v1/messages/{id}/retry` and `.../feedback` | mounted under the conversations prefix |
| 12.3 | `POST /v1/query/stream` | **not implemented** |

**§5 needs no decision** — an approved ADR changed the profile and §5 defers to
one, so it can be updated as work. **§12 does**: move the contract, or move the
code. §25 makes a breaking API change an approval matter, so it is not mine to
pick.

---

## P2 — scheduled

### P2-A · A guard so README claims cannot drift · **DONE 2026-08-20**

Still the cheapest high-leverage item. Nothing covers `README.md`; that is why
five figures and a wrong tool count shipped. A test deriving the version
constants, MCP tool count and quoted metrics from source would have caught every
one — the same shape as the packaging guard added 2026-08-19, which was written
after the identical failure.

### P2-B · Widen the LF guard beyond the corpus · **DONE 2026-08-20**

**The cleanup half is done**: every drifted file was normalized as it was
touched, and the only `w/crlf` left is the deliberate ADR-0043 fixture, held by
an explicit `-text` attribute.

**The durable half is not.**
`test_every_corpus_file_has_lf_endings_in_the_working_tree` is scoped to
`tests/evaluation`, so it protects the corpus and not the product — which is why
18 files drifted unnoticed. Widening it is what stops a third occurrence.

**Done: `tests/unit/test_working_tree_line_endings.py`, two assertions.** The
scope is derived from `git ls-files --eol`, not from a list of directories —
deliberately, because a list that must be extended and nothing enforces is the
defect this project has now hit five times. A directory is covered the day it is
committed.

The two assertions ask different questions: whether anything *has* drifted, and
whether anything is *permitted* to. The second catches a file marked `-text`
while its bytes are still LF — a silencer one commit before it matters, and
invisible to the first. Both were proven to fail: CRLF drift, drift plus a
`.gitattributes` silencing attempt (both fire; the skip is a hard-coded path, so
editing attributes cannot turn it off), a latent `-text` exemption, and a
mixed-ending file. The corpus guard stays: it reads bytes off disk, so it sees
an *untracked* fixture that `git ls-files` cannot.

### P2-C · `SECURITY.md` · *work*

Still the untouched GitHub template — "5.1.x ✅ / 4.0.x ✅", "Tell them where to
go" — on a public repository with a 206-line threat model. Twenty minutes, and
it is the file a security-minded reader opens first.

### P2-D · Re-measure packaged performance · *work*

`-Perf` has not run since **2026-08-10**, and the artifact has been rebuilt
twice since, across two `PARSER_BUNDLE_VERSION` bumps. The recorded p95 figures
in the README and the register describe an artifact that no longer exists.

Cheap to run, and it closes a claim that is currently stale rather than wrong.

### P2-E · Small, batchable · *work*

- **The stale zip.** `dist/codeatlas-win64.zip` is dated 2026-08-17 and does not
  match the folder beside it. Both rebuilds used `-SkipZip`.
- **Delete the merged branch.** `git branch -d` refuses anything unmerged, so
  the safe form is sufficient. The remote copy too.
- **ADR-0047 cites an ADR-0049 that was never written** — a dangling reference.
- **`-SkipWeb -Perf` silently skips the measurement and returns 0.** The
  array-splat class is guarded; this one has nothing watching it, in a
  repository with a history of green runs that measured nothing.

### P2-F · Two small live-path defects · *work*

- **The ambiguity message does not disambiguate.** It prints `qualified_name`,
  identical for both candidates, so "ask again with a qualified name" is
  followed by `process, process`. `find_exact` tier 2 *does* disambiguate.
- **A Java `IMPORTS` edge cites a line outside the symbol it is labelled with**
  (found 2026-08-19). Not a §4.1 violation — line 3 *is* the import — but the
  label model is inconsistent, because Java emits no module symbol where Python
  does. Needs a ruling: accept it, or emit a compilation-unit symbol.

---

## P3 — deferred, with triggers

| Item | Why not now | Reopens when |
| --- | --- | --- |
| `restart-persistence` sees another suite's conversation | Observed once with its mechanism captured; **three clean runs afterwards** | It recurs — capture the log *and* the `.e2e-tmp` database |
| Concurrent gate runs fail; one `check_phase7` exited 1 unattributed | Never reproduced | It recurs with output captured |
| Unsigned executable | A purchasing decision | A certificate is bought |
| 1.05 GB semantic tree | Accepted at the Phase 7 gate | A deterministic-only second artifact is wanted |
| `changed_symbol_precision` 0.9483 | Structural; the corpus is not edited to move a number | **Never** |
| `TRACE_FLOW` may be systemically mislabelled | Six cases carry it; three examined all classify as `text` | Someone rules the intent vocabulary |
| The "stated limit of the instrument" rows (fusion corpus, withheld-step branch, claim merge, ADR-0044 shape, ranking sensitivity) | Honest limits of corpus reach, not defects | Absorbed by P1-A/P1-B — re-read them after |
| Resolution's remaining 3.55 s unprofiled | ADR-0064 declined to claim it optimal; it is no longer the bottleneck | Preflight becomes slow again |

---

## Sequencing

```text
P1-A Go/Rust cases ──┬── P1-B change cases (same fixtures, reuse them)
                     └── P2-D re-measure perf (artifact already current)
P1-C §5 ─────────────── work; §12 waits on a decision
P2-A, P2-B ──────────── independent; these two are what stop recurrence
P2-C, P2-E ──────────── independent, minutes each
```

**One task in progress at a time.** P1-A is the substantive one; P2-C and P2-E
are the ones to take when a short slot is what is available.

## What is deliberately not here

- **New languages beyond the seven.** C#/Kotlin ship no `tags.scm`; Ruby, PHP,
  Swift, C and C++ were measured and deferred. Each needs its own §25 approval.
- **Test edges and route detection for the query-backed four.** Explicitly not
  approved by ADR-0065.
- **A Phase 8.** Phases 0–7 are complete and closed out; a new phase is a user
  decision, not a consequence of this list.
