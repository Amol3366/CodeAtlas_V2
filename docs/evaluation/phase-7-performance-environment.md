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

## Re-measured 2026-08-21 — refresh p95 now MISSES its target

The table above is the **2026-07-30 gate record and is deliberately unedited.**
This section records the re-measurement P2-D asked for, because `-Perf` had not
run since 2026-08-10 while the artifact was rebuilt twice across two
`PARSER_BUNDLE_VERSION` bumps (1.4.0 -> 1.5.0 -> 1.6.0). The tracked artifact
`baseline-phase-7-perf.json` now holds the run below.

Same method: packaged semantic-local artifact, its own `/v1` API, 300 generated
modules, watcher off, 20 samples per target, `provider: local`, coverage 1.0.

| Metric | 2026-08-10 | 2026-08-21 | Target | Met |
| --- | ---: | ---: | ---: | --- |
| Changed-file refresh p95 | 0.799 s | **2.407 s** | <= 2 s | **NO** |
| Changed-file refresh p50 | 0.689 s | 2.298 s | — | — |
| Warm preflight p95 | 2.243 s | 4.376 s | <= 10 s | yes |
| Cold start to first answer | 1.060 s | 2.327 s | reported | n/a |
| Cold index, 300 modules | 21.295 s | 18.877 s | reported | n/a |
| Semantic coverage | 1.0000 | 1.0000 | complete | yes |
| onedir package tree | 1,052,540,446 B | 1,058,201,846 B | reported | n/a |

**Read the fourth and fifth rows before concluding anything about the machine.**
The first attempt at this measurement looked like environment contamination:
everything was 1.3x-3.3x slower and `model_test.latency_ms` — which loads a
sentence-transformers model and embeds a probe, a path containing no CodeAtlas
code that has changed — had gone 42,474 ms -> 76,089 ms. That reading was
recorded and then **disproved by re-running.**

In the promoted run, `model_test.latency_ms` is **21,403 ms**, half the
2026-08-10 figure, and the cold index is **faster** than the 2026-08-10 baseline
(18.877 s against 21.295 s). **The machine was demonstrably quicker than
baseline on unchanged paths while refresh was still three times slower.** That is
what makes this a regression rather than a slow afternoon, and it is why two runs
were taken rather than one.

| Run | refresh p95 | model_test | cold index |
| --- | ---: | ---: | ---: |
| 1 | 2.433 s | 76,089 ms | 27.211 s |
| 2 (promoted) | 2.407 s | 21,403 ms | 18.877 s |

Refresh reproduces within 26 ms across a 3.6x swing in the machine-speed
indicator. The regression is not load.

**The cause is not attributed, and one plausible story was measured and
rejected.** Refresh is +1.6 s and preflight +2.1 s, which looks like a fixed
per-operation cost rather than proportional work; the obvious suspect was
ADR-0065's four extra grammars, since `build_registry()` constructs every parser
eagerly. Timed directly: `default_registry()` costs **0.09-0.16 s**, an order of
magnitude short of explaining it. Recorded so the next investigation does not
spend itself there again (the ADR-0064 lesson).

Candidates still open: the resolver's declared-module index
(`RESOLVER_VERSION` 1.4.0 -> 1.5.0), ADR-0067's additional Scala references, or
something unrelated to ADR-0065 that landed in the same window. **Bisect the two
parser bumps or time the stages inside the refresh path; do not guess.**

### Narrowed the same day: it is the packaged artifact

Four measurements, **all taken on 2026-08-21** so no cross-date comparison is
load-bearing:

| | deterministic | semantic |
| --- | ---: | ---: |
| **source** | **1.668 s** (target met) | not measurable by these harnesses |
| **packaged** | **2.266 s** (target MISSED) | **2.407 s** (target MISSED) |

Reading across the packaged row: **embeddings cost +0.14 s.** Reading down the
deterministic column: **packaging costs +0.60 s.** Against the historical
figures, packaged deterministic regressed **1.295 -> 2.266 s (+75%)** while
source deterministic moved **1.426 -> 1.668 s (+17%)** and still passes.

