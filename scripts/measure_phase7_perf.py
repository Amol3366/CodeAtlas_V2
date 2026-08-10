"""Measure Phase 7 performance on the packaged build with embeddings enabled.

Phase 6 proved the packaged deterministic artifact. Phase 7 has a stricter
question: do the same Section 19.3 refresh and preflight targets still hold
when the repository is opted into local embeddings, and what does that do to
artifact size and cold start?

The harness drives the package through its public HTTP API. It registers a
generated Git repository, switches that repository to the local provider through
`/v1/settings`, checks `/v1/models/test`, indexes, then measures warm refresh
and change-preflight latency. If the artifact or the local provider is missing,
the script writes an explicit blocked payload and exits 2 rather than reporting
a deterministic-only number as a semantic measurement.

Usage::

    powershell -File scripts/build_package.ps1 -SemanticLocal
    uv run python scripts/measure_phase7_perf.py \\
        --json-output docs/evaluation/baseline-phase-7-perf.json

Exit codes: 0 targets met, 1 targets missed, 2 prerequisite missing.
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
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    from scripts.measure_phase4_perf import (
        _edit_one_file,
        _git,
        _p95,
        generate_repository,
    )
    from scripts.measure_phase6_perf import (
        _ARTIFACT,
        _PREFLIGHT_TARGET_S,
        _REFRESH_TARGET_S,
        _get,
        _post,
        _progress,
        _put,
        _utc_text,
        _wait_until_answering,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from measure_phase4_perf import (  # type: ignore[import-not-found,no-redef]
        _edit_one_file,
        _git,
        _p95,
        generate_repository,
    )
    from measure_phase6_perf import (  # type: ignore[import-not-found,no-redef]
        _ARTIFACT,
        _PREFLIGHT_TARGET_S,
        _REFRESH_TARGET_S,
        _get,
        _post,
        _progress,
        _put,
        _utc_text,
        _wait_until_answering,
    )


class MeasurementPreconditionError(Exception):
    """The requested semantic measurement cannot be run in this environment."""

    def __init__(self, message: str, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.payload = payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Phase 7 packaged performance with local embeddings."
    )
    parser.add_argument("--modules", type=int, default=300)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--port", type=int, default=8597)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=_ARTIFACT,
        help="The packaged executable to measure.",
    )
    parser.add_argument(
        "--provider",
        choices=("local", "none"),
        default="local",
        help=(
            "`local` is the Phase 7 gate measurement. `none` is a diagnostic"
            " deterministic-only comparison."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact: Path = args.artifact
    if not artifact.is_file():
        payload = _blocked_payload(
            artifact,
            args,
            reason="packaged_artifact_missing",
            detail=(
                "Run scripts/build_package.ps1 -SemanticLocal before measuring"
                " Phase 7 performance."
            ),
        )
        _maybe_write(args.json_output, payload)
        print(payload["detail"], file=sys.stderr)
        return 2

    try:
        with tempfile.TemporaryDirectory(prefix="codeatlas-perf7-") as workspace:
            results = _measure(Path(workspace), artifact, args)
    except MeasurementPreconditionError as error:
        _maybe_write(args.json_output, error.payload)
        print(str(error), file=sys.stderr)
        return 2

    for key, value in results.items():
        print(f"{key}: {value}")
    _maybe_write(args.json_output, results)
    met = (
        results["refresh_target_met"]
        and results["preflight_target_met"]
        and results["semantic_coverage_target_met"]
    )
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

    server = subprocess.Popen(
        [
            str(artifact),
            "serve",
            "--port",
            str(args.port),
            "--db",
            str(database),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        cold_start_s = _wait_until_answering(server, f"{base}/v1/repositories")

        registered = _post(f"{base}/v1/repositories", {"path": str(root)})
        repository_id = registered["repository_id"]
        _put(f"{base}/v1/repositories/{repository_id}/watch", {"enabled": False})

        settings = _configure_provider(
            base, repository_id, args.provider, artifact, args
        )

        started = time.perf_counter()
        _post(f"{base}/v1/repositories/{repository_id}/index", {})
        cold_index_s = time.perf_counter() - started
        semantic_status = _get(
            f"{base}/v1/repositories/{repository_id}/semantic-status"
        )

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
    semantic_target = (
        args.provider == "none"
        or (
            semantic_status.get("enabled") is True
            and semantic_status.get("is_complete") is True
        )
    )
    return {
        "measurement_status": (
            "measured_with_local_embeddings"
            if args.provider == "local"
            else "deterministic_only"
        ),
        "measured_on": "packaged build",
        "artifact": str(artifact.name),
        "artifact_size_bytes": artifact.stat().st_size,
        "package_tree_size_bytes": _directory_size(artifact.parent),
        "archive_size_bytes": _archive_size(artifact),
        "artifact_built_at": _utc_text(artifact.stat().st_mtime),
        "modules": args.modules,
        "runs": args.runs,
        "harness_python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "embedding_provider": args.provider,
        "settings": settings,
        "semantic_status_after_cold_index": semantic_status,
        "semantic_coverage_target_met": semantic_target,
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


def _configure_provider(
    base: str,
    repository_id: str,
    provider: str,
    artifact: Path,
    args: argparse.Namespace,
) -> Any:
    query = urllib.parse.urlencode({"repository_id": repository_id})
    try:
        settings = _patch(
            f"{base}/v1/settings?{query}", {"embedding_provider": provider}
        )
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as error:
        payload = _blocked_payload(
            artifact,
            args,
            reason="phase7_settings_api_unavailable",
            detail=type(error).__name__,
        )
        raise MeasurementPreconditionError(
            "The packaged build does not expose the Phase 7 settings API. "
            "Rebuild with scripts/build_package.ps1 -SemanticLocal.",
            payload,
        ) from error
    if provider != "local":
        return settings

    try:
        tested = _post(f"{base}/v1/models/test?{query}", {})
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as error:
        payload = _blocked_payload(
            artifact,
            args,
            reason="phase7_model_test_unavailable",
            detail=type(error).__name__,
        )
        payload["settings"] = settings
        raise MeasurementPreconditionError(
            "The packaged build could not run the Phase 7 model test.",
            payload,
        ) from error
    if tested.get("ok") is True:
        return {**settings, "model_test": tested}

    detail = str(tested.get("detail_code") or "PROVIDER_TEST_FAILED")
    payload = _blocked_payload(
        artifact,
        args,
        reason="local_provider_unavailable",
        detail=detail,
    )
    payload["settings"] = settings
    payload["model_test"] = tested
    raise MeasurementPreconditionError(
        "The local embedding provider is not available in the packaged build: "
        f"{detail}.",
        payload,
    )


def _patch(url: str, payload: dict[str, Any], *, timeout: float = 60.0) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _blocked_payload(
    artifact: Path, args: argparse.Namespace, *, reason: str, detail: str
) -> dict[str, Any]:
    return {
        "measurement_status": "blocked",
        "reason": reason,
        "detail": detail,
        "artifact": str(artifact),
        "artifact_exists": artifact.is_file(),
        "artifact_size_bytes": artifact.stat().st_size if artifact.is_file() else None,
        "package_tree_size_bytes": (
            _directory_size(artifact.parent) if artifact.parent.is_dir() else None
        ),
        "archive_size_bytes": _archive_size(artifact),
        "modules": args.modules,
        "runs": args.runs,
        "embedding_provider": args.provider,
        "harness_python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def _archive_size(artifact: Path) -> int | None:
    archive = artifact.parent.with_suffix(".zip")
    return archive.stat().st_size if archive.is_file() else None


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _maybe_write(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""` writes the "\n" through untranslated. Without it Python
    # emits CRLF on Windows, and this artifact is *tracked* and gated by a
    # byte comparison -- so the working tree would disagree with the committed
    # object that `.gitattributes` normalised, and `--check` would fail on a
    # fresh clone while passing here. That is ADR-0022 exactly, which cost a
    # session to diagnose the first time.
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )


if __name__ == "__main__":
    sys.exit(main())
