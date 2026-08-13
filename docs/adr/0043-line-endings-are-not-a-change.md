# ADR-0043: Line endings are not a change

- Status: accepted
- Date: 2026-08-11
- Decision owners: user/product and implementing agent
- Supersedes: none (companion to ADR-0022, which ruled on the corpus)

## Context

Found while verifying ADR-0042 on a real repository rather than a fixture.

With ADR-0042's duplicates gone, a preflight of an **unmodified** checkout of
this project still reported **150 findings** across 35 files. `git status` was
empty.

The two views that form a comparison read from different places:
`GitBlobStateView` reads the blob, `DirectoryStateView` reads the working tree.
Git rewrites line endings between those two whenever `core.autocrlf` is on —
**the default on Windows**, which Section 5 names as the primary supported
environment. Both sides then hash raw bytes, so every line of such a file
differs and the whole file reads as changed.

Proven per file: normalized content identical, raw bytes different.

```text
src/codeatlas/api/routers/repositories.py
   normalised: 321f96ea484a4686 vs 321f96ea484a4686  -> SAME
   raw bytes : 321f96ea484a4686 vs c80d46fb23d85d35  -> DIFFER
```

**Git and CodeAtlas gave opposite answers to "did this file change?"** For a
change-assurance tool that is the worst possible disagreement: the whole product
is a second opinion on a diff, and it was contradicting the thing it reports on.

This repository has a `.gitattributes` pinning `eol=lf` precisely because
ADR-0022 hit the *corpus* side of this. It did not protect the engine, and a
user's repository will usually have no `.gitattributes` at all.

## Decision

**Normalize line endings on both sides of a comparison.** CRLF and lone CR
become LF in `GitBlobStateView` and `DirectoryStateView`, for both the hash used
to compare files and the bytes handed to the parser.

Both sides, or the fix would be worthless: agreeing at file level while parsing
different bytes just moves the disagreement down to every symbol hash inside the
file. A test pins that the two views return byte-identical content.

**A real edit still changes the hash** — only the endings stop counting. This is
deliberately the same answer Git gives under `text=auto`.

**Binary files are excluded.** A lone CR is meaningful inside a binary and
normalizing would corrupt it.

**`SnapshotStateView` is deliberately left alone.** It verifies bytes on disk
against a hash taken at index time, and no flow pairs it with another view — so
normalizing it would break its drift check to fix a comparison that never
happens. If it is ever used in a comparison, this is the first thing to revisit.

## Consequences

No schema, contract, migration, or version change. Indexing still hashes raw
bytes, so **no re-index is required by this record** (ADR-0042 already requires
one for its own reason).

Measured on this repository, unmodified working tree, after ADR-0042:

| | findings |
| --- | ---: |
| Before ADR-0042 | 1592 |
| After ADR-0042 | 150 |
| After this record | **26** |

Every Phase baseline reproduces byte-for-byte: the corpus fixtures are LF on
both sides, so nothing in the evaluation set could ever have seen this. **That
is the fourth time a defect has been invisible to the corpus** (ADR-0016,
ADR-0029, ADR-0042), and the second in one day.

### A limitation, stated rather than hidden

A change that is *only* line endings — running `dos2unix` across a tree — now
reports nothing. That is intentional and matches Git, but it is a real blind
spot: a reviewer who cares about endings must look at Git, not at CodeAtlas.

### What this does not fix

The remaining 26 findings are a **different defect, still open**: the two views
disagree about which files *exist*. `GitBlobStateView` lists everything tracked
at the ref; `DirectoryStateView` applies ignore rules. A file that is tracked
*and* matches an ignore pattern — `dist/`, `build/`, `target/`, `bin/`,
`*.min.js`, all built-in defaults — is therefore present in the base and absent
in the target, and reports as `SYMBOL_DELETED` at **high** severity, taking
`overall_risk` to `high` on a clean tree.

Here it is 26 findings from files under `tests/evaluation/**/target/**`, which
are tracked corpus fixtures that `target/` happens to match. Recorded in the
Deferred Register; not fixed here because it is a separate ruling — whether
preflight should consider a tracked-but-ignored file at all, and on which side.
