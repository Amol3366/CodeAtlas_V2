# Post-ADR-0065 Program

Status: proposed. No task may start until the user sets or confirms its urgency.
Date: 2026-08-19
Authority: `AGENTS.md` is the contract. Live status is `docs/plans/PLAN.md`.
Predecessor: `2026-08-14-post-closeout-program.md`, whose six workstreams are
closed or absorbed into the Deferred Register.

**Goal:** give everything currently open a stated urgency, an owner class
(decision vs work), and a named condition that starts it — so the tail has an
order rather than a list.

**Premises checked, not assumed** (this project's most-recorded planning
failure is a stale premise, hit twice in one task on 2026-08-14):

| Premise | Checked | Result |
| --- | --- | --- |
| Branch gate is green | `check_phase4.ps1 -SkipSync` | **2313 passed, 2 xfailed, exit 0** |
| Branch is unmerged | `git log main..HEAD` | **21 commits ahead** |
| Package is current | `dist/codeatlas-win64/codeatlas.exe` mtime | **2026-08-17, predates ADR-0065** |
| Package build flags | `_internal/` contents | carries torch + lancedb → **`-SemanticLocal`** |
| `AGENTS.md` §5 profile | line read | still **"Python, TypeScript, and JavaScript"** |
| `AGENTS.md` §12 routes | OpenAPI vs contract | **two divergences** confirmed |
| Product docs carry ADR-0065 | grep | PRD, architecture, working-guide **yes**; phases.md **no** |

## Urgency scale

| Level | Meaning | Test for membership |
| --- | --- | --- |
| **P0 — now** | Cost of delay compounds, or it is a failure mode this repository has already suffered | Would waiting a week make it worse, not merely later? |
| **P1 — next** | Real risk or real value, but static | Does it change what a user or a metric can see? |
| **P2 — scheduled** | Worth doing, no clock | Would a reader call it obviously right? |
| **P3 — deferred** | Do not start; a named trigger reopens it | Is the blocker external, or a decision already taken? |

---

## P0 — now

### P0-1 · Merge `query-backed-language-support` into `main` · *decision + work*

The gate is green and the branch is 21 commits ahead. **The argument for
urgency is not the feature, it is the branch.** Unmerged work is this
repository's single most-repeated process failure:

- 2026-08-06 — `per-repository-embedding-model` sat two days, took the whole
  `documentation/` folder with it, and its merge silently resurrected an Ollama
  pull feature `main` had deliberately deleted the day before.
- 2026-08-11 — ADR-0043 was finished and left uncommitted for two days, with its
  handoff in a scratchpad file at the repository root.

Both were recorded as lessons. A third instance is now sitting at 21 commits and
two version bumps. Every day it waits, `main` moves and the merge gets harder.

**Do not batch anything else into this.** The two rulings below are *not*
blockers — both limits are declared `strict` xfails, which is precisely the
mechanism that lets them ship undecided.

Verification to repeat post-merge, because a merge is a change: re-run
`check_phase4.ps1 -SkipSync` on `main` and read the log, not the exit code.

### P0-2 · Rule the two ADR-0065 limits · *decision only*

Five minutes of your time each, and they gate P1-1's scope. Both carry full
diagnoses in their test files.

**Go import matching policy.** A Go import resolves `external` because its path
carries the module prefix from `go.mod`, which a single-file parse cannot know.
The cost is **asymmetric**: trimming to one segment makes a third-party
`github.com/foo/payments` resolve onto a local `payments`, *inventing* a
relationship §4.1 forbids. A miss is the safe direction; an invention is not.
Options: (a) leave as a permanent declared limit, (b) read `go.mod` — which
breaks the parser's pure-function-of-one-file invariant and needs its own ADR,
(c) a suffix-match policy with a stated minimum segment count.

**Scala member calls.** Its shipped `tags.scm` carries only
`(call_expression (identifier) @name)`, so `obj.method(x)` — most Scala calls —
is invisible. Closing it needs a supplementary references query; the profile
contract already has one authored slot (`imports_query`), so this is a contract
widening, not a hack. Options: (a) permanent declared limit, (b) widen the
profile contract to a second authored query.

