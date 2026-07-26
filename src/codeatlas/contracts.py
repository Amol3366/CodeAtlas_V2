"""Versioned public contracts shared by all CodeAtlas delivery adapters."""

from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

CONTRACT_VERSION: Literal["1.0"] = "1.0"

OpaqueId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
PositiveLine = Annotated[int, Field(ge=1)]
NonNegativeDuration = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _validate_relative_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or any(ord(character) < 32 for character in value)
        or value != unicodedata.normalize("NFC", value)
    ):
        raise ValueError("file_path must be a normalized repository-relative path")
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        for part in parts
    ):
        raise ValueError("file_path must be a normalized repository-relative path")
    if PurePosixPath(value).is_absolute():
        raise ValueError("file_path must be a normalized repository-relative path")
    return value


RepositoryRelativePath = Annotated[
    str,
    StringConstraints(max_length=4096),
    AfterValidator(_validate_relative_path),
]


def _validate_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


UtcDatetime = Annotated[datetime, AfterValidator(_validate_utc)]


class ContractModel(BaseModel):
    """Strict base configuration for boundary models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Derivation(StrEnum):
    DETERMINISTIC = "deterministic"
    STATIC_RESOLVED = "static_resolved"
    HIGH_CONFIDENCE_HEURISTIC = "high_confidence_heuristic"
    LOW_CONFIDENCE_HEURISTIC = "low_confidence_heuristic"
    SEMANTIC_CANDIDATE = "semantic_candidate"
    MODEL_GENERATED = "model_generated"
    UNSUPPORTED = "unsupported"


class EvidenceValidation(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


class SnapshotFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SymbolKind(StrEnum):
    MODULE = "MODULE"
    PACKAGE = "PACKAGE"
    CLASS = "CLASS"
    INTERFACE = "INTERFACE"
    ENUM = "ENUM"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    CONSTRUCTOR = "CONSTRUCTOR"
    PROPERTY = "PROPERTY"
    FIELD = "FIELD"
    CONSTANT = "CONSTANT"
    TYPE_ALIAS = "TYPE_ALIAS"
    ROUTE = "ROUTE"
    TEST = "TEST"
    FIXTURE = "FIXTURE"
    CONFIG_KEY = "CONFIG_KEY"
    DATABASE_TABLE = "DATABASE_TABLE"
    DATABASE_COLUMN = "DATABASE_COLUMN"
    SQL_QUERY = "SQL_QUERY"
    DOCUMENT_SECTION = "DOCUMENT_SECTION"


class RelationKind(StrEnum):
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    EXPORTS = "EXPORTS"
    CALLS = "CALLS"
    MAY_CALL = "MAY_CALL"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    OVERRIDES = "OVERRIDES"
    ROUTES_TO = "ROUTES_TO"
    TESTS = "TESTS"
    DOCUMENTS = "DOCUMENTS"
    READS = "READS"
    WRITES = "WRITES"
    QUERIES = "QUERIES"
    CONFIGURES = "CONFIGURES"
    REFERENCES = "REFERENCES"
    DEPENDS_ON = "DEPENDS_ON"


class SnapshotReference(ContractModel):
    snapshot_id: OpaqueId
    git_head: OpaqueId | None
    working_tree_fingerprint: OpaqueId
    freshness: SnapshotFreshness
    semantic_coverage: Confidence


class Evidence(ContractModel):
    evidence_id: OpaqueId
    repository_id: OpaqueId
    snapshot_id: OpaqueId
    file_path: RepositoryRelativePath
    symbol: NonEmptyText | None = None
    start_line: PositiveLine
    end_line: PositiveLine
    excerpt: Annotated[str, StringConstraints(max_length=16384)]
    content_hash: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    validation: EvidenceValidation

    @model_validator(mode="after")
    def validate_line_range(self) -> Evidence:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class Claim(ContractModel):
    claim_id: OpaqueId
    text: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    evidence_ids: list[OpaqueId] = Field(min_length=1)


class Answer(ContractModel):
    summary: NonEmptyText
    claims: list[Claim]


class Finding(ContractModel):
    code: NonEmptyText
    severity: Severity
    title: NonEmptyText
    description: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    evidence_ids: list[OpaqueId] = Field(min_length=1)
    remediation: str | None = None
    limitations: list[str] = Field(default_factory=list)


class RelationStep(ContractModel):
    """One edge of a relation path, citable on its own.

    Every step carries its own evidence, so a path is auditable edge by edge
    rather than as an opaque conclusion a reader has to take on faith.
    """

    source: NonEmptyText
    kind: RelationKind
    target: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    evidence_id: OpaqueId


class RelationPath(ContractModel):
    steps: list[RelationStep] = Field(min_length=1)


class QueryResponse(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    request_id: OpaqueId
    repository_id: OpaqueId
    snapshot: SnapshotReference
    answer: Answer
    evidence: list[Evidence]
    # Additive and optional (ADR-0004), so `contract_version` stays "1.0" and a
    # client written against Phase 2 keeps working unchanged.
    relation_paths: list[RelationPath] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    timing_ms: dict[str, NonNegativeDuration] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_membership(self) -> QueryResponse:
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")

        for item in self.evidence:
            if item.repository_id != self.repository_id:
                raise ValueError(
                    "evidence repository must match response repository"
                )
            if item.snapshot_id != self.snapshot.snapshot_id:
                raise ValueError("evidence snapshot must match response snapshot")
            if item.validation is not EvidenceValidation.VALID:
                raise ValueError("claims may use only valid evidence")

        for claim in self.answer.claims:
            unknown = set(claim.evidence_ids) - evidence_by_id.keys()
            if unknown:
                raise ValueError("claim references unknown evidence")

        # A path step citing evidence that is not in the response would be an
        # unverifiable link in an otherwise auditable chain.
        for path in self.relation_paths:
            for step in path.steps:
                if step.evidence_id not in evidence_by_id:
                    raise ValueError("relation step references unknown evidence")
        return self


class ErrorDetail(ContractModel):
    code: NonEmptyText
    message: NonEmptyText
    request_id: OpaqueId
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(ContractModel):
    error: ErrorDetail


class StreamEventMetadata(ContractModel):
    contract_version: Literal["1.0"] = CONTRACT_VERSION
    request_id: OpaqueId
    conversation_id: OpaqueId
    message_id: OpaqueId
    sequence: Annotated[int, Field(ge=0)]
    timestamp: UtcDatetime
