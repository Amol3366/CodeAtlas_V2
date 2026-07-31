"""Measure the Section 19.3 performance targets on the **packaged** build.

Phase 4 measured these in process, from a source checkout. Gate condition 7
asks for them on the artifact users actually run, because a frozen build loads
its native extensions and its data files differently and there is no reason to
assume the numbers carry over.

Two targets, warm, on named hardware:

- ordinary changed-file deterministic refresh p95 <= 2 s
- warm change-preflight p95 <= 10 s

**Driven over the packaged build's own HTTP API, with the server started once.**
That is the fair analogue of the Phase 4 in-process numbers, so the two are
comparable and a regression does not look like a packaging cost. The packaging
cost is real and is reported separately as ``cold_start_s`` — the time from
launching the executable to its first answered request, which a user pays once
per session and a scripted CLI user pays every invocation.

The workload is generated, not a corpus fixture, and generation is
deterministic: ``--modules`` Python modules (default 300) with cross-package
imports and calls, committed to a real Git repository. It is the *same*
generator Phase 4 used, imported rather than copied, so the two measurements
describe the same shape of work.

Usage::

    powershell -File scripts/build_package.ps1     # if not already built
    uv run python scripts/measure_phase6_perf.py [--modules 300] [--runs 20] \\
        [--json-output docs/evaluation/baseline-phase-6.json]

Exit codes: 0 both targets met, 1 a target missed, 2 no packaged artifact.
A missed target is reported as missed, with the measurement and the reason.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.measure_phase4_perf import (
        _edit_one_file,
        _git,
        _p95,
        generate_repository,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from measure_phase4_perf import (  # type: ignore[import-not-found,no-redef]
        _edit_one_file,
        _git,
        _p95,
        generate_repository,
    )

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACT = _REPOSITORY_ROOT / "dist" / "codeatlas-win64" / "codeatlas.exe"

_REFRESH_TARGET_S = 2.0
_PREFLIGHT_TARGET_S = 10.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Phase 6 refresh and preflight latency on the"
        " packaged build."
    )
    parser.add_argument("--modules", type=int, default=300)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--port", type=int, default=8593)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=_ARTIFACT,
        help="The packaged executable to measure.",
    )
    return parser


def _post(url: str, payload: dict[str, Any], *, timeout: float = 300.0) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _put(url: str, payload: dict[str, Any], *, timeout: float = 60.0) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _get(url: str, *, timeout: float = 60.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read())


def _progress(stage: str, run: int, total: int, seconds: float) -> None:
    """Say where a measurement that takes minutes has got to.

    On stderr, so piping stdout to a file still yields only the results — and
    so a run that stalls says which sample it stalled on.
    """
    print(f"  {stage} {run + 1}/{total}: {seconds:.3f}s", file=sys.stderr)


def _utc_text(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, UTC).isoformat().replace("+00:00", "Z")
    )


def _wait_until_answering(
    server: subprocess.Popen[bytes], probe: str, *, timeout: float = 120.0
) -> float:
    """Return the seconds from launch to the first answered request."""
    started = time.perf_counter()
    deadline = started + timeout
    while time.perf_counter() < deadline:
        if server.poll() is not None:
            _, stderr = server.communicate()
            raise RuntimeError(
                f"the packaged server exited with {server.returncode}:"
                f" {stderr.decode(errors='replace')}"
            )
        try:
            _get(probe, timeout=2.0)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            # Polling with no sleep would make the measurement a busy-wait
            # benchmark of this loop rather than of the server's startup.
            time.sleep(0.05)
            continue
        return time.perf_counter() - started
    raise RuntimeError("the packaged server never started answering")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact: Path = args.artifact
    if not artifact.is_file():
        print(
            f"No packaged build at {artifact}."
            " Run scripts/build_package.ps1 first — this measures the artifact,"
            " and measuring the source checkout instead would answer a"
            " different question.",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="codeatlas-perf6-") as workspace:
        results = _measure(Path(workspace), artifact, args)

    for key, value in results.items():
        print(f"{key}: {value}")
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    met = results["refresh_target_met"] and results["preflight_target_met"]
    return 0 if met else 1


def _measure(
    workspace: Path, artifact: Path, args: argparse.Namespace
) -> dict[str, Any]:
    root = workspace / "repo"
    root.mkdir()
    generate_repository(root, args.modules)
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "perf@example.invalid")
    _git(root, "config", "user.name", "CodeAtlas Perf")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "baseline")

    database = workspace / "perf.db"
    base = f"http://127.0.0.1:{args.port}"

    # Fixed argv, no shell; every value here is this script's own.
    server = subprocess.Popen(
        [
            str(artifact), "serve",
            "--port", str(args.port),
            "--db", str(database),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        cold_start_s = _wait_until_answering(server, f"{base}/v1/repositories")

        registered = _post(f"{base}/v1/repositories", {"path": str(root)})
        repository_id = registered["repository_id"]

        # Watching off, through the product's own switch. Phase 4 measured
        # these targets with no watcher, and leaving it on would time a
        # *different* workload: every edit below would also trigger a debounced
        # reindex racing the explicit one, so the number would describe
        # contention rather than refresh latency. What the watcher costs is a
        # separate question and deserves a separate measurement.
        _put(f"{base}/v1/repositories/{repository_id}/watch", {"enabled": False})

        started = time.perf_counter()
        _post(f"{base}/v1/repositories/{repository_id}/index", {})
        cold_index_s = time.perf_counter() - started

        refresh: list[float] = []
        for run in range(args.runs):
            _edit_one_file(root, args.modules, run)
            started = time.perf_counter()
            _post(f"{base}/v1/repositories/{repository_id}/index", {})
            refresh.append(time.perf_counter() - started)
            _progress("refresh", run, args.runs, refresh[-1])

        preflight: list[float] = []
        for run in range(args.runs):
            _edit_one_file(root, args.modules, args.runs + run)
            started = time.perf_counter()
            _post(
                f"{base}/v1/change-analysis/working-tree",
                {"repository_id": repository_id},
            )
            preflight.append(time.perf_counter() - started)
            _progress("preflight", run, args.runs, preflight[-1])
    finally:
        server.terminate()
        server.wait(timeout=60)

    refresh_p95 = _p95(refresh)
    preflight_p95 = _p95(preflight)
    return {
        "measured_on": "packaged build",
        "artifact": str(artifact.name),
        "artifact_size_bytes": artifact.stat().st_size,
        "artifact_built_at": _utc_text(artifact.stat().st_mtime),
        "modules": args.modules,
        "runs": args.runs,
        # The *harness* interpreter. The packaged build carries its own, which
        # is the point of measuring it, so this is not the Python under test.
        "harness_python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cold_start_s": round(cold_start_s, 3),
        "cold_index_s": round(cold_index_s, 3),
        "refresh_p50_s": round(statistics.median(refresh), 3),
        "refresh_p95_s": round(refresh_p95, 3),
        "refresh_target_s": _REFRESH_TARGET_S,
        "refresh_target_met": refresh_p95 <= _REFRESH_TARGET_S,
        "preflight_p50_s": round(statistics.median(preflight), 3),
        "preflight_p95_s": round(preflight_p95, 3),
        "preflight_target_s": _PREFLIGHT_TARGET_S,
        "preflight_target_met": preflight_p95 <= _PREFLIGHT_TARGET_S,
    }


if __name__ == "__main__":
    sys.exit(main())