**Recommendation:** rule Go as (a) and Scala as (b). Go's is a genuine
information-availability limit; Scala's is a missing query in a mechanism that
already supports authored queries.

---

## P1 — next

### P1-1 · Evaluation cases for Java, Go, Rust, Scala · *work*

**ADR-0065 names this its own largest remaining gap.** No metric measures any of
the four. Unit, integration, and security tests are real coverage but they are
not measurement, and §19.3's target table says nothing about these languages.
Until this lands, no surface may claim the four are *measured* — only that they
are implemented.

Hard constraints, each already learned here:

- **Gold is declared before the engine runs against it** (ADR-0003, ADR-0036).
  Deriving an expected range from engine output is what those records forbid.
- `java_app` is indexed but **deliberately not in `SUPPORTED_FIXTURES`**, because
  ADR-0017's guard asserts that constant equals the fixtures the *cases* use — a
  fixture with no cases fails the suite.
- **Check the denominator before and after.** `exact_symbol_resolution` scores 51
  cases against 0.98; one miss scores 0.9804 and passes, two do not. Roughly six
  hardcoded cardinality guards will fire — that is the corpus tripwire working.
- **Mutation-check with a mutation that matches the claim.** Reversing ranking
  failed 0 of 23 cases in the last corpus growth because most return one symbol;
  dropping the top hit failed 18 of 23.

This also discharges several standing "the instrument cannot see it" register
rows, which is a real secondary benefit worth stating.

### P1-2 · Rebuild the packaged artifact · *work*

The artifact is dated **2026-08-17**, two days before ADR-0065. It is stamped
parser/resolver `1.4.0` and **cannot index Java, Go, Rust, or Scala at all.**

**Build it with `-SemanticLocal`.** The outgoing artifact carries `torch`,
`lancedb`, and `sentence_transformers`; omitting the flag silently produces a
deterministic-only package that still looks like a successful build. This exact
mistake is recorded twice.

**Verify behaviourally, because exit 0 only proves PyInstaller ran.** Index a
Java fixture *with the packaged exe* and confirm the snapshot stamps 1.5.0/1.5.0
and that a cross-package import resolves. A version-only staleness check cannot
see an unversioned fix — also recorded here, from ADR-0037.

Do this **after** P0-1, so the artifact is built from `main`.

### P1-3 · Reconcile `AGENTS.md` with the implementation · *decision + work*

Three divergences in the release-blocking contract:

| §  | Contract says | Implementation |
| --- | --- | --- |
| 5 | "Python, TypeScript, and JavaScript source" | seven languages since ADR-0065 |
| 12.2 | `POST /v1/messages/{id}/retry` and `.../feedback` | mounted at `/v1/conversations/messages/{id}/…` |
| 12.3 | `POST /v1/query/stream` | **not implemented**; streaming is `GET /v1/conversations/{id}/stream` |

§5 is arguably self-healing — it opens "Unless an approved ADR changes the
profile" — but a reader of the contract still sees three languages. §12 is a
straight disagreement. **Each needs a direction chosen: move the contract, or
move the code.** Do not silently pick; §25 makes a breaking API change an
approval matter.

`documentation/phases.md` also has no ADR-0065 entry in its post-gate section.

### P1-4 · Chromium Playwright: failing, not skipping · *work*

Distinct from the seven known skips. Opened 2026-08-18, **reproduces on `main`**,
and two runs of one tree gave different failure sets — a flake signature. These
run inside the gate whenever `-SkipE2E` is absent, so they can redden a release
gate for a non-product reason.

First step is capture, not diagnosis: run the suite three times recording the
full output each run, and establish whether the failure set is stable. **Do not
pipe through `Select-Object -Last N`** — that is how the last attempt lost the
evidence.

---

## P2 — scheduled

### P2-1 · A guard so README claims cannot drift · *work*

Nothing covers `README.md`. This session found five stale figures and a wrong
tool count in it, all introduced by hand-edits after a source-derived rewrite.
A test that derives the version constants, the MCP tool count, and the quoted
metrics from source and the tracked artifacts would have caught every one.

Cheapest high-leverage item in this program. It is the same argument the
invariant corpus won: a rule enforced only by care is enforced only sometimes.

### P2-2 · Line endings, and widen the guard · *work*

