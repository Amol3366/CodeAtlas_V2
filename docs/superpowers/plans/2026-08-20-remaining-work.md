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
| Packaged zip | file date | **resolved 2026-08-20** — rebuilt from the verified tree; contents cross-checked, 0 files missing |
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

### P1-A · Finish language coverage: Go and Rust cases · **DONE 2026-08-20**

`go_app` and `rust_app` were admitted and the corpus went **73 → 80 query
cases**, completing coverage of all four ADR-0065 languages. The only source
edit was `SUPPORTED_FIXTURES`. **Every moved metric moved up**, which had not
happened on previous corpus growth, and the 0.98 denominator tripwire fired
again without margin being bought: 51 → 66 scored cases, one miss still clears.

**Go deliberately gets no import case, and refusing to write one was the
finding.** ADR-0066 rules a Go import stays `external`; an external edge carries
no `target_symbol_id`, so it never appears in a `relation_path` (ADR-0057). The
corpus vocabulary cannot express the ruled outcome, so a case written anyway
would pass whatever the engine did. q080 is the control instead — Rust's `crate`
is a keyword, so its import *does* resolve, which is the contrast that diagnosed
Go in the first place.

The original entry follows, kept because the traps it names are still real.

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

### P1-B · Change cases for Scala, Go and Rust · **DONE 2026-08-20**

Corpus **29 → 32 change cases**; all four ADR-0065 languages now have change
coverage. No source change at all — variant overlays, three cases, counts.

**c030 measures ADR-0067 on the change side**: mutating the extractor to ignore
the supplementary references query fails c030 *alone*, because Java, Go and Rust
ship member-call patterns and Scala does not. So Scala's impact analysis depends
on that ruling, not merely its symbol lookup.

**This is where `unmet_targets` emptied by dilution** — `changed_symbol_precision`
0.9483 → 0.9531 with c020–c022 still scoring exactly 0.50 each. Settled the same
day by emitting `changed_symbol_exact_cases` beside the mean; see P2 and the
Deferred Register. **Never cite "all §19.3 targets met" without it.**

The original entry follows.

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
| 5 | ~~"Python, TypeScript, and JavaScript source"~~ **updated 2026-08-20** | seven languages in two tiers, matching the registry |
| 12.2 | `POST /v1/messages/{id}/retry` and `.../feedback` | mounted under the conversations prefix |
| 12.3 | `POST /v1/query/stream` | **not implemented** |

**§5 needed no decision and is now done (2026-08-20).** An approved ADR changed
the profile and §5 defers to one, so recording it was bookkeeping — §25 lists
"new programming-language support" as needing approval, and ADR-0065 *is* that
approval. The line now carries the two-tier boundary, the ADR-0066 and ADR-0067
rulings, and why C#, Kotlin and the other five stay out. Verified against the
running registry rather than the docs: `parser_for` returns a parser for exactly
seven languages and `None` for every other name tried.

**Two more stale language lists were found in `AGENTS.md`. Both are now fixed
(2026-08-20)**, having been outside the original §5 ask:

- **§6.1** now names the query-backed engine, and records the two limits that
  are structural rather than incidental — no shipped `tags.scm` captures an
  import, and Go's receiver being a node *field* means a query-only design is
  **wrong** rather than incomplete. A new language must expect both, which is
  the part worth having in the contract instead of only in an ADR.
- **§19.2** now requires a fixture per query-backed language, **one each rather
  than one shared** — the engine's per-language data is exactly what varies, so
  a shared fixture would let one language's profile pass on another's
  evidence. Verified as satisfied on the day it was written: `java_app`,
  `scala_app`, `go_app`, `rust_app` all exist and are in `SUPPORTED_FIXTURES`.

Both are the same bookkeeping class as §5 and need no decision. The Phase
checklists at §22 also say "Python, TypeScript, and JavaScript", and those
**must not** be touched — they record what a completed phase delivered.

~~**§12 still needs a decision**~~ **RULED 2026-08-21 — ADR-0068. P1-C is
closed, and with it the last item in this plan that needed anybody.**

**§12.2: move the code.** The table above recorded the divergence without
evidence for either side. Checking source supplied it: the nested path
`/v1/conversations/messages/{message_id}/retry` **carries no conversation id**,
so the prefix was inherited from `APIRouter(prefix="/v1/conversations")` rather
than chosen — and `cancel`, the third operation on the same run lifecycle,
already sat at `/v1/message-runs/...` because it lives in `stream.py`. The
implementation disagreed with itself along the axis of which file a handler was
written in. Both routes moved to `/v1/messages/{message_id}/...`.

**§12.3: remove `POST /v1/query/stream`** rather than build it — specified in
Phase 0, never implemented, never missed. A documented endpoint that does not
exist is the `SECURITY.md` version table again.

Breaking, and that is why it needed the ruling. Blast radius was measured before
the change, not asserted: loopback-only, no tagged releases, one client with
generated types, and `feedback` had **no caller at all**. Neither route had a
Python test either, which is why nothing ever objected — they have one now, and
it is two-sided, so registering the new path while leaving the old one fails.
`contract_version` stays `1.1` deliberately: where an operation is addressed
changed, no payload did.

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

### P2-C · `SECURITY.md` · **DONE 2026-08-20**

Was the untouched GitHub template — "5.1.x ✅ / 4.0.x ✅", "Tell them where to
go" — on a public repository with a 206-line threat model.

**Rewritten against the threat model rather than from scratch.** No version
table: there are no tags, so a table of supported semver lines would be the same
fiction as the one removed. `main` is the only line and reports name a commit
SHA. The internal stamps (`SCHEMA_VERSION`, `contract_version`, parser bundle)
are called out as compatibility markers, *not* releases, because they are the
obvious thing to mistake for one.

