"""Load and validate the versioned Phase 0 evaluation corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator

from codeatlas.contracts import (
    CONTRACT_VERSION,
    ContractModel,
    NonEmptyText,
    OpaqueId,
    PositiveLine,
    RepositoryRelativePath,
)


class DatasetError(ValueError):
    """The evaluation corpus is malformed or references invalid fixture data."""


class FixtureSnapshot(ContractModel):
    id: OpaqueId
    members: list[RepositoryRelativePath] = Field(min_length=1)


class FixtureDescriptor(ContractModel):
    id: OpaqueId
    root: RepositoryRelativePath
    kind: NonEmptyText
    snapshots: list[FixtureSnapshot] = Field(min_length=1)


class EvidenceExpectation(ContractModel):
    evidence_id: OpaqueId
    snapshot_id: OpaqueId
    file_path: RepositoryRelativePath
    symbol: NonEmptyText | None = None
    start_line: PositiveLine
    end_line: PositiveLine
    validated_line_count: int = Field(default=0, exclude=True, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> EvidenceExpectation:
        if self.end_line < self.start_line:
            raise ValueError("evidence end_line must not precede start_line")
        return self


class QueryCase(ContractModel):
    id: OpaqueId
    repository_fixture: OpaqueId
    snapshot_id: OpaqueId
    question: NonEmptyText
    intent: NonEmptyText
    expected_abstention: bool
    expected_symbols: list[NonEmptyText]
    expected_relations: list[NonEmptyText]
    expected_evidence: list[EvidenceExpectation]
    warnings: list[str]
    limitations: list[str]
    forbidden_claims: list[NonEmptyText]


class ChangeCase(ContractModel):
    id: OpaqueId
    repository_fixture: OpaqueId
    snapshot_id: OpaqueId
    base_ref: NonEmptyText
    target_ref: NonEmptyText
    expected_symbols: list[NonEmptyText]
    expected_relations: list[NonEmptyText]
    expected_evidence: list[EvidenceExpectation]
    expected_changed_symbols: list[NonEmptyText]
    expected_impact_paths: list[list[NonEmptyText]]
    expected_findings: list[NonEmptyText]
    warnings: list[str]
    limitations: list[str]
    forbidden_claims: list[NonEmptyText]


class DatasetManifest(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    fixtures_root: RepositoryRelativePath
    fixtures: list[FixtureDescriptor] = Field(min_length=1)
    query_cases_file: RepositoryRelativePath
    change_cases_file: RepositoryRelativePath
    expected_query_count: Annotated[int, Field(ge=1)]
    expected_change_count: Annotated[int, Field(ge=1)]


class QueryCaseFile(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    cases: list[QueryCase]


class ChangeCaseFile(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    cases: list[ChangeCase]


class Dataset(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    fixtures_root: Path
    fixtures: list[FixtureDescriptor]
    query_cases: list[QueryCase]
    change_cases: list[ChangeCase]


def load_dataset(dataset_root: Path) -> Dataset:
    """Load a dataset and validate every evidence location without imports."""
    try:
        root = dataset_root.resolve(strict=True)
        manifest = DatasetManifest.model_validate(
            _read_json(root / "dataset.json")
        )
        query_file = QueryCaseFile.model_validate(
            _read_json(_resolve_inside(root, manifest.query_cases_file))
        )
        change_file = ChangeCaseFile.model_validate(
            _read_json(_resolve_inside(root, manifest.change_cases_file))
        )
        _validate_unique_ids(
            [case.id for case in query_file.cases], "query case IDs"
        )
        _validate_unique_ids(
            [case.id for case in change_file.cases], "change case IDs"
        )
        if len(query_file.cases) != manifest.expected_query_count:
            raise DatasetError(
                "query case count does not match expected_query_count"
            )
        if len(change_file.cases) != manifest.expected_change_count:
            raise DatasetError(
                "change case count does not match expected_change_count"
            )

        fixtures_root = _resolve_inside(root, manifest.fixtures_root)
        fixtures = {fixture.id: fixture for fixture in manifest.fixtures}
        if len(fixtures) != len(manifest.fixtures):
            raise DatasetError("fixture IDs must be unique")
        fixture_roots = {
            fixture_id: _resolve_inside(fixtures_root, fixture.root)
            for fixture_id, fixture in fixtures.items()
        }
        if any(not fixture_root.is_dir() for fixture_root in fixture_roots.values()):
            raise DatasetError("every fixture root must be a directory")
        snapshot_membership = {
            fixture.id: {
                snapshot.id: set(snapshot.members)
                for snapshot in fixture.snapshots
            }
            for fixture in manifest.fixtures
        }
        if any(
            len(snapshots) != len(fixture.snapshots)
            for fixture, snapshots in (
                (fixture, snapshot_membership[fixture.id])
                for fixture in manifest.fixtures
            )
        ):
            raise DatasetError("fixture snapshot IDs must be unique")

        queries = [
            case.model_copy(
                update={
                    "expected_evidence": _validate_evidence(
                        case.repository_fixture,
                        case.expected_evidence,
                        fixture_roots,
                        snapshot_membership,
                    )
                }
            )
            for case in query_file.cases
        ]
        changes = [
            case.model_copy(
                update={
                    "expected_evidence": _validate_evidence(
                        case.repository_fixture,
                        case.expected_evidence,
                        fixture_roots,
                        snapshot_membership,
                    )
                }
            )
            for case in change_file.cases
        ]
        return Dataset(
            fixtures_root=fixtures_root,
            fixtures=manifest.fixtures,
            query_cases=queries,
            change_cases=changes,
        )
    except DatasetError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise DatasetError(str(exc)) from exc


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _resolve_inside(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = (resolved_root / relative_path).resolve(strict=True)
    if not candidate.is_relative_to(resolved_root):
        raise DatasetError("path must remain repository-relative")
    return candidate


def _validate_unique_ids(ids: list[str], label: str) -> None:
    if len(ids) != len(set(ids)):
        raise DatasetError(f"{label} must be unique")


def _validate_evidence(
    fixture_id: str,
    evidence: list[EvidenceExpectation],
    fixture_roots: dict[str, Path],
    snapshot_membership: dict[str, dict[str, set[str]]],
) -> list[EvidenceExpectation]:
    if fixture_id not in fixture_roots:
        raise DatasetError(f"unknown repository fixture: {fixture_id}")
    fixture_root = fixture_roots[fixture_id]
    validated: list[EvidenceExpectation] = []
    evidence_ids = [item.evidence_id for item in evidence]
    _validate_unique_ids(evidence_ids, "evidence IDs")
    for item in evidence:
        members = snapshot_membership[fixture_id].get(item.snapshot_id)
        if members is None or item.file_path not in members:
            raise DatasetError(
                "evidence does not belong to declared snapshot membership"
            )
        source_path = _resolve_inside(fixture_root, item.file_path)
        if not source_path.is_file():
            raise DatasetError(f"evidence is not a file: {item.file_path}")
        line_count = len(
            source_path.read_text(encoding="utf-8").splitlines()
        )
        if item.end_line > line_count:
            raise DatasetError(
                f"evidence line range exceeds {item.file_path}: "
                f"{item.end_line} > {line_count}"
            )
        validated.append(
            item.model_copy(update={"validated_line_count": line_count})
        )
    return validated