**In July the packaged build was faster than source** (1.295 s against 1.426 s,
a difference the Phase 6 document explains as the snapshot-retention fix).
**Today it is 0.6 s slower.** That inversion is the finding.

`cold_start_s` agrees independently: **1.627 s -> 2.393 s**, +0.77 s of setup.

**Two candidates this document named earlier are now refuted.** The resolver's
declared-module index and ADR-0067's additional Scala references are both in the
source path, and the source path measures clean. They are not the cause.

**Leading hypothesis, explicitly unproven.** ADR-0065 added four grammars, and
`docs/operations/packaging-and-install.md` records that the engine reads each
grammar's `tags.scm` **off disk with `os.walk`** — data PyInstaller cannot find
by analysis, which is why it is carried explicitly. Services are built per
request. An `os.walk` over a frozen onedir tree, per parser construction, per
request, would be packaged-only, fixed-cost, and dated to exactly the right
change. Every number above is consistent with it. **None of them tests it.**

**A confirmation attempt that failed, recorded as such.** Timing `codeatlas
doctor` gave packaged **1.624 s** against source **1.769 s** — packaged faster.
That does not refute the hypothesis, because the source side carries `uv run`
environment-resolution overhead and, more importantly, **neither side isolates
per-request service construction**, which is what the HTTP-driven harnesses
exercise. It measured one-shot process startup instead. The next investigation
should time construction inside the **running** packaged server.

### Corrected: the attribution was reached badly, then measured properly

**The 2x2 above mixed two instruments, and that is a method error worth keeping
rather than deleting.** Its source cell came from `measure_phase4_perf.py`, which
calls `build_services` **in-process**; both packaged cells came from
`measure_phase6_perf.py`, which drives the server over **HTTP**. Subtracting one
from the other conflates packaging with transport, so "+0.60 s of packaging" did
not follow from those numbers even though it landed close to the truth.

**Two hypotheses were then killed by measurement, in order.**

1. **Per-request service construction.** `GET /v1/repositories` against an empty
   database, 25 warm requests each: **packaged 184.9 ms, source 186.3 ms**
   (median), a difference of **-1.5 ms**. `build_registry()`, the `os.walk` for
   each grammar's `tags.scm`, and per-request `build_services` are all cleared.
2. **The earlier candidates**, already recorded above: the semantic layer, the
   resolver's declared-module index, ADR-0067's Scala references. All live in the
   source path, and the source path passes.

**Re-measured on one instrument.** `measure_phase6_perf.py` accepts `--artifact`,
so the source build was driven over HTTP through the *same* harness using the
venv console script `.venv/Scripts/codeatlas.exe`:

| Both over HTTP, same harness, same day | refresh p95 | target |
| --- | ---: | --- |
| source (`.venv/Scripts/codeatlas.exe`) | **1.525 s** | **met** |
| packaged (`dist/codeatlas-win64/codeatlas.exe`) | **2.266 s** | **MISSED** |
| **packaging cost** | **+0.741 s** | — |

**The corrected figure is larger than the unsound one**, so the error was
understatement, not exaggeration. It was bounded because the two harnesses
measure the **same operation** — edit one file, then re-index
(`services.indexing.index` against `POST /v1/repositories/{id}/index`) — and
differ only by the transport whose cost is the ~185 ms measured above.

**What this establishes.** Source over HTTP **meets** the ≤ 2 s target with
margin; the packaged build does not. **Packaging alone causes the miss.** And
because a request that parses nothing shows no packaged penalty at all, the cost
sits in the **index path** and scales with files indexed rather than with
requests served.

**What it does not establish.** Why. Per-file parse cost inside the frozen build
is the shape that fits — it would scale with files and vanish on a request that
parses nothing — but nothing here measures it. That is the next step, and the
Deferred Register names it.

**What this does not say.** Preflight still clears its target with margin, the
deterministic corpus metrics are untouched (all three `--check` baselines
reproduce byte-for-byte), and no evidence, snapshot, or contract behaviour is
implicated. This is a latency regression on one measured path.

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
