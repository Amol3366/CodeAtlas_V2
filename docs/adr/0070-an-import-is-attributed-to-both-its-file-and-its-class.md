# ADR-0070 — An import is attributed to both its file and its class

- Status: accepted
- Date: 2026-08-31
- Approval: the user, 2026-08-31, choosing option 2 of three presented after the
  per-case measurement below
- Supersedes: nothing. Closes the `IMPORTS`-label row open in the Deferred
  Register since 2026-08-19, and extends ADR-0065's query-backed engine

## Context

Python and TypeScript/JavaScript attach a file-level import to a **`MODULE`**
symbol spanning the whole file, so the cited import line sits *inside* the
symbol the edge is labelled with — 3 of 3 measured. No query-backed adapter
emits a compilation-unit symbol, so an import attaches to the **class** instead:
`OrderService` is defined at lines 5–15 and its `IMPORTS PaymentService`
evidence cites **line 3**. Measured 2026-08-21 across all four query-backed
languages: **4 of 4 outside**.

**This was never a §4.1 violation.** Line 3 *is* the import statement, so the
evidence genuinely supports the claim. What was inconsistent is the label model,
and the inconsistency falls exactly on the tier boundary.

A prototype emitting a compilation-unit symbol was measured on 2026-08-22 and
recorded as failing the Phase 4 gate: 12 metrics move, every one down, including
`exact_symbol_resolution` 1.0000 → 0.9545 and `relation_path_recall`
1.0000 → 0.9062, the latter gated at **1.0 absolutely** by ADR-0058. The record
attributed this to "a per-file `MODULE` being an extra retrieval candidate that
dilutes top-1 ranking and enters relation paths", and framed the choice as
*accept the tier difference, or pay a corpus-expectation update*.

**That framing was wrong, and the stated mechanism was wrong.** Re-measuring
per-case on 2026-08-31 (branch `imports-compilation-unit-measurement`, `dbb09fd`,
kept and never merged) reproduced all 12 figures exactly and then asked the
question nobody had asked: *which cases moved?*

**Only 3 of 80 query cases change — q069 (Java), q073 (Scala), q080 (Rust) —
and all three go from a correct answer to ABSTENTION.** They account for every
one of the 12 movements: `63/66 = 0.9545` and `29/32 = 0.9062`, to four places.
There is **no ranking dilution at all**; the module symbols cost nothing on any
ranking metric.

The mechanism is that the import edge moved *off the class and onto the
compilation unit*, so "what does `OrderService` import" stopped having an answer
and the engine correctly abstained. **That is an engine regression, not a stale
instrument** — the hypothesis six earlier investigations (ADR-0017, ADR-0018,
ADR-0024, ADR-0027, ADR-0038, ADR-0051) made worth testing, which does not hold
here.

The corpus was therefore **not** updated. Re-declaring q069 as
`app IMPORTS PaymentService` restores every number while declaring a *worse*
answer — laundering a regression into a passing metric, which is what ADR-0003
exists to prevent.

## Decision

**An import is attributed to the compilation unit *and* to the file's first
definition. Both edges are emitted, and both are true.**

1. **Every query-backed file emits a compilation-unit `MODULE` symbol**, spanning
   the file, named by the adapter's `module_path` (falling back to the file
   stem). Its range is **clamped to the file's real line count**: tree-sitter's
   root node ends one line past a trailing newline, and an unclamped range fails
   snapshot validation with "a staged symbol has a line range outside its file".
   This is not incidental — it is why the change is not the six-line edit it
   appears to be.

2. **The module edge is the structurally correct one.** Its cited line sits
   inside the symbol it is labelled with, matching Python and TS/JS. Measured:
   **4 of 4 inside**, closing the tier inconsistency.

3. **The definition edge is kept, unchanged.** It is the one a caller asks for.
   Java's one-public-class-per-file convention makes the class a truthful
   importer, and dropping the edge trades three working answers for label
   tidiness.

4. **Both edges cite the same line and differ only in source**, so they carry
   distinct `relation_id`s and neither hides the other.

**One engine change covers all four languages.** No adapter changed.

## Consequences

- **`PARSER_BUNDLE_VERSION` 1.6.0 → 1.7.0, and every existing snapshot is
  stale. Users must reindex.** A file now yields one symbol and one `IMPORTS`
  edge it did not before. `RESOLVER_VERSION` is deliberately **not** moved, on
  the ADR-0067 precedent: resolution draws the same conclusions from a reference
  as it always did; only the set of references changed.
- **No schema, contract, or migration change.** `SCHEMA_VERSION` stays 14 and
  `contract_version` stays `1.1`.
- **Every Phase 4 metric is byte-identical to the pre-change baseline**, and
  `targets_met` stays `true` with `unmet_targets` empty. Zero of 80 query cases
  differ. The corpus artifacts are unchanged, which is the point: the numbers
  were not restored by editing what is expected.
- Symbols grow by one per query-backed file. On the two-file fixtures that is a
  large proportional increase and it moves no metric.
- A query-backed file that defines nothing now yields a `MODULE`, so its imports
  are attributable where ADR-0069 had to drop them. That is a strict improvement
  on the `package-info.java` shape, which previously contributed no import edges
  at all.

## Alternatives rejected

- **Accept the tier difference.** Free, and the evidence was always truthful.
  Rejected: the inconsistency is permanent, and the measurement showed the fix
  costs nothing once the class edge is kept.
- **Emit the compilation unit alone**, as prototyped. Rejected: it is the option
  that produced the three abstentions. It buys label consistency by deleting
  three correct answers.
- **Update the corpus to expect the module-level answer.** Rejected under
  ADR-0003 — see Context. It restores the metrics by declaring a worse answer.
- **Suffix or otherwise change `qualified_name`.** Not considered here; ADR-0069
  settled that identity moves and names do not.

## Limits, stated

- **"Costs nothing measured" is not "costs nothing."** The corpus is eleven
  two-file toy fixtures, and module symbols may simply never rank into any
  case's top-10 there. This is the same limit that let ADR-0069's collision ship
  through seven phases of gates. `scripts/check_real_repos.py` is the instrument
  that can speak to real code, and it was run against all five pinned
  repositories for this change.
- **The definition edge attaches to the file's first definition, whatever its
  kind.** For Java and Scala that is the class, which is what makes it truthful.
  For Go and Rust it may be a function, so `Go IMPORTS payments` reads oddly.
  **This is unchanged behaviour** — `symbols[0]` already resolved to the first
  definition before this change — and is recorded rather than fixed, because
  fixing it is a separate question about what a Go file's importer *is*.
