# Phase 0 Baseline Environment and Method

Recorded: 2026-07-25T16:16:02Z  
Contract version: 1.0  
Implementation status: `not_implemented`

## Environment

- Operating system: Windows 11, build 10.0.26200, 64-bit
- Logical processors visible to the process: 24
- Python: CPython 3.12.12 selected by `uv`
- uv: 0.11.24
- Dependency input: frozen `uv.lock`, 17 packages checked
- Repository Git state: unavailable because this workspace is not a Git
  repository

Memory and processor model were not recorded because the current execution
boundary denied CIM access. No performance claim depends on those unavailable
values.

## Method

From the repository root:

```powershell
$timer = [System.Diagnostics.Stopwatch]::StartNew()
powershell -ExecutionPolicy Bypass -File scripts/check_phase0.ps1
$timer.Stop()
$timer.ElapsedMilliseconds
```

The command performed a frozen dependency check, verified the tracked contract
schema, ran the complete test suite, Ruff, strict MyPy, dataset validation, and
null-baseline generation. The observed wall-clock time was 6,485 ms. This is a
development-gate measurement, not a product latency benchmark.

## Result

- Tests: 50 passed in 0.90 seconds on the final handoff-state run
- Ruff: all checks passed
- MyPy: no issues in 14 source files
- Dataset: 6 fixtures, 40 query cases, 24 change cases
- Contract schema: current
- Null baseline: generated successfully
- Tracked baseline: byte-for-byte verification succeeded without rewriting
- Product targets: intentionally unmet because the engine is not implemented

All implemented product metrics are recorded as `0.0`; metrics requiring
predicted evidence, claims, or answers are `null` (not applicable). No metric is
inferred from an LLM or an oracle answer.

Artifact SHA-256 values:

- `baseline-phase-0.json`:
  `E425A4F116AAA07036B11E0D4017BE3F7C11B4F0FA3D9148922FF65C5FA2002F`
- `baseline-phase-0.md`:
  `F6D09C468AA04A44FE40B999CD2CE67ABF06C0E7E2C1422823F9DC06685C9A0C`

## Accepted Phase 0 Non-Goals

Phase 0 does not implement repository scanning, Git analysis, parsing, storage,
retrieval, REST, MCP, web UI, embeddings, reranking, LLM generation, cloud
providers, or product performance targets. It establishes trustworthy
contracts, evaluation truth, security boundaries, and repeatable gates for
those later vertical slices.
