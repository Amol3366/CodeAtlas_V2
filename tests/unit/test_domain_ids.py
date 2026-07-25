"""Stable identity rules for repositories, files, symbols, and snapshots."""

from __future__ import annotations

from codeatlas.domain.ids import (
    evidence_id,
    file_id,
    repository_id,
    snapshot_id,
    stable_hash,
    symbol_id,
    symbol_version_id,
)


def test_stable_hash_is_deterministic_and_field_separated() -> None:
    assert stable_hash("a", "b") == stable_hash("a", "b")
    assert stable_hash("a", "b") != stable_hash("ab", "")
    assert len(stable_hash("a")) == 32


def test_stable_hash_is_lowercase_hex() -> None:
    value = stable_hash("PaymentService", "capture")
    assert value == value.lower()
    assert all(character in "0123456789abcdef" for character in value)


def test_repository_id_ignores_case_on_the_same_root() -> None:
    assert repository_id("C:/Repos/Demo") == repository_id("c:/repos/demo")


def test_repository_id_differs_between_roots() -> None:
    assert repository_id("C:/Repos/Demo") != repository_id("C:/Repos/Other")


def test_ids_carry_their_type_prefix() -> None:
    repository = repository_id("C:/Repos/Demo")
    file_value = file_id(repository, "src/a.py")
    logical = symbol_id(repository, "src/a.py", "A.run", "METHOD")
    assert repository.startswith("repo_")
    assert file_value.startswith("file_")
    assert logical.startswith("sym_")
    assert symbol_version_id(logical, "hash-1", "1.0.0").startswith("symv_")
    assert snapshot_id(repository, "fp", "1.0.0", "1.0.0").startswith("snap_")
    assert evidence_id("snap_1", file_value, 1, 2).startswith("ev_")


def test_symbol_version_changes_with_content_but_symbol_id_does_not() -> None:
    logical = symbol_id("repo_1", "src/a.py", "A.run", "METHOD")
    first = symbol_version_id(logical, "hash-1", "1.0.0")
    second = symbol_version_id(logical, "hash-2", "1.0.0")
    assert first != second
    assert logical == symbol_id("repo_1", "src/a.py", "A.run", "METHOD")


def test_symbol_version_changes_with_parser_bundle_version() -> None:
    logical = symbol_id("repo_1", "src/a.py", "A.run", "METHOD")
    assert symbol_version_id(logical, "hash-1", "1.0.0") != symbol_version_id(
        logical, "hash-1", "1.1.0"
    )


def test_symbol_id_distinguishes_kind_and_path() -> None:
    base = symbol_id("repo_1", "src/a.py", "A", "CLASS")
    assert base != symbol_id("repo_1", "src/a.py", "A", "FUNCTION")
    assert base != symbol_id("repo_1", "src/b.py", "A", "CLASS")


def test_snapshot_id_is_idempotent_for_identical_inputs() -> None:
    assert snapshot_id("repo_1", "fp", "1.0.0", "1.0.0") == snapshot_id(
        "repo_1", "fp", "1.0.0", "1.0.0"
    )


def test_snapshot_id_changes_with_fingerprint_or_versions() -> None:
    base = snapshot_id("repo_1", "fp", "1.0.0", "1.0.0")
    assert base != snapshot_id("repo_1", "other-fp", "1.0.0", "1.0.0")
    assert base != snapshot_id("repo_1", "fp", "2.0.0", "1.0.0")
    assert base != snapshot_id("repo_1", "fp", "1.0.0", "2.0.0")


def test_evidence_id_depends_on_the_line_range() -> None:
    assert evidence_id("snap_1", "file_1", 1, 2) != evidence_id(
        "snap_1", "file_1", 1, 3
    )
