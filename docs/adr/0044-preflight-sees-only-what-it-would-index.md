# ADR-0044: Preflight sees only what it would index

- Status: accepted
- Date: 2026-08-13
- Decision owners: user/product (ruling) and implementing agent
- Supersedes: none (closes the item ADR-0043 left open)

## Context

ADR-0043 fixed the *bytes* half of a comparison and stated the remainder
plainly: with line endings normalized, an **unmodified** checkout of this
project still reported **26 findings** and drove `overall_risk` to `high` while
`git status` was empty.

The cause is not bytes but **existence**. The two views that form a comparison
answer "which files are here?" differently:

| View | Lists |
| --- | --- |
| `GitBlobStateView` | everything tracked at the ref |
| `DirectoryStateView` | whatever a repository scan would index |

A file that is tracked **and** excluded from a scan is therefore present in the
base and absent from the target, which is indistinguishable from a deletion. It
reports `SYMBOL_DELETED` at **high** severity.

**Four** separate mechanisms exclude a file from a scan. Measured on this
repository, base-only files:

| Mechanism | Files |
| --- | ---: |
| An ignore rule matches (`dist/`, `build/`, `target/`, `bin/`, `*.min.js`, …) | 11 |
| The opening bytes sniff as binary (a NUL) | 1 |
| The bytes will not decode as UTF-8 | 0 here |
| The file exceeds `max_file_bytes` | 0 here |

The fourth was found by reading the scanner rather than by a failing report:
the NUL sniff is only its first test, and Latin-1 prose carries no NUL yet is
skipped just the same. Two of these four cost nothing to observe on this
repository, which is the ordinary condition of a latent defect.

The 11 came from tracked corpus fixtures under `tests/evaluation/**/target/**`,
where `target/` is a built-in default written for Rust and Java build output.
The 1 was `tests/fixtures/upgrade/schema_0008.db`.

## Decision

**Preflight never considers a file it would not index.** The Git-blob view
applies the same exclusions a scan applies, so both sides of a comparison
describe the same world.

Ruled by the user on 2026-08-13, choosing this over the alternative below.

Three of the four mechanisms are implemented here:

1. **Ignore rules.** `GitBlobStateView` loads `IgnoreRules` for the root and
   drops every listed path the rules exclude. The rules are read from the
   working tree, not from the ref, because they are the same rules that decide
   what gets indexed — and it is the *index* the answer has to agree with.
2. **Binary content.** The scanner's NUL sniff is now the public
   `is_binary_content` in `repositories/scanner.py`, called by both.
3. **Undecodable content.** The scanner's UTF-8 decode, with its BOM fallback,
   is now the public `decode_text` in the same module, and the scanner uses it
   for the decode it was already doing.

Both shared functions are content tests rather than extension tests, so the
blob side must reach its verdict from the blob bytes. They are shared rather
than restated because two implementations of "would this be indexed?" would put
a file on one side of a comparison and not the other, which is the defect this
record exists to fix.

`decode_text` returns the decoded text rather than a boolean **so that sharing
it costs the indexing path nothing.** A predicate would have made the scanner
decode every file twice — once to answer the question and once to count lines —
and paying for a comparison fix on every index is the wrong trade.

### The fourth mechanism is deliberately not changed

An oversized tracked file does not merely disagree — `GitDiffAdapter.archive`
**raises** `ScanLimitExceededError`, so one 3 MB tracked CSV makes a repository
impossible to preflight at all, while the directory scan quietly skips the same
file with a `TOO_LARGE` warning.

That is a worse defect than the one being fixed and it is **not** what was
ruled. Turning a declared error path into a silent skip is its own decision, so
it is recorded in the Deferred Register with the asymmetry pinned by a test that
asserts today's behaviour. Nothing in this repository triggers it, which is
exactly why it would have gone unnoticed.

## Alternatives

**Make the target stop ignoring what Git tracks.** If it is tracked, it is real
— which is Git's own view and would remove the false findings too. Rejected:
ignore rules exist to keep built output, minified bundles, and vendored trees
out of the index, and this would pull all of them in through the back door of a
comparison. The user rejected it explicitly.

**Filter at the engine instead of the view.** Rejected as the same logic in a
place where only one caller benefits. The disagreement is a property of the
views, and a commit-range comparison puts `GitBlobStateView` on *both* sides —
fixing it in the view fixes both at once.

## Consequences

No schema, contract, migration, or version change. **No re-index is required by
this record**; indexing was never the side that was wrong.

Measured on this repository, unmodified working tree:

| | base-only files | findings |
| --- | ---: | ---: |
| Before ADR-0042 | — | 1592 |
| After ADR-0042 | — | 150 |
| After ADR-0043 | 12 | 26 |
| After this record | **0** | not re-measured; see below |

The two views now list byte-identical path sets on a clean tree — base-only 0,
target-only 0 — which is the property that should have held all along.

**The findings column is deliberately left unmeasured rather than filled in by
inference.** ADR-0043 recorded that all 26 came from these files, so zero
base-only files should mean zero findings, but a preflight run over this
repository needs a fresh index and one was still building when this record was
written. The file-level measurement is what was observed; the finding count is
what follows from it, and the two are not the same claim. Whoever next indexes
this repository should confirm it and amend this line.

### What is now invisible

A tracked file that is also ignored can be **added or deleted** without
preflight saying so. That is the deliberate consequence of the ruling: such a
file is outside what CodeAtlas indexes, so it has no symbols, no relations, and
no evidence to cite, and reporting on it would mean reporting on something no
answer could ever support. A reviewer who cares about committed build output
must look at Git.

### The blind spot behind it

Every baseline reproduces byte-for-byte, again. The corpus fixtures contain no
tracked-and-ignored file and no tracked binary, so **the corpus could not see
this defect either** — the fifth consecutive record where that is true
(ADR-0016, ADR-0029, ADR-0042, ADR-0043). The unit and integration tests are
the only coverage, and the defect was found the same way the last one was: by
running preflight on a real repository instead of a fixture.

`test_git_blob_state_view_lists_same_paths_as_directory_view` has asserted the
exact property this record restores **since Phase 4**, and passed throughout,
because its fixture has no file that any rule excludes. A true assertion over a
corpus that cannot exercise it is not coverage.
