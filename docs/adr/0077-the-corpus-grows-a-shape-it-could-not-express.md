# ADR-0077: The corpus grows two shapes it could not express

- Status: accepted
- Date: 2026-09-02
- Decision owners: implementing agent (DR-06); no user ruling was required —
  both changes close register rows on their own stated triggers
- Related: ADR-0044 (preflight sees only what it would index), ADR-0056 (the
  coarse-chunk penalty, measured on 14 cases over one fixture), ADR-0049 (a
  fixture re-includes a directory an ignore default excludes), ADR-0003 (the
  corpus is not edited to move a number), ADR-0023 (target profiles)

## Context

Two Deferred Register rows recorded the same class of gap: **a defect the
evaluation corpus is structurally unable to see.** Neither was a missing case;
each needed a fixture *shape* the corpus did not have.

- `predict_changes` compared two `DirectoryStateView`s, so `GitBlobStateView` —
  the view a real working-tree preflight reads its base through, and where
  ADR-0044's ignore-rule fix lives — never ran under the corpus at all.
- The semantic corpus was **14 cases over one fixture**, byte-identical since
  2026-07-31. ADR-0056's conclusion about rank fusion rests entirely on it.

## Decision 1 — a change case declares which view reads its base

`ChangeCase` gains `base_view: "directory" | "git_blob"`, defaulting to
`directory` so every existing case is unchanged and Git stays off the path for
all of them.

A `git_blob` case builds **one** working tree: the base state is committed and
read back through `GitBlobStateView`, then the target overlay is written over
the same directory and read through `DirectoryStateView`. That is deliberately
the shape `analyze_working_tree` uses — a committed ref against the tree on disk.

**Two directories could not have worked, and that is why no case existed
before.** The ADR-0044 defect is a *disagreement between two view
implementations* about which files exist. A comparison that uses one
implementation twice cannot produce it: both directory sides apply the same
ignore rules, so a tracked-but-ignored file is absent from each, and a case
asserting "no `SYMBOL_DELETED`" would pass with the fix **and** with it
reverted. Permanent green reads as coverage.

**c033 discriminates**, measured by removing the ignore filter from
`GitBlobStateView.list_files`:

| | changed symbols | findings |
| --- | --- | --- |
| with ADR-0044's fix | `['capture']` | `['RETURN_VALUE_CHANGED']` |
| without it | `['bundled_total', 'capture']` | `['SYMBOL_DELETED', 'RETURN_VALUE_CHANGED']` |

The fixture's `coverage/report.py` is tracked at HEAD and matched by the
`coverage/` ignore default. **`coverage/` was chosen over the obvious `dist/`
because this repository's own `.gitignore` excludes `dist/`** — a fixture file
under it could not be committed here at all. That is ADR-0049's collision
between a fixture's needs and an ignore rule, met a second time and avoided
rather than worked around.

## Decision 2 — the semantic corpus gains a second fixture

`delivery_scheduler` — retry backoff, duplicate suppression, and deadline
parking — with four conceptual cases (s015–s018). A different domain on purpose:
a second orders-shaped fixture would test the same vocabulary twice.

## Consequences

**Numbers move, and each movement has one named cause.**

| Metric | Before | After | Why |
| --- | ---: | ---: | --- |
| `changed_symbol_precision` | 0.9531 | **0.9545** | denominator 32 → 33 |
| `changed_symbol_exact_cases` | 29 | **30** | c033 scores exactly 1.0 |
| semantic `containing_evidence_recall_at_10` | 1.0 | **1.0** | unchanged |
| semantic `symbol_recall_at_10` | 0.9286 | **0.9444** | four cases answered |
| deterministic `containing_evidence_recall_at_10` | 0.8667 | **0.8947** | — |

**The precision movement is dilution and must not be read as improvement**
(ADR-0053). It is the third time that mean has drifted up on denominator growth
alone. The honest counterpart is `changed_symbol_exact_cases`, which rises
because a genuinely exact case was added and cannot be lifted by adding cases
that already pass.

The deterministic side of the semantic baseline keeps its two pre-existing unmet
targets; it improved rather than regressed. The semantic side stays
`targets_met: true`.

**One expectation was declared wrongly and corrected before landing**, recorded
because the reasoning is reusable. c033 first declared `PUBLIC_BEHAVIOR_CHANGED`
by analogy with the Rust case c032 — but Rust only falls through to that code
because ADR-0065's tier has no statement-level classification. Python has one,
and correctly returns `RETURN_VALUE_CHANGED`. **Generalising from a language
that lacks a classifier produced a wrong expectation about one that has it.**

A second correction followed: the case first declared the symbol's whole range
as evidence, and the engine cited the body span. c002 and c009 — the existing
`RETURN_VALUE_CHANGED` cases — already declare the body span, so the corpus
convention was against the first declaration, not the engine. The fixture also
had to gain a module docstring: without one, its only function shared the
module symbol's exact range, a collision no other fixture has because every
other changed symbol is nested inside a class.

## What this does not do

- It does not make Git a dependency of the other 32 change cases; each still
  compares two directories and spawns no subprocess.
- It does not widen what ADR-0056 measured. That record's conclusion was reached
  on 14 cases over one fixture and **must still be cited that way**; the corpus
  is larger now, but the measurement it rests on was not re-run here.