Six tracked Markdown files still read `w/crlf` against a `.gitattributes`
declaring `eol=lf`. They normalize on commit and corrupt nothing, but the
working tree disagrees with its own declared rule, which is the state ADR-0022
warns makes drift invisible.

**The durable half is widening the guard.**
`test_every_corpus_file_has_lf_endings_in_the_working_tree` is scoped to
`tests/evaluation`, so it protects the corpus and not the product — the identical
"the rule only covers where the fixtures live" shape ADR-0043 recorded.

### P2-3 · `SECURITY.md` · *work*

Still the untouched GitHub template — "5.1.x ✅ / 4.0.x ✅", "Tell them where to
go" — on a public repository carrying a 206-line threat model and a local-first
privacy contract. Twenty minutes, and it is the file a security-minded reader
opens first.

### P2-4 · `TRACE_FLOW` may be systemically mislabelled · *work*

All three `TRACE_FLOW` cases examined (q003, q006, q035) classify as `text` in
the product's own `classify()`. **Six carry the label.** q006 was re-typed by
ADR-0051; q003 and q035 were deliberately left. Either the label is wrong across
the board or the classifier is — and the corpus disagreeing with the product
about its own intent is worth settling.

### P2-5 · The ambiguity message does not disambiguate · *work*

When a subject is ambiguous the engine correctly abstains and lists candidates —
but it prints `qualified_name`, which is identical for both, so "ask again with a
qualified name" is followed by `process, process`. `find_exact` has four tiers
and tier 2 (`module_path || '.' || qualified_name`) *does* disambiguate. Small,
live-path, user-visible.

### P2-6 · Profile resolution's remaining 3.55 s · *work*

ADR-0064 explicitly declines to claim resolution is now cheap — only that it is
no longer the bottleneck. `_derive_config_edges` and `_RouteIndex.handlers` are
the two largest remaining items and neither has been examined.

### P2-7 · Batch-able small items · *work*

- ADR-0047 forward-references an **ADR-0049 that was never written**; 0050
  deliberately skipped the number rather than hijack it. Dangling citation.
- **`-SkipWeb -Perf` silently skips the measurement and returns 0.** The
  array-splat class is guarded by `test_gate_script_invocations.py`; this class
  has nothing watching it, in a repository with a history of green runs that
  measured nothing.

---

## P3 — deferred, with the trigger that reopens each

| Item | Why it is not now | Reopens when |
| --- | --- | --- |
| Unsigned executable | A purchasing decision, not engineering | A certificate is purchased |
| 1.05 GB semantic tree | Accepted at the Phase 7 activation gate | A deterministic-only second artifact is wanted |
| `changed_symbol_precision` 0.9464 | Structural; c020–c022 split one diff into three cases that count each other's symbols | **Never** — the corpus is not edited to move a number (ADR-0003) |
| Concurrent gate runs fail; one `check_phase7` exited 1 unattributed | Observed, never reproduced, mechanism unconfirmed | It recurs **with the output captured** |
| The "stated limit of the instrument" register rows | All are honest limits of corpus reach, not defects | Absorbed by **P1-1**; re-read them after it lands |
| Reranking / generated explanations | Built, measured, declined — neither improved a metric | A corpus exists that can express reader-quality uplift |

---

## Sequencing

```text
P0-1 merge ──┬── P1-2 rebuild package (must build from main)
             └── P1-3 AGENTS.md reconcile
P0-2 rulings ──── P1-1 evaluation cases (scope depends on the Scala ruling)
P1-4 chromium ─── independent, start any time
P2-* ──────────── independent; P2-1 and P2-2 are the two that stop recurrence
```

**One task in progress at a time**, per the plan rules. P0-1 and P0-2 are the
only two that should be touched before anything else, and P0-2 is a
conversation rather than a task.

## What is deliberately not in this program

- **New languages beyond the seven.** C#/Kotlin ship no `tags.scm`; Ruby, PHP,
  Swift, C, C++ were measured and deferred on reference quality. Each needs its
  own §25 approval.
- **Test edges and route detection for the query-backed four.** Explicitly not
  approved by ADR-0065; each needs its own record.
- **Any new phase.** Phases 0–7 are complete and closed out. A Phase 8 is a user
  decision, not a consequence of this list.
