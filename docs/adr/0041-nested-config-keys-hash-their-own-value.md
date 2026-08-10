# ADR-0041: A nested configuration key hashes its own value, not the range it cites

- Status: accepted
- Date: 2026-08-11
- Decision owners: user/product and implementing agent
- Supersedes: none (corrects a consequence of ADR-0025)

## Context

Reported by the user from a real change-preflight run: `pyproject.toml` produced
what looked like duplicated findings — repeated `project changed` entries with
identical evidence.

Reproduced against this project's own `pyproject.toml` in a throwaway git
repository. Changing **one line** (`version`) produced **eight**
`CONFIG_VALUE_CHANGED` findings, **seven of them false**:

```text
project changed
project.optional-dependencies changed
project.optional-dependencies.semantic-local changed
project.optional-dependencies.semantic-openai changed
project.scripts changed
project.scripts.codeatlas changed
project.scripts.codeatlas-mcp changed
project.version changed          <- the only true one
```

**This is a consequence of ADR-0025, two days old**, in change preflight —
the product's core wedge.

ADR-0025 made nested configuration keys addressable symbols, which was right:
`service.port` had been searchable prose but not a citable symbol, and the fix
moved `lexical_resolution` 0.3750 → 0.6250. It also decided, deliberately, that
a leaf whose own line cannot be located keeps its **parent's range** rather than
being given a guessed one — "a leaf whose line cannot be found keeps its
parent's range rather than a guessed one", because inventing a citation is
worse than a coarse one.

That decision stands. What was missed is that `_record` derives
`content_hash` from **the text of the cited range**. So a leaf inheriting its
parent's range hashes the *whole parent block*, and any edit anywhere inside
that block changes the hash of every such key.

TOML table headers (`[project.scripts]`) and intermediate JSON objects are
exactly the keys `_leaf_line`'s `key =` pattern cannot match, so they are
exactly the keys that inherit — and there are many of them in a real file.

**ADR-0025 measured the wrong risk.** Its recorded follow-up was index volume
(measured: 6% growth, judged modest). It never asked what a parent-range
fallback does to change detection. The retrieval side was measured; the change
side was not, and the change side is what the product is for.

## Decision

**A configuration key's content hash covers its own value. The line range
continues to say where to look; the hash now says what the key is.**

`_record` takes an optional `content` override. Nested keys pass one:

- **JSON and TOML** render the key's parsed value as JSON with sorted keys, so
  dictionary ordering cannot make an unchanged key look changed. A value JSON
  cannot represent falls back to `repr`, which is stable for the types
  `tomllib` returns.
- **YAML** is scanned by indentation and has no parsed values, so a key's
  "own value" is the block beneath it: the following lines indented deeper,
  stopping where the indentation returns. This gives YAML the same property
  without introducing a YAML value parser.
- **The path is part of the hashed string** in all three. Otherwise
  `{"a": 1, "b": 1}` would give `a` and `b` one identity, and a change moving a
  value between them would be invisible — trading one false-positive class for
  a false-negative one.

Top-level keys are unchanged: they cite and hash their real block, so `project`
still reports as changed when something inside it changes. That is correct —
the table did change — and it is now accompanied by the specific key rather
than by six false siblings.

`PARSER_BUNDLE_VERSION` 1.3.0 → **1.4.0**. Symbol identity moves, so every
existing snapshot is stale until re-indexed.

## Alternatives

**Suppress children of a changed parent.** Simple and wrong: it would hide a
nested key that genuinely changed, which is a false negative in the same
feature. A finding that is missing is worse than one that is redundant.

**Make `_leaf_line` match table headers**, so `[project.scripts]` resolves to
its own line. Rejected as a fix, though it may be worth doing separately: it
narrows the population of inheriting keys without removing the defect, because
any key that still fails to match keeps hashing its parent's block. Fixing the
mechanism beats shrinking its blast radius.

**Give an unlocatable leaf no symbol at all.** Rejected: it reverses ADR-0025
and returns `service.port` to being unaddressable.

## Consequences

The reproduction goes from **8 findings (7 false) to 2**: `project.version`,
and `project` for the containing table. Verified by re-running the same
throwaway repository through `repo add` → `index` → `impact --format json`.

Positive: change preflight stops reporting configuration keys that did not
change. On a file like a real `pyproject.toml` that is the difference between a
usable report and one a reader learns to skim.

Negative and accepted:

- **Every snapshot is stale until re-indexed** (`PARSER_BUNDLE_VERSION` bump).
- **YAML's subtree text includes formatting.** Re-indenting a YAML block
  without changing a value will now report that key as changed. The parsed
  formats do not have this, because they compare values. Recorded rather than
  hidden; fixing it needs a YAML parser, which Phase 2 deliberately declined.
- The hash input is no longer the text a reader sees at the citation. That is
  the point, and it is why `content` is a named parameter with the reasoning
  at the call site rather than a silent default.

**Every tracked baseline reproduces byte-for-byte, and that is a limitation
rather than a reassurance.** `check_phase4.ps1` passes unchanged, which means
the evaluation corpus cannot see this defect at all: its `docs_config` fixture
has no change case over a nested configuration key. The same blind spot
ADR-0016 and ADR-0029 recorded. **The unit tests are the only thing covering
this fix** — a green gate here proves the fix broke nothing, not that it works.

`contract_version` `1.1`, `SCHEMA_VERSION` `14`, no migration.

## Security and Privacy

None. Hash inputs stay in-process and are never logged or transmitted.
Configuration values are already read as data and never executed.

## Migration and Rollback

Re-index. `change_analysis` already refuses a stale parser version rather than
mixing derivations, so a snapshot from 1.3.0 is rejected rather than silently
compared. Rollback is reverting the `content` override and the version.

Two tests, both observed failing first. One pins that an untouched nested key
keeps its hash when a sibling changes — asserting on `project.scripts`, the
TOML table header that actually inherits, **not** on `project.scripts.run`,
which resolves to its own line and therefore passes without testing anything.
That mistake was made and caught while writing them. The other pins that two
keys holding equal values stay distinct.

## Approval

The user reported the defect and directed that it be fixed immediately.
Recorded by the implementing agent on 2026-08-11. No Section 25 item is
triggered: no contract, schema, dependency, or scope change.
