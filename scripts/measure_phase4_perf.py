"""Measure the two Phase 4 performance gates on a synthetic repository.

Section 19.3 declares two targets, and this script produces the numbers for
both, warm, on named hardware:

- ordinary changed-file deterministic refresh p95 <= 2 s
  (one file edited, ``IndexRepositoryService.index`` re-run);
- warm change-preflight p95 <= 10 s
  (``ChangeAnalysisService.analyze_working_tree``: freshness check, refresh,
  Git base blobs, engine, persistence, report).

The repository profile is generated, not a corpus fixture: ``--modules``
Python modules (default 300) with cross-package imports and calls, committed
to a real Git repository. Generation is deterministic, so two runs on the
same machine measure the same workload. Results are printed and optionally
written as JSON; the committed record of a measurement lives in
``docs/evaluation/phase-4-baseline-environment.md`` together with the
hardware it was taken on, per Section 19.3's naming rule.

Usage::

    uv run python scripts/measure_phase4_perf.py [--modules 300] [--runs 20] \\
        [--json-output perf.json]
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
from collections.abc import Sequence
from pathlib import Path

from codeatlas.application.change_analysis import ChangeAnalysisRequest
from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.evaluation.quiescence import (
    CALIBRATION_TOLERANCE,
    calibrate,
    unsettled_reason,
)
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Phase 4 refresh and preflight latency."
    )
    parser.add_argument("--modules", type=int, default=300)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--allow-busy", action="store_true")
    parser.add_argument(
        "--profile",
        choices=("synthetic", "realistic"),
        default="synthetic",
        help=(
            "Corpus shape. `synthetic` is the tracked Phase 4 baseline. "
            "`realistic` emits Markdown that mentions the symbols the "
            "modules define, so the reference class ADR-0064 found to "
            "dominate real cost is present at all."
        ),
    )
    return parser


def generate_repository(
    root: Path, modules: int, profile: str = "synthetic"
) -> None:
    """A deterministic Python tree with cross-package imports and calls.

    ``profile`` selects what the tree is made of.

    ``synthetic`` is the original and is **kept byte-identical**, because the
    tracked Phase 4 baseline was taken on it and must stay reproducible.

    ``realistic`` exists because ADR-0064 showed the synthetic one cannot
    measure what dominates a real repository. ``DOCUMENTS`` is 117,471 of
    160,687 references there and ``<mention>`` alone is 112,265 of them, while
    this generator emits no Markdown at all -- so the quadratic term ADR-0062
    fitted a 1.14 exponent against was not merely under-represented, it was
    absent. The realistic profile emits documents that mention the symbols the
    modules define, and modules with enough body to have a realistic size.
    """
    if profile not in ("synthetic", "realistic"):
        raise ValueError(f"unknown profile {profile!r}")
    if profile == "realistic":
        _generate_realistic(root, modules)
        return
    packages = ("core", "services", "adapters")
    for name in packages:
        package_dir = root / "src" / name
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")

    for index in range(modules):
        package = packages[index % len(packages)]
        lines = ["from __future__ import annotations", ""]
        # Each module leans on two earlier modules, which is what gives the
        # resolver and the graph real cross-file work to do.
        for offset in (1, 2):
            other = index - offset
            if other >= 0:
                other_package = packages[other % len(packages)]
                lines.append(
                    f"from src.{other_package}.mod_{other:03d} import "
                    f"handle_{other:03d}"
                )
        lines += [
            "",
            f"def handle_{index:03d}(value: str) -> str:",
            f'    marker = "m{index:03d}"',
        ]
        for offset in (1, 2):
            other = index - offset
            if other >= 0:
                lines.append(f"    value = handle_{other:03d}(value)")
        lines += [
            "    return f\"{marker}:{value}\"",
            "",
            f"def check_{index:03d}(value: str) -> str:",
            "    if not value:",
            '        raise ValueError("value is required")',
            f"    return handle_{index:03d}(value)",
            "",
        ]
        target = root / "src" / package / f"mod_{index:03d}.py"
        target.write_text("\n".join(lines), encoding="utf-8")


_HELPERS_PER_MODULE = 8
_MODULES_PER_DOCUMENT = 2


def _generate_realistic(root: Path, modules: int) -> None:
    """Larger modules, plus Markdown that mentions the symbols they define.

    The document-to-code ratio is deliberately generous rather than tuned to a
    real repository: the point is that the dominant reference class is *present*
    and scales with the corpus, not that its share matches any one codebase.
    Claiming a calibrated ratio would repeat ADR-0062's error in the other
    direction.
    """
    packages = ("core", "services", "adapters")
    for name in packages:
        package_dir = root / "src" / name
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (root / "docs").mkdir(parents=True)

    for index in range(modules):
        package = packages[index % len(packages)]
        lines = ["from __future__ import annotations", ""]
        for offset in (1, 2):
            other = index - offset
            if other >= 0:
                other_package = packages[other % len(packages)]
                lines.append(
                    f"from src.{other_package}.mod_{other:03d} import "
                    f"handle_{other:03d}"
                )
        lines += [
            "",
            f"def handle_{index:03d}(value: str) -> str:",
            f'    """Transform ``value`` for module {index:03d}."""',
            f'    marker = "m{index:03d}"',
        ]
        for offset in (1, 2):
            other = index - offset
            if other >= 0:
                lines.append(f"    value = handle_{other:03d}(value)")
        lines += ['    return f"{marker}:{value}"', ""]

        # Body, so a module has a realistic size rather than fifteen lines.
        for helper in range(_HELPERS_PER_MODULE):
            lines += [
                f"def step_{index:03d}_{helper:02d}(value: str) -> str:",
                f'    """Step {helper} of module {index:03d}."""',
                "    if not value:",
                '        raise ValueError("value is required")',
                f'    prefix = "s{helper:02d}"',
                "    parts = [prefix, value.strip()]",
                "    if len(parts) > 1:",
                '        return "-".join(parts)',
                "    return value",
                "",
            ]
        lines += [
            f"def check_{index:03d}(value: str) -> str:",
            "    if not value:",
            '        raise ValueError("value is required")',
            f"    return handle_{index:03d}(value)",
            "",
        ]
        target = root / "src" / package / f"mod_{index:03d}.py"
        target.write_text("\n".join(lines), encoding="utf-8")

    for start in range(0, modules, _MODULES_PER_DOCUMENT):
        covered = range(start, min(start + _MODULES_PER_DOCUMENT, modules))
        prose = [f"# Modules {start:03d}-{max(covered):03d}", ""]
        for index in covered:
            prose += [
                f"## Module {index:03d}",
                "",
                f"`handle_{index:03d}` transforms a value and delegates to the "
                f"two modules below it. `check_{index:03d}` rejects an empty "
                "value before calling it.",
                "",
                "### Steps",
                "",
            ]
            prose += [
                f"- `step_{index:03d}_{helper:02d}` prefixes and joins the parts."
                for helper in range(_HELPERS_PER_MODULE)
            ]
            prose.append("")
        (root / "docs" / f"modules_{start:03d}.md").write_text(
            "\n".join(prose), encoding="utf-8"
        )


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=120,
    )


def _edit_one_file(root: Path, modules: int, run: int) -> None:
    """Change one function body; each run's edit differs from the last."""
    index = modules // 2
    package = ("core", "services", "adapters")[index % 3]
    path = root / "src" / package / f"mod_{index:03d}.py"
    text = path.read_text(encoding="utf-8")
    marker = f'    marker = "m{index:03d}'
    replacement = f'    marker = "m{index:03d}-r{run:03d}'
    start = text.index(marker)
    end = text.index('"', start + len(marker))
    path.write_text(
        text[:start] + replacement + text[end:], encoding="utf-8"
    )


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    rank = max(0, round(0.95 * len(ordered)) - 1)
    return ordered[rank]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    calibration_before = calibrate()
    with tempfile.TemporaryDirectory(prefix="codeatlas-perf-") as workspace:
        root = Path(workspace) / "repo"
        root.mkdir()
        generate_repository(root, args.modules, args.profile)
        _git(root, "init", "--quiet")
        _git(root, "config", "user.email", "perf@example.invalid")
        _git(root, "config", "user.name", "CodeAtlas Perf")
        _git(root, "add", "-A")
        _git(root, "commit", "--quiet", "-m", "baseline")

        database = Path(workspace) / "perf.db"
        with connect(database) as connection:
            apply_migrations(connection)
            services = build_services(connection)
            repository = services.registration.register(
                RegisterRepositoryRequest(path=str(root))
            )
            repository_id = repository.repository_id

            started = time.perf_counter()
            services.indexing.index(repository_id)
            cold_index_s = time.perf_counter() - started

            refresh: list[float] = []
            for run in range(args.runs):
                _edit_one_file(root, args.modules, run)
                started = time.perf_counter()
                services.indexing.index(repository_id)
                refresh.append(time.perf_counter() - started)

            preflight: list[float] = []
            for run in range(args.runs):
                _edit_one_file(root, args.modules, args.runs + run)
                started = time.perf_counter()
                services.change_analysis.analyze_working_tree(
                    ChangeAnalysisRequest(
                        repository_id=repository_id,
                        request_id=f"perf_{run:03d}",
                    )
                )
                preflight.append(time.perf_counter() - started)

    calibration_after = calibrate()
    results = {
        # Probed before and after the samples. A run whose probes disagree
        # measured two different machines; see
        # docs/evaluation/phase-7-performance-environment.md (2026-08-21).
        "calibration_before_s": round(calibration_before, 4),
        "calibration_after_s": round(calibration_after, 4),
        "calibration_tolerance": CALIBRATION_TOLERANCE,
        "machine_settled": unsettled_reason(
            calibration_before, calibration_after
        ) is None,
        "profile": args.profile,
        "modules": args.modules,
        "runs": args.runs,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cold_index_s": round(cold_index_s, 3),
        "refresh_p50_s": round(statistics.median(refresh), 3),
        "refresh_p95_s": round(_p95(refresh), 3),
        "refresh_target_s": 2.0,
        "refresh_target_met": _p95(refresh) <= 2.0,
        "preflight_p50_s": round(statistics.median(preflight), 3),
        "preflight_p95_s": round(_p95(preflight), 3),
        "preflight_target_s": 10.0,
        "preflight_target_met": _p95(preflight) <= 10.0,
    }

    for key, value in results.items():
        print(f"{key}: {value}")
    if args.json_output is not None:
        args.json_output.write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if not results["machine_settled"]:
        print(
            f"WARNING: {unsettled_reason(calibration_before, calibration_after)}",
            file=sys.stderr,
        )
        if not args.allow_busy:
            return 2
    return 0 if results["refresh_target_met"] and results["preflight_target_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
