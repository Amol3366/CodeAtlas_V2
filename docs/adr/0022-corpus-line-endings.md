# ADR-0022: A Tracked Baseline Encoded Local Working-Tree Drift

- Status: accepted
- Date: 2026-08-09
- Decision owners: user (approved the Phase 7 harness audit and this fix), implementing agent (record)
- Supersedes: none
- Extends: ADR-0003 (the corpus is not edited to improve a number)

## Context

`changed_symbol_precision = 0.2000` was carried in `documentation/memory.md` as
one of four unmet Phase 7 targets — read as an engine defect, and noted as
resting on a single change case: "an anecdote with a decimal point".

It was not an engine defect. It was not even a corpus defect.

The semantic corpus has one change case, `sc001`, declaring `shipping_for` as
the changed symbol. The engine reported five: `apply_discount`, `shipping_for`,
`subtotal`, `tax_for`, `total_for` — every function in `pricing.py`. Diffing the
variant against the base showed all 42 lines differing while the visible content
was identical apart from `shipping_for`:

```
base    src/orders/pricing.py   CRLF=0   LF-only=42
variant src/orders/pricing.py   CRLF=42  LF-only=0
```

`diff --strip-trailing-cr` shows the real change touches only `shipping_for`.
The engine was right: the change engine hashes bytes and diffs lines, and
byte-wise every line in that file *had* changed.

**`.gitattributes` already prevents this.** It declares `* text=auto eol=lf`
with a comment naming this exact failure — "the evaluation corpus declares gold
symbol ranges, evidence line numbers, and content hashes against files as they
were authored — with LF … the Phase 4 corpus fails on a fresh clone while
passing for whoever wrote it." Both files carry identical attributes
(`text: auto`, `eol: lf`), and the committed object is LF.

So the CRLF did not come from checkout. The file had been rewritten locally with
CRLF at some point and never restored. Deleting it and running
`git checkout -- <path>` produced LF, and `changed_symbol_precision` went to
1.0000 — matching the declared expectation exactly.

**The consequence is the serious part.** `baseline-phase-7.json` is gated
byte-for-byte by `check_phase7.ps1`. It was generated against the drifted tree,
so it recorded 0.2000. Running `--check` on a correctly-checked-out tree exits
**5 (stale)**. The tracked artifact did not reproduce on a clean clone, and had
not for as long as the drift existed.

### Why nobody saw it

Git's own reporting hides this, in two different ways depending on stat state:

- When the working file's stat information still matches the index, git skips
  the content comparison entirely and reports a **completely clean tree**. That
  is the state this repository was in throughout the audit.
- Once the stat changes, git reports ` M` — but `git diff` is **empty**, because
  `text=auto` normalises CRLF away when comparing. A reviewer sees a modified
  file with no changes and a warning that "CRLF will be replaced by LF the next
  time Git touches it".

Neither view shows a byte difference, and the evaluation reads bytes.

## Decision

**1. Restore the file so `.gitattributes` applies.** This is a restore, not an
edit: the committed object was already LF, so the fixture's tracked content is
unchanged and the corpus diff is empty. ADR-0003 is not engaged — no
expectation, symbol, question, or range was touched.

**2. Regenerate `baseline-phase-7`.** `changed_symbol_precision` 0.2000 →
1.0000 in both the deterministic and semantic columns, and the metric drops out
of `unmet_targets` in both. The new artifact is the one a fresh clone
reproduces; the old one never was.

**3. Guard the drift git cannot show.**
`test_every_corpus_file_has_lf_endings_in_the_working_tree` reads the bytes of
every file in all three corpora and fails on any CRLF. It is parameterised per
corpus so a failure names which one.

## Consequences

**Phase 7 has three unmet targets, not four.** `changed_symbol_precision` is met
at 1.0000. The remaining three are `exact_symbol_resolution` (0.2857),
`valid_evidence_rate` (0.0563), and `primary_evidence_recall_at_10` (0.6667).

No engine code changed. No corpus expectation changed. The metric moved because
the bytes under it were restored to what the repository already declared they
should be.

The guard passed the moment it was written, so it was mutation-checked by
rewriting the same file with CRLF: the guard fails and names `semantic_cases`,
while `git diff` stays empty throughout. Restored, it passes again.

### What the audit found on the query side, recorded here so it is not lost

`exact_symbol_resolution = 0.2857` on this corpus is a **ranking** result, not a
retrieval failure. Per-case, the expected symbol is inside the top 10 for **11
of 14 cases** (`symbol_recall_at_10 = 0.7857`); only s001, s007, and s013 miss
entirely. The questions are deliberately fuzzy ("Can a promotion ever push the
price below nothing?") and several expected answers are **document headings**
rather than code symbols, so top-1 spans two different kinds of thing.

`_unmet_targets` applies **one dataset-agnostic target table** to both corpora,
so the 0.98 written for `EXACT_SYMBOL` lookup is applied unchanged to conceptual
search. Whether that corpus should instead be gated on `symbol_recall_at_10` and
`containing_evidence_rate` is the open ruling — the same one
`valid_evidence_rate` has been waiting on, now with two corpora's evidence
behind it.

One genuine weakness is visible and is not a measurement artifact: s003, "When
does a customer avoid paying for delivery?", returns `OrderRepository.for_customer`
— matched on the word "customer". That is the same family as the lexical
stopword defect that was worth +0.53 recall during P7-06.

`predict_conceptual` itself was audited for the defects found in
`predict_exact_symbols` and **has none of them**: no fixture gate, the question
is asked verbatim by documented design, and projecting evidence labels as
`ranked_symbols` is correct for conceptual intent.
