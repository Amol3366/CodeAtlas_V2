# Phase 6 Performance Environment

Status: recorded 2026-07-28; **corrected and completed 2026-07-29** when the
defect below was diagnosed properly and fixed
Baseline artifact: `baseline-phase-6.json`
Regenerate: `powershell -File scripts/build_package.ps1` then
`uv run python scripts/measure_phase6_perf.py --json-output docs/evaluation/baseline-phase-6.json`

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

20 samples per target, which is the sample count Phase 4 used.

| Metric | Packaged (Phase 6) | Source, in-process (Phase 4) | Target | Met |
| --- | ---: | ---: | ---: | --- |
| Changed-file deterministic refresh p95 | **1.295 s** | 1.426 s | ≤ 2 s | yes |
| Warm change-preflight p95 | **3.103 s** | 5.151 s | ≤ 10 s | yes |
| Cold start to first answer | 1.627 s | n/a | — | reported |
| Cold index, 300 modules | 2.287 s | n/a | — | reported |

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

### 2. The server stopped answering under sustained change analysis — fixed

Driving `POST /v1/change-analysis/working-tree` repeatedly, the server stopped
answering **every** request — not the one in flight, all of them — while the
process stayed alive with memory, threads, and handles flat and nothing in its
log to say why.

**The cause was uvicorn's access log.** It writes one line per request,
synchronously, on the event-loop thread. A server launched by a shortcut, a
wrapper script, or a test harness is usually given a pipe for stdout that nobody
reads. A pipe holds a few kilobytes; the write that fills it blocks forever, and
because that write happens on the event loop, the whole server stops.

`py-spy dump` against the live process named it in one line:

```text
Thread (idle): "MainThread"
    flush (logging/__init__.py:1144)
    emit  (logging/__init__.py:1164)
        msg: 'INFO:  127.0.0.1:54602 - "POST /v1/change-analysis/working-tree HTTP/1.1" 200 OK'
    ...
    send  (uvicorn/protocols/http/h11_impl.py:482)
```

The analysis had already **succeeded**. The server was blocked announcing it.

Confirmed by removing the one variable: with a thread draining the server's
stdout, 60 consecutive analyses pass; without it, the hang lands at the same
request every time. The fix is `access_log=False` in `serve`, which also matches
`CLAUDE.md` Section 17 — this product writes no logs by default, and an access
log records a request path per request. Regression test:
`tests/integration/test_serve_output_backpressure.py`, which drives 400 requests
at a server whose output nobody reads.

#### The wrong diagnosis, and why it was wrong

This was first recorded here as an unfixed **"Windows fatal exception: access
violation"** in `nt._getfinalpathname`, with a captured stack and six ruled-out
hypotheses. That diagnosis was wrong, and the way it went wrong is worth keeping.

The stack came from a run instrumented with
`faulthandler.dump_traceback_later(repeat=True)`, which walks frame objects from
a separate thread while the interpreter is running. **The instrumentation
faulted, not the product.** Every other observation — the hangs — was real, but
the one run that produced a stack produced a misleading one, and it was the only
run that appeared to explain the others.

Two claims made at the time were also wrong, both traceable to the same run:

- *"It is a crash, not a hang."* It was always a hang. The process stayed alive;
  a later run confirmed `server alive=True` at the moment of failure.
- *"It is not packaging — a source-run uvicorn reproduces it."* The source
  server in that comparison ran with `log_level="warning"`, which suppresses
  access logs, so it could not have reproduced it. It never did.

What was true, and what pointed at the answer once the crash theory was dropped:
the failure moved with **how much had been logged** rather than how many
requests had been made — the 44th analysis alone, the 17th after 20 reindexes —
which is the fingerprint of a fixed-size buffer, not a leak or a race.
