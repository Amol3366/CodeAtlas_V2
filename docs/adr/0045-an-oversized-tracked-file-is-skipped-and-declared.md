# ADR-0045: An oversized tracked file is skipped and declared, not refused

- Status: accepted
- Date: 2026-08-15
- Decision owners: user/product (ruling given 2026-08-15) and implementing agent
- Supersedes: none
- Related: ADR-0044 (preflight sees only what it would index), ADR-0043 (line
  endings are not a change), ADR-0003 (evidence granularity)

## Context

ADR-0044 ruled that **preflight never considers a file it would not index**, and
aligned the two sides of a comparison on three exclusion mechanisms: ignore
rules, content-based binary detection, and UTF-8 decodability. It recorded a
fourth, deliberately excluded from that decision:

> The oversized-file case is deliberately excluded: it does not disagree, it
> *raises*.

The asymmetry:

| Side | An oversized file |
| --- | --- |
| `DirectoryStateView` (working tree) | **skipped**, with a `TOO_LARGE` reason recorded by the scanner since Phase 1 |
| `GitBlobStateView` (blob at a ref) | **raises** `ScanLimitExceededError` |

So a single committed 3 MB CSV made a repository **impossible to preflight at
all** — the product's core workflow refused outright — while the same file was
merely skipped when read from disk. `max_file_bytes` is 2 MB.

Nothing in this repository triggers it, which is exactly why it went unnoticed.
Today's behaviour was pinned by
`test_a_tracked_file_over_the_size_limit_fails_the_whole_comparison`, whose
docstring said the asymmetry "cannot be altered silently in either direction"
and that changing it "deserves its own ruling".

There was also a second, quieter half. The scanner has recorded `TOO_LARGE`
since Phase 1, but **nothing carried it into a change report**. So on the
directory side an oversized file was already invisible — silently. The blob side
was at least loud about it.

## Decision

**Skip it, like the scanner does — and declare the omission.**

Three parts, and the third is what makes the first acceptable.

1. **`GitDiffAdapter.archive` skips an oversized entry** rather than raising,
   and returns the skipped names alongside the contents (`ArchiveResult`). The
   per-blob fallback in `GitBlobStateView.list_files` catches the same error per
   file and records it.
2. **`GitDiffAdapter.read_blob` still raises.** It is asked for *one specific
   blob*, and answering "here is nothing" for a file the caller named by hand
   would be a worse contract than refusing. The two paths now differ on purpose,
   and the reason is written at both.
3. **`StateView` gains `excluded_files()`**, and the engine turns the union
   across both sides into a `FILE_TOO_LARGE` warning and a limitation naming the
   files. Reported once across both sides, because the same oversized file is
   normally in both and two identical limitations read as two problems.

**Only oversize is reported.** An *ignored* file is deliberately not, because
ADR-0044 already ruled that such a file is outside the index and accepted as a
consequence that it can be added or deleted without preflight saying so.
Reporting them here would relitigate that ruling in warning text.

## Alternatives considered

**Keep refusing, with a better error.** The argument for it is real: a preflight
that silently ignores part of the tree is arguably worse than one that declines,
and this product's whole position is that it says what it does not know. It was
rejected because the refusal is *total* — one file makes the entire repository
un-preflightable, including every file the tool could have analysed perfectly
well. Declining to answer anything because of one CSV is not a useful form of
honesty.

**Skip it silently**, matching the scanner exactly. Rejected: that trades a loud
failure for a quiet one, which for a change-assurance tool is the worse defect.
It is also the shape of the defect ADR-0044 had just finished fixing.

## Consequences

- A repository containing an oversized tracked file can be preflighted. Changes
  *inside* that file are not detected, and the report says so by name.
- The directory side now declares its oversize skips too, which it never did.
  Some reports that were previously silent will gain a limitation; that is the
  point, not a regression.
- `archive`'s return type changed from `dict[str, bytes] | None` to
  `ArchiveResult | None`. Two callers, both updated.
- No schema, contract, or version change. `contract_version` stays `1.1`;
  `PARSER_BUNDLE_VERSION`, `RESOLVER_VERSION` and `CHUNKER_VERSION` are
  untouched, so **no snapshot is stale**.
- The pinning test is **inverted** rather than deleted, so the new behaviour is
  asserted in the same place the old one was — including that `read_blob` still
  raises, so the deliberate difference between the two paths cannot erode.

## Follow-up found after the ruling landed

Delivering the skip exposed a gap in the surface that mattered most for it.
**`render_text` — the CLI's default `impact` output — dropped warnings and
limitations entirely.** That was survivable while an excluded file produced a
loud failure elsewhere; this decision turns it into a silent skip, so the
renderer that a developer at a prompt actually reads would have shown a clean
verdict and never said a file was left out. That is precisely the defect this
ADR exists to avoid, arriving through the back door.

Fixed in the same change: `render_text` now emits a "Warnings and limitations"
section, last, after the verdict. `FILE_TOO_LARGE` was also added to the web
app's known-warning prose; an unknown code already rendered as itself, so this
is polish rather than a hole.

**The lesson is general: when an exclusion stops being loud, check every
surface that reported the loudness.** The JSON, Markdown, PR and SARIF
renderers already carried limitations; only the terminal one did not.

## Verification

Mutation-checked in both halves, restored from file copies:

| Mutation | Result |
| --- | --- |
| Engine stops appending the limitation | `test_an_oversized_file_is_declared_rather_than_silently_omitted` fails |
| `archive` raises again instead of skipping | 3 tests fail, across `test_state_views.py` and `test_git_diff.py` |

`uv run pytest -q` 2236 passed / 3 skipped; ruff clean; mypy clean on 352 files.
