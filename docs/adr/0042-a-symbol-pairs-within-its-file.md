# ADR-0042: A symbol pairs within its file, and a container speaks through its members

- Status: accepted
- Date: 2026-08-11
- Decision owners: user/product and implementing agent
- Supersedes: none (completes ADR-0041, corrects a consequence of ADR-0025)

## Context

Reported by the user from a real change-preflight run, as three observations:
findings appeared **twice** under `medium`, **four times** under `low`, and
more further down; `high` showed none.

ADR-0041 had just closed the previous duplicate report, and the Deferred
Register carried the remainder as *"a separately-reported duplicate rendering
in the web Preflight screen is unreproduced and may be a UI issue."*

**It was not a UI issue.** `FindingsList.tsx` groups by severity and filters
each finding into exactly one group. The engine was emitting the entries.

### What reproduced

Two causes, both in the engine, and the multiplicities the user described are
the two of them multiplying together.

**1. Symbols were matched across files.** `symbol_diff` grouped by
`(kind, qualified_name)` with no file in the key. A configuration key name that
occurs in *N* files is then an *N*-versus-*N* match, which is not one-to-one, so
it fell to the ambiguous branch — *"report every base symbol as deleted and
every target symbol as added"* — producing `2N` changes for a name nobody had
touched.

That branch is right for what it was written for. Its input was wrong.