In-scope is the six trust boundaries made concrete; out-of-scope is stated with
reasons, so the loopback API having no authentication reads as a documented
assumption rather than an oversight, and an argument against it is invited as a
model change instead of a report.

**One claim was checked before shipping and was false.** The draft directed
reporters to GitHub private vulnerability reporting;
`gh api repos/.../private-vulnerability-reporting` returned `{"enabled":false}`.
Pointing people at a channel that does not exist is the same defect as the
version table. Enabled on the user's decision, verified `{"enabled":true}`, and
only then linked. **Response times are deliberately not promised** — a
single-maintainer project publishing an SLA would be one more claim nothing
backs.

### P2-D · Re-measure packaged performance · *work*

`-Perf` has not run since **2026-08-10**, and the artifact has been rebuilt
twice since, across two `PARSER_BUNDLE_VERSION` bumps. The recorded p95 figures
in the README and the register describe an artifact that no longer exists.

Cheap to run, and it closes a claim that is currently stale rather than wrong.

### P2-E · Small, batchable · *work*

- ~~**The stale zip.**~~ **DONE 2026-08-20.** It was dated 2026-08-17 and did
  not match the folder beside it, because both rebuilds used `-SkipZip`.
  **It was worse than "stale":** the archive contained no `tree_sitter_java`,
  `_go`, `_rust` or `_scala` at all, and no `tags.scm` or authored queries — it
  predated ADR-0065 entirely. Installing it would have given a CodeAtlas that
  ran fine while silently supporting only Python and TS/JS, with no error to say
  the other four were absent. That is a quieter failure than the packaged build
  which could not start, and a worse one to ship.
  Rebuilt by reproducing `build_package.ps1`'s own archive step, retry included.
  Verified by content, not by exit code: 17414 entries against the old 17378,
  all four `queries/tags.scm`, all five authored `.scm` files, and **0 files
  present on disk but missing from the archive**. Note the archive was *not*
  extracted and run; the gate's `test_the_packaged_build_parses_a_query_backed_language`
  runs the binary in the tree, and the archive is a file-for-file copy of it.
- ~~**Delete the merged branch.**~~ **Local copy deleted 2026-08-20**
  (`query-backed-language-support`, was `7b97acc`), using `git branch -d` — the
  form that refuses anything unmerged, so it is self-checking. **The remote copy
  is deliberately still there:** deleting a remote branch is not locally
  reversible and was not authorised. 14 other merged local branches also remain;
  only the one named was in scope.
- **ADR-0047 cites an ADR-0049 that was never written** — a dangling reference.
- **`-SkipWeb -Perf` silently skips the measurement and returns 0.** The
  array-splat class is guarded; this one has nothing watching it, in a
  repository with a history of green runs that measured nothing.

### P2-F · Two small live-path defects · *work*

- ~~**The ambiguity message does not disambiguate.**~~ **FIXED 2026-08-20.** It
  printed `qualified_name`, identical for both candidates, so "ask again with a
  qualified name" was followed by `process, process` — naming the thing the
  caller had just typed, twice.

  **The fix reuses the resolver's own vocabulary rather than inventing a display
  format.** `find_exact` tries `qualified_name`, then
  `module_path || '.' || qualified_name`; those are the only two forms a caller
  can type back and have resolve, so the message now uses the shorter one when
  it already distinguishes the candidates and the module-qualified one when it
  does not. All-or-nothing rather than per-candidate, because a list mixing
  `process` with `beta.process` invites reading the difference as meaningful.

  **The test asserts the journey, not a string:** ask again with each name the
  message offered, and the ambiguity must be gone. That survives a change of
  display format, and fails correctly if the message ever offers something
  unqueryable — a file path, most temptingly, which reads as helpful and cannot
  be typed back in. The pre-existing ambiguity test could not catch the defect
  because `Alpha.shared` and `Beta.shared` are already distinct.
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
P1-A Go/Rust cases ──── DONE 2026-08-20
P1-B change cases ───── DONE 2026-08-20
P1-C §5 · §6 · §19 ──── DONE 2026-08-20; §12 DONE 2026-08-21 (ADR-0068)
P2-A, P2-B ──────────── DONE 2026-08-20; these two are what stop recurrence
P2-C, P2-E ──────────── DONE 2026-08-20 (zip, branch, SECURITY.md)
P2-F ────────────────── ambiguity message DONE; Java IMPORTS label needs a ruling
P2-D re-measure perf ── OPEN, needs nobody  ← the only work item left here
P2-E remainder ──────── ADR-0049 dangling cite; `-SkipWeb -Perf` silent skip
```

**Nothing in this plan now needs a decision.** P2-D is **DONE 2026-08-21** and
found a live regression rather than the stale number it went looking for — see
the Deferred Register. The **§5 language-list guard is DONE too**, widened to the
README's ADR count and packaged perf figures, all three of which had drifted:
`tests/unit/test_contract_language_profile.py` and three additions to
`test_readme_claims.py`, eight mutations, eight caught. P2-F's second half is a
ruling, not work.

**What is left:** the refresh-regression investigation (register row names the
next measurement), and P2-E's two remainders — ADR-0047's dangling ADR-0049
citation, and `-SkipWeb -Perf` silently skipping its measurement.

## What is deliberately not here

- **New languages beyond the seven.** C#/Kotlin ship no `tags.scm`; Ruby, PHP,
  Swift, C and C++ were measured and deferred. Each needs its own §25 approval.
- **Test edges and route detection for the query-backed four.** Explicitly not
  approved by ADR-0065.
- **A Phase 8.** Phases 0–7 are complete and closed out; a new phase is a user
  decision, not a consequence of this list.
