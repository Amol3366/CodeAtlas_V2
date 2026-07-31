# Phase 7 performance and packaging environment

Status: recorded 2026-07-30 against the semantic-local packaged onedir artifact.
Baseline artifact path: `docs/evaluation/baseline-phase-7-perf.json`.
Regenerate:

```powershell
uv sync --all-groups --extra semantic-local --frozen
powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1 -SemanticLocal -SkipZip
uv run python scripts/measure_phase7_perf.py --json-output docs/evaluation/baseline-phase-7-perf.json
```

## What must be measured

Gate condition 12 is not the Phase 6 deterministic package measurement repeated.
It asks whether the Section 19.3 targets still hold **with embeddings enabled**
and asks for artifact size and cold start with the torch/sentence-transformers
dependency tree present.

The script therefore:

- starts the packaged `codeatlas.exe` once and drives its `/v1` API;
- registers a generated 300-module Git repository;
- disables the watcher through the product API, matching the Phase 6 method;
- sets the measured repository to provider `local` through `/v1/settings`;
- requires `/v1/models/test` to succeed before indexing;
- records semantic coverage after the cold index;
- measures warm changed-file refresh p95 and warm change-preflight p95;
- records executable size, zip size when present, cold start, and cold index.

## Results

20 samples per target on Windows 11 AMD64, using the same 300-module generated
repository shape as Phase 6.

| Metric | Phase 7 semantic-local package | Target | Met |
| --- | ---: | ---: | --- |
| Changed-file refresh p95 with embeddings enabled | **0.975 s** | <= 2 s | yes |
| Warm change-preflight p95 with embeddings enabled | **2.298 s** | <= 10 s | yes |
| Semantic coverage after cold index | **1.0000** | complete | yes |
| Cold start to first answer | 1.064 s | reported | n/a |
| Cold index, 300 modules + 1,200 embeddings | 12.481 s | reported | n/a |
| Executable size | 81,658,585 bytes | reported | n/a |
| onedir package tree size | 1,052,390,437 bytes | reported | n/a |
| Zip/archive size | not produced (`-SkipZip`) | reported | n/a |

The first tiny semantic-package run missed refresh p95 because it rebuilt the
local sentence-transformers provider on every index. P7-12 fixed that by caching
the local provider process-wide; the recorded full run above includes that fix.

## Blocked is a gate result

`measure_phase7_perf.py` exits 2 and writes `measurement_status: "blocked"` when
the artifact is missing, the package does not expose the Phase 7 settings API,
or the local provider cannot run. That result is intentionally not coerced into
the Phase 6 deterministic number. If the semantic-local package cannot be
measured, the Phase 7 packaging/performance gate is unsatisfied in that
environment and the reason must be carried into the handoff.

## Packaging note

The semantic onedir package is the measured artifact. `Compress-Archive` over
the 1.05 GB semantic-local tree exceeded the automation timeout in this
workspace, so `check_phase7.ps1 -Semantic -Package` passes `-SkipZip` and the
perf artifact records `archive_size_bytes: null`. A distributable archive can be
produced as a slower packaging step, but it is not what the perf harness starts.
