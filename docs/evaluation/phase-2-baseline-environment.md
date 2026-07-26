# Phase 2 Baseline Environment

The tracked Phase 2 baseline is generated with timings excluded, so the artifact
is byte-for-byte reproducible on any machine. Correctness metrics do not depend
on hardware; performance claims do, and are reported separately with the
hardware named, per `CLAUDE.md` Section 19.3.

## Environment of record

| Field | Value |
| --- | --- |
| Platform | Windows 11 (`Windows-11-10.0.26200-SP0`) |
| Python | 3.12.12 |
| Dependency state | `uv sync --all-groups --frozen` against the committed `uv.lock` |
| Dataset | `tests/evaluation/cases` — 6 fixtures, 40 query cases, 24 change cases |

## Reproducing it

```powershell
uv run python scripts/run_phase2_baseline.py `
    --dataset tests/evaluation/cases `
    --json-output docs/evaluation/baseline-phase-2.json `
    --markdown-output docs/evaluation/baseline-phase-2.md
```

Add `--check` to compare against the tracked artifacts instead of overwriting
them. `--check` exits 5 when they differ.

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `baseline-phase-2.json` | `C32444D3B72B8884FED54D88C16C9BCE1A916999E56649E6CCA1130CCCD33A97` |
| `baseline-phase-2.md` | `6301786284FF5C4C5EAA4A9489B095735F8B59CED266804ECD9770AD46748650` |

## The Phase 2 baseline became historical in Phase 3

As of P3-SETUP (2026-07-26) the Phase 2 artifacts above are a historical record,
exactly as the Phase 1 artifacts became one at the start of Phase 2. Two
independent changes make them irreproducible against the current engine:

1. **ADR-0003** added `exact_evidence_rate` and `containing_evidence_rate` to
   `AggregateMetrics`, changing the baseline artifact **schema**.
2. **ADR-0004** moved `PARSER_BUNDLE_VERSION` to `1.1.0`, which changes every
   `snapshot_id` and therefore every evidence `snapshot_id` in the report.

`scripts/run_phase2_baseline.py --check` consequently exits 5, and
`scripts/check_phase2.ps1` is marked superseded. **The Phase 2 artifacts and
their hashes above are deliberately not regenerated** — they record what the
Phase 2 gate measured, and rewriting them would erase that record.

`docs/evaluation/baseline-phase-0.json` and `.md` *were* regenerated in
P3-SETUP, because a null baseline records "the engine does nothing" and that
statement is unchanged. The regeneration added two `null` fields and altered no
recorded value.

## The Phase 1 baseline is historical

`docs/evaluation/baseline-phase-1.*` records what the **Phase 1** engine did.
Re-running `scripts/run_phase1_baseline.py --check` against the current engine
exits 5, and should: the engine now answers intents it previously abstained
from. The Phase 1 artifacts are kept unchanged as the record of that gate, and
`scripts/check_phase2.ps1` deliberately does not re-check them.
