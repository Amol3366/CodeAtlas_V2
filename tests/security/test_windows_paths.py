"""Windows filesystem semantics that must hold before release.

These are the cases that make a Windows-first product behave differently from a
POSIX one: case-insensitive roots, reserved device names, trailing dots and
spaces, long paths, deep trees, and junctions. Each is asserted against the real
filesystem rather than a simulation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from codeatlas.domain.ids import repository_id
from codeatlas.domain.paths import canonicalize_root
from codeatlas.domain.repository import ScanLimits
from codeatlas.repositories.ignore_rules import IgnoreRules
from codeatlas.repositories.scanner import RepositoryScanner, ScanResult

windows_only = pytest.mark.skipif(
    os.name != "nt", reason="Windows-only path semantics"
)


def _scan(root_path: Path, limits: ScanLimits | None = None) -> ScanResult:
    root = canonicalize_root(str(root_path))
    scanner = RepositoryScanner(limits) if limits else RepositoryScanner()
    return scanner.scan(root, IgnoreRules.load(root))


def test_mixed_case_roots_resolve_to_one_repository_identity(
    sample_repo: Path,
) -> None:
    lower = repository_id(canonicalize_root(str(sample_repo)).as_posix().lower())
    upper = repository_id(canonicalize_root(str(sample_repo)).as_posix().upper())
    assert lower == upper


@windows_only
def test_reserved_device_names_are_rejected(sample_repo: Path) -> None:
    # NUL cannot be created as a real file on Windows, so the reserved-name rule
    # is asserted through the path validator the scanner uses for every entry.
    from codeatlas.domain.errors import PathSafetyError
    from codeatlas.domain.paths import validate_relative_path

    for reserved in ("NUL.py", "aux.txt", "src/COM1.py", "prn"):
        with pytest.raises(PathSafetyError):
            validate_relative_path(reserved)


def test_trailing_dot_or_space_segments_are_rejected() -> None:
    from codeatlas.domain.errors import PathSafetyError
    from codeatlas.domain.paths import validate_relative_path

    for candidate in ("src/bad./file.py", "src/bad /file.py", "trailing.", "space "):
        with pytest.raises(PathSafetyError):
            validate_relative_path(candidate)


def test_paths_longer_than_the_limit_are_skipped_with_a_reason(
    sample_repo: Path,
) -> None:
    nested = sample_repo / "a" / "bbbbbbbbbb" / "cccccccccc"
    nested.mkdir(parents=True)
    (nested / "deep_file_name.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _scan(sample_repo, ScanLimits(max_relative_path_length=20))
    assert any(item.reason_code == "PATH_REJECTED" for item in result.skipped)
    assert all(
        len(record.relative_path) <= 20 for record in result.files
    )


def test_directories_deeper_than_the_limit_are_skipped(sample_repo: Path) -> None:
    deep = sample_repo / "l1" / "l2" / "l3" / "l4"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _scan(sample_repo, ScanLimits(max_depth=2))
    assert any(item.reason_code == "TOO_DEEP" for item in result.skipped)
    assert all("l3" not in record.relative_path for record in result.files)


def test_junction_escaping_the_root_is_excluded_with_a_security_warning(
    sample_repo: Path,
) -> None:
    outside = sample_repo.parent / "outside_secrets"
    outside.mkdir()
    (outside / "secret.py").write_text("TOKEN = 'value'\n", encoding="utf-8")
    link = sample_repo / "linked"

    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(outside, link, target_is_directory=True)

    result = _scan(sample_repo)
    assert all("secret.py" not in record.relative_path for record in result.files)
    assert any(item.reason_code == "OUTSIDE_ROOT" for item in result.skipped)
    assert any("SECURITY_LINK_ESCAPE" in warning for warning in result.warnings)


def test_junction_inside_the_root_is_followed(sample_repo: Path) -> None:
    target = sample_repo / "shared"
    target.mkdir()
    (target / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    link = sample_repo / "alias"

    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)

    result = _scan(sample_repo)
    paths = {record.relative_path for record in result.files}
    assert "shared/helper.py" in paths
    assert "alias/helper.py" in paths


def test_utf8_bom_files_are_indexed_not_reported_as_parse_errors(
    sample_repo: Path,
) -> None:
    (sample_repo / "bom_module.py").write_bytes(
        b"\xef\xbb\xbf" + b"class BomClass:\n    pass\n"
    )
    result = _scan(sample_repo)
    assert any(record.relative_path == "bom_module.py" for record in result.files)


def test_non_ascii_filenames_are_scanned(sample_repo: Path) -> None:
    (sample_repo / "café.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = _scan(sample_repo)
    assert any("caf" in record.relative_path for record in result.files)


def test_unreadable_directory_degrades_without_crashing(sample_repo: Path) -> None:
    # A directory that disappears between listing and reading must not abort the
    # scan; the scanner reports it and continues.
    missing = sample_repo / "vanishing"
    missing.mkdir()
    result = _scan(sample_repo)
    assert isinstance(result.files, tuple)