Reproduced in a throwaway git repository, **clean working tree**, `git status`
empty, blob bytes byte-identical to the worktree (checked with `od -c`, so this
is not ADR-0022's line-ending hazard):

```text
findings: 4
  medium CONFIG_VALUE_CHANGED | cases changed
  medium CONFIG_VALUE_CHANGED | cases changed
  medium CONFIG_VALUE_CHANGED | name changed
  medium CONFIG_VALUE_CHANGED | name changed
```

`a.json` and `b.json` each declared `cases` and `name`. **Nothing had changed
and preflight reported four findings.** On this repository the same run produced
1592 findings, five of them the identical line `cases changed` — one per
evaluation corpus file declaring a top-level `cases` key. The user's "twice" and
"four times" is the count of files sharing that key name; "later again more" is
five.

**2. Every ancestor restated its descendant's edit.** A mapping key's value *is*
its subtree, so editing `service.api.http.port` also moves the hash of
`service.api.http`, `service.api` and `service`. All four reported:

```text
medium CONFIG_VALUE_CHANGED | service changed
medium CONFIG_VALUE_CHANGED | service.api changed
medium CONFIG_VALUE_CHANGED | service.api.http changed
medium CONFIG_VALUE_CHANGED | service.api.http.port changed
```

ADR-0041 fixed the *leaf* side of this — a leaf no longer inherits its parent's
hash — and explicitly recorded the subtree residue. This is that residue.

**Neither is cosmetic.** Cause 1 invents findings for an unedited repository,
which is the abstention contract failing in the core wedge.

## Decision

**1. Occurrences sharing a file pair before anything cross-file is considered.**
A name common to several files is not ambiguous within any one of them. Only a
file holding exactly one occurrence on each side pairs; two occurrences of one
name inside a single file stay ambiguous and fall through, because guessing
between them would be the ungrounded move this module refuses to emit.

Pairing is by file **path**, not file id — an id is not stable across the two
state views, and comparing ids would pair nothing.

The move rule is unchanged: what survives same-file pairing, one occurrence on
each side, is still carried across as a move. A test pins that.

**2. A configuration key is reported through its members**, joining the class in
`_CODE_CONTAINER_KINDS`. The container's hash moved only because a descendant's
text lies inside it, and the reviewer wants the key that actually changed.

**3. Containment for a configuration key is its dotted path, not its line
range.** ADR-0041 gave every nested key its own line, so `service.api` and
`service.api.http` are single-line ranges that do not contain the leaf below
them — only the top-level key still spans its block, which is why folding on
line ranges alone reached one level and left the intermediates restating the
edit. The trailing dot is load-bearing: `service.apikey` is a sibling of
`service.api`, not a child.

**4. A derived `DOCUMENTS` edge targets the key it names.** It pointed at the
top-level container while its own `target_hint` said `service.port`, because the
dotted paths are summarized on the container. ADR-0025 made the leaf
addressable, so the edge can now name what it always meant. Folding the
container away without this would have lost the documentation link entirely —
which is how it was found.

This is the correction ADR-0039 made for `IMPORTS`, one kind across.

## Consequences

`RESOLVER_VERSION` **1.3.0 → 1.4.0**: relation targets changed, so **every
snapshot must be re-indexed**. No schema, contract, or migration change —
`SCHEMA_VERSION` stays 14 and `contract_version` stays `1.1`.

Measured on the fixture that reproduced it:

| | before | after |
| --- | ---: | ---: |
| Clean tree, nothing edited | 4 findings | **0** |
| One nested leaf edited | 4 findings | **1** |
| One-line `pyproject.toml` version bump | 8 (ADR-0041: 2) | **1** |

Phase 4 baseline, all in the same direction:

| Metric | before | after |
| --- | ---: | ---: |
| `containing_evidence_rate` | 0.6667 | 0.6824 |
| `exact_evidence_rate` / `valid_evidence_rate` | 0.5632 | 0.5765 |
| `finding_precision` | 1.0000 | 1.0000 |

`primary_evidence_recall_at_10` and `containing_evidence_recall_at_10` did not
move. Phase 0 and Phase 3 baselines reproduce byte-for-byte.

### Two corpus expectations were corrected, and why that is not moving a number

c012 and c014 declared a **leaf** symbol's evidence using its **parent's** line
range — `symbol: "service.port"` with `start_line: 1, end_line: 3`, which is the
range of `service`; and `symbol: "scripts.test"` with `4-6`, the range of
`scripts`. Corrected to `3-3` and `5-5`.

The justification is the narrow, checkable one ADR-0039 used, not "the number
improved": **the expectation names one symbol and gives another symbol's
range.** It was written before ADR-0025 made the leaf addressable, when a
configuration key's citation could only be its block.

Left as it was, `finding_precision` read 0.9167 — because `supported_findings`
requires a finding's evidence to appear in the declared evidence, and the
engine now cites line 3 where the corpus declared 1–3.

**The strongest evidence that the correction is right is what the corpus was
hiding.** Before this change c012 produced **two** `CONFIG_VALUE_CHANGED`
findings for one edit — one citing 1–3, one citing line 3 — and c014 two
`PACKAGE_SCRIPT_CHANGED`. The user's duplicate has been in the corpus since
Phase 4 and no metric ever saw it, because `expected_findings` is a **set of
codes**: a duplicate cannot fail a set membership test.

That is the ADR-0016 and ADR-0029 lesson again — the corpus is structurally
blind to the defect being fixed — and it is now the third time. **A set-valued
expectation cannot count.** Whether `expected_findings` should carry
multiplicity is left open rather than answered here; it would touch all 24 cases
and is a corpus design decision, not part of this fix.

## Alternatives rejected

**Deduplicate in the renderer.** It would have hidden a false finding rather
than not making one, and `evidence_ids` differ per occurrence, so the UI cannot
tell a duplicate from two real findings.

**Add the file to the grouping key outright.** Simpler, and it deletes cross-file
move detection — the property the module's opening docstring is about.

**Suppress ancestors in the finding rules instead of the diff.** The false
change would still reach impact analysis, `changed_symbols`, and every other
adapter. The diff is where "one edit is one change" already lives.

**Keep the `DOCUMENTS` edge on the container and refuse to fold a documented
key.** Preserves the duplicate in exactly the case a reviewer is most likely to
be looking at.

## Follow-ups

1. **A finding cannot be told apart from its twin.** The serialized `Finding`
   carries no `subject` and no file path — only code, title, description,
   severity, derivation, confidence and evidence. Two findings from different
   files render identically, and `FindingsList`'s React key
   (`${code}-${title}`) collides for them. This fix removes today's duplicates;
   it does not make a *legitimate* same-named pair distinguishable. Adding the
   subject to the contract is additive and worth doing.
2. Whether `expected_findings` should be a multiset (above).
3. YAML still compares subtree **text**, so re-indenting a block reports a
   change (recorded by ADR-0041, unchanged here).
