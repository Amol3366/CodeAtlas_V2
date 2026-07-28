# Phase 6 Performance Environment, and One Open Defect

Status: recorded 2026-07-28
Baseline artifact: `baseline-phase-6.json`
Regenerate: `powershell -File scripts/build_package.ps1` then
`uv run python scripts/measure_phase6_perf.py --runs 10 --json-output docs/evaluation/baseline-phase-6.json`

Gate condition 7 asks for the Section 19.3 performance targets **on the
packaged build**. Phase 4 measured them in process from a source checkout; a
frozen build loads its native extensions and data files differently, and there
is no reason to assume the numbers carry over.

## Hardware and method

| | |
| --- | --- |
| Machine | Windows 11 (10.0.26200), AMD64 |
| Artifact | `dist/codeatlas-win64/codeatlas.exe`, PyInstaller onedir |
| Workload | 300 generated Python modules with cross-package imports and calls, in a real Git repository — the *same* generator Phase 4 used, imported rather than copied |
| Driver | the packaged build's own `/v1` API, server started **once** |
| State | warm; 10 samples per target after a cold index |
| Watching | off for the measured repository, through the product's own switch |

The server is started once and driven over HTTP because that is the fair
analogue of the Phase 4 in-process numbers — comparable, so a regression cannot
be mistaken for a packaging cost. The packaging cost is real and reported
separately as `cold_start_s`: the time from launching the executable to its
first answered request. A CLI user pays it per invocation; a `serve` user pays
it once.

Watching is disabled for the measured repository because Phase 4 measured with
no watcher. Leaving it on would time a different workload — every edit would
also trigger a debounced reindex racing the explicit one, so the number would
describe contention rather than refresh latency.

## Results

| Metric | Packaged (Phase 6) | Source, in-process (Phase 4) | Target | Met |
| --- | ---: | ---: | ---: | --- |
| Changed-file deterministic refresh p95 | **1.311 s** | 1.426 s | ≤ 2 s | yes |
| Warm change-preflight p95 | **3.217 s** | 5.151 s | ≤ 10 s | yes |
| Cold start to first answer | 1.104 s | n/a | — | reported |
| Cold index, 300 modules | 6.703 s | n/a | — | reported |

**The packaged build is faster than the Phase 4 source measurement**, which is
not a packaging effect. It is the retention fix below: Phase 4's numbers were
taken against a database that had already accumulated every snapshot it ever
built.

## What this measurement found

### 1. Snapshots accumulated forever — fixed

`SnapshotRecoveryService.prune` had existed since Phase 2 and documented the
policy — keep the active snapshot and the newest superseded one — but **nothing
ever called it**. Every index left its predecessor behind permanently, with all
of that snapshot's files, symbols, relations, chunks, and FTS rows.

Before Phase 6 this burned slowly, because you reindexed when you chose to. The
watcher changed the arithmetic: a repository being edited all day is reindexed
all day. Measured over 20 reindexes plus 20 preflights, refresh drifted from
1.6 s to 2.3 s — through the 2 s target — and preflight went from 4.6 s to
10.6 s, a **step change** that never came back down.

Retention now runs where snapshots are made, so the bound holds for the CLI, the
API, the watcher, and the reconciling scan alike. With it, both numbers are flat
across the run rather than degrading. Regression tests:
`tests/integration/test_snapshot_retention.py`.

### 2. The API process can crash under sustained change analysis — open

**This is an unfixed defect and it is reported as one.**

Driving `POST /v1/change-analysis/working-tree` repeatedly against the 300-module
repository, the server process dies with a **Windows fatal exception: access
violation**. The client sees a connection reset or a hung request; the process
is gone.

The captured faulthandler stack puts the fault inside a Windows syscall:

```text
Windows fatal exception: access violation

  File "<frozen ntpath>", line 739 in realpath        # nt._getfinalpathname
  File "codeatlas/domain/paths.py", line 68 in is_inside_root
  File "codeatlas/domain/paths.py", line 103 in resolve_inside_root
  File "codeatlas/analysis/states.py", line 108 in _read
  File "codeatlas/analysis/engine.py", line 290 in _classify_bodies
  File "codeatlas/analysis/engine.py", line 136 in analyze
  File "codeatlas/application/change_analysis.py", line 119 in analyze_working_tree
  File "codeatlas/api/routers/change_analysis.py", line 47 in analyze_working_tree
  File "anyio/_backends/_asyncio.py", line 1033 in run                # worker thread
```

What is established:

- **It is a crash, not a hang.** Handles, threads, and memory are flat right up
  to the moment it dies — 260 handles, 10 threads, ~110 MB, unchanged.
- **It is not packaging.** It reproduces identically on a source-run `uvicorn`
  server, so it is not a frozen-build artifact.
- **It is not the snapshot accumulation.** It survives the retention fix.
- **It is not a fixed request count.** Observed at the 6th, 17th, and 44th
  analysis in different runs — it is probabilistic under load.
- **It is specific to change analysis.** Twenty consecutive reindexes through
  the same server never triggered it, in any run.
- **It is not plain `realpath` under concurrent writes.** A stdlib-only probe
  doing 30,000 threaded resolutions over a tree being rewritten does not crash.

What is not established: the cause. A fault inside `nt._getfinalpathname` is
where corrupted state finally faults, which is not necessarily where it was
caused. Naming the cause needs a native debugger, and guessing at a fix for a
memory fault would be worse than reporting it accurately.

**Impact.** Change preflight is the product's primary workflow, and the crash is
in its server path. A single preflight, or a handful, is unaffected — the
measured runs above complete cleanly, and the CLI path (a process per
invocation) has never reproduced it. Sustained repeated preflight against one
long-running server is what triggers it.

The baseline above uses 10 samples per target, which completes reliably. Twenty
samples reproduces the crash often enough that the measurement cannot be relied
on to finish, and **that constraint is part of this record rather than a
footnote to it**.
