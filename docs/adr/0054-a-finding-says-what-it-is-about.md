# ADR-0054: A finding says what it is about, and cites the file it is about

- Status: accepted
- Date: 2026-08-17
- Decision owners: user/product (Task 3 assigned 2026-08-17) and implementing agent
- Supersedes: none
- Related: ADR-0042 (a symbol pairs within its file), ADR-0045 (the CLI verdict
  is a fourth renderer), ADR-0016 (a capability shipped to one surface),
  `AGENTS.md` §4.1

## Context

`extra_build.md` Task 3, recorded as ADR-0042 follow-up 1:

> A `Finding` carries no subject and no file path, so two *legitimate* findings
> sharing a code and title render identically and collide on `FindingsList`'s
> React key.

That description is accurate and it is the symptom, not the defect.

## The defect underneath

Reproducing the case — one repository, `orders.py` and `billing.py`, each
defining `total`, each changed the same way — produced two findings that shared
a code **and cited the same single evidence item**:

```
changed_symbols:  total  file=billing.py
                  total  file=orders.py

findings:  PUBLIC_BEHAVIOR_CHANGED  ev=ev_cf95…   (orders.py)
           PUBLIC_BEHAVIOR_CHANGED  ev=ev_cf95…   (orders.py)   <-- same citation
```

`_finding_citations` resolved each draft through

```python
by_name = {item.qualified_name: item for item in report.changed_symbols}
change = by_name.get(draft.subject)
```

A qualified name is not unique across a repository. Two `total`s collapse to
whichever the dict comprehension saw last, so **the finding about `billing.py`
cited lines in `orders.py`** — a §4.1 violation, because the citation does not
support the claim; it is about different code in a different file.

**This is ADR-0042's ruling reaching a surface that ruling did not touch.**
ADR-0042 fixed exactly this class in `symbol_diff` — "a config key name in *N*
files was an *N*-versus-*N* ambiguous match" — and its remedy was to pair within
the file first. The same file-less keying survived one layer up, in the step
that turns a finding into a citation.

The ambiguity begins earlier still: `FindingDraft.subject` is a bare string, so
by the time the citation step runs, the two drafts are already indistinguishable.

## Decision

**A finding is located, not just named — at every step.**

1. **`FindingDraft` carries `subject_file`**, set from the `SymbolChange` the
   draft was built from. `None` for file-level and architecture drafts, whose
   subject is already a path or a rule source.
2. **The citation step keys on name *and* file.** A symbol draft resolves
   **only** by location; there is deliberately no fall back to the name, because
   a wrong citation still renders as a perfectly valid finding and the failure
   would be silent.
3. **`Finding` gains optional `subject` and `file_path`**, so the pair is
   legible on every surface rather than recoverable only by chasing an opaque
   evidence id.

### The fields are derived, and that is why there is no migration

`extra_build.md` predicted "no migration is needed". That was right, but not for
the reason given — findings **are** persisted, in `change_findings`, which has no
such columns. Storing them would have needed a migration *and* created a second
copy of a fact the citation already carries.

`locate_finding` derives the pair from the evidence the finding cites, and both
the fresh path and the rehydration path call it. One derivation cannot disagree
with itself; two could. The citation always identifies the subject because that
is what it was built to cite — `_cite` labels a symbol finding's evidence with
the changed symbol's qualified name, and `_cite_file` gives a file-level finding
an unlabelled citation of the path that *is* its subject, so `symbol or
file_path` reproduces the draft's subject in both cases.

It returns `(None, None)` for an unresolvable citation rather than inventing a
location. `contract_version` stays `1.1`, `SCHEMA_VERSION` stays 14.

## Consequences

**Six surfaces, and the fourth renderer was checked explicitly.** JSON follows
from the model; Markdown, PR and the CLI verdict gained a subject line; SARIF
needed **no new field** — it already carries the location in `artifactLocation`,
and mapping to the standard rather than inventing a parallel property is the
requirement. The web list renders the pair and keys on it.

Before, all four renderers printed two identical blocks. After, each names its
file, and SARIF emits two results with distinct URIs.

**The React key still needed care.** `subject + file_path` is not guaranteed
unique in principle, so the key falls back to the cited evidence id for a
finding with no location. Two findings sharing a code *and* a subject *and* a
file would be a duplicate, which is what ADR-0042 fixed.

### The web test had no teeth, and the mutation is what showed it

The first version asserted that both findings were *rendered*:

```
it("renders both, rather than collapsing them on a duplicate key", …)
```

Reverting the key to `code-title` left it **green**. React renders both children
whatever the key; a duplicate surfaces only as a console warning. The test's name
described a property it did not check.

Rewritten to spy on `console.error` and assert no "same key" warning, the
mutation fails. **Assert on the mechanism the defect actually produces** — the
rendered output was never going to show it.

Every change here is mutation-checked: restoring the name-only citation lookup,
dropping the population on the fresh path, dropping the derivation on the
rehydration path, removing the subject from the web render, and reverting the
key. All five fail.
