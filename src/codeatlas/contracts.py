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

CONTRACT_VERSION: Literal["1.1"] = "1.1"

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
    contract_version: Literal["1.1"] = CONTRACT_VERSION
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
    contract_version: Literal["1.1"] = CONTRACT_VERSION
    request_id: OpaqueId
    conversation_id: OpaqueId
    message_id: OpaqueId
    sequence: Annotated[int, Field(ge=0)]
    timestamp: UtcDatetime


# ---------------------------------------------------------------------------
# Change assurance (Phase 4, ADR-0005).
#
# These models are additive: `contract_version` stays "1.0" and a client
# written against Phase 3 keeps working against a backend that never produces
# a change report. The report is the persisted machine-readable rendering of one
# analysis; Markdown and SARIF are derived from the same rows in P4-09.
# ---------------------------------------------------------------------------


class ChangeAnalysisKind(StrEnum):
    """Which form of diff an analysis compares."""

    WORKING_TREE = "working_tree"
    COMMIT_RANGE = "commit_range"


class ChangeAnalysisStatus(StrEnum):
    """Lifecycle of one change analysis."""

    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class OverallRisk(StrEnum):
    """The highest severity present in an analysis, or none.

    Extends :class:`Severity` with one ``NONE`` value so an analysis with no
    findings can still name its overall risk honestly rather than being absent.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    NONE = "none"


class ChangeKind(StrEnum):
    """What happened to one symbol across a change."""

    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    MOVED = "moved"
    DEPENDENCY = "dependency"


class AnalysisSide(StrEnum):
    """Which side of a change a piece of evidence belongs to.

    Base-side evidence is hash-verified at analysis time and historical by
    construction; it is labeled as base so a reader never mistakes it for the
    current snapshot's content.
    """

    BASE = "base"
    TARGET = "target"


class FileChangeKind(StrEnum):
    """The file-level diff classification."""

    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"


class AnalysisStateRef(ContractModel):
    """One side of a change: the ref the caller asked for and what it resolved
    to.

    The base side carries no snapshot ID — it is reconstructed in memory or read
    from Git objects, never a stored active snapshot. The target side carries
    the active snapshot ID it was analyzed against, so a reader can tell exactly
    which snapshot the analysis is bound to.
    """

    ref: NonEmptyText
    commit: OpaqueId | None
    snapshot_id: OpaqueId | None
    freshness: SnapshotFreshness


class ChangedFile(ContractModel):
    """One file in the file-level diff."""

    path: RepositoryRelativePath
    change_kind: FileChangeKind
    base_path: RepositoryRelativePath | None = None
    content_hash_changed: bool = False


class ChangedSymbol(ContractModel):
    """One symbol that differs between the base and target states.

    A deleted or moved-from symbol carries base line range and a base file path;
    an added symbol carries target range; a modified symbol carries target
    range and, when its content also moved, a base file path. The two are kept
    consistent: base lines without a base file is a contradiction the contract
    refuses, because a citation with no file is not a citation.
    """

    qualified_name: NonEmptyText
    symbol_kind: SymbolKind
    change_kind: ChangeKind
    file_path: RepositoryRelativePath
    base_file_path: RepositoryRelativePath | None = None
    base_start_line: PositiveLine | None = None
    base_end_line: PositiveLine | None = None
    target_start_line: PositiveLine | None = None
    target_end_line: PositiveLine | None = None
    signature_changed: bool
    public: bool
    derivation: Derivation
    confidence: Confidence

    @model_validator(mode="after")
    def validate_ranges(self) -> ChangedSymbol:
        has_base_lines = (
            self.base_start_line is not None or self.base_end_line is not None
        )
        if has_base_lines and self.base_file_path is None:
            raise ValueError(
                "base_start_line or base_end_line requires a base_file_path"
            )
        if (
            self.base_start_line is not None
            and self.base_end_line is not None
            and self.base_end_line < self.base_start_line
        ):
            raise ValueError("base_end_line must not precede base_start_line")
        if (
            self.target_start_line is not None
            and self.target_end_line is not None
            and self.target_end_line < self.target_start_line
        ):
            raise ValueError("target_end_line must not precede target_start_line")
        return self


class ImpactEdge(ContractModel):
    """One edge in the impact graph, labeled but not cited.

    An impact edge is a graph fact with a derivation and a confidence; it is
    not a citable region of source. Keeping evidence off the edge is what keeps
    the response's evidence list minimal and the exact/containing metrics
    meaningful, per ADR-0003 and ADR-0005.
    """

    source: NonEmptyText
    target: NonEmptyText
    kind: RelationKind
    derivation: Derivation
    confidence: Confidence


class ChangeEvidenceItem(ContractModel):
    """One piece of analysis-scoped evidence, explicitly base- or target-side.

    Unlike :class:`Evidence`, the analysis evidence model carries a ``side``
    rather than a repository-wide ``snapshot_id``: the base side of a working
    tree has no stored snapshot, only a commit, and pretending otherwise would
    hide the historical nature of base-side citations.
    """

    evidence_id: OpaqueId
    side: AnalysisSide
    file_path: RepositoryRelativePath
    symbol: NonEmptyText | None = None
    start_line: PositiveLine
    end_line: PositiveLine
    content_hash: NonEmptyText
    derivation: Derivation
    confidence: Confidence

    @model_validator(mode="after")
    def validate_range(self) -> ChangeEvidenceItem:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class ChangeAnalysisReport(ContractModel):
    """The persisted, machine-readable rendering of one change analysis."""

    contract_version: Literal["1.1"] = CONTRACT_VERSION
    analysis_id: OpaqueId
    request_id: OpaqueId
    repository_id: OpaqueId
    kind: ChangeAnalysisKind
    status: ChangeAnalysisStatus
    overall_risk: OverallRisk
    base: AnalysisStateRef
    target: AnalysisStateRef
    changed_files: list[ChangedFile] = Field(default_factory=list)
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    impact_edges: list[ImpactEdge] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[ChangeEvidenceItem] = Field(default_factory=list)
    test_gaps: list[NonEmptyText] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    timing_ms: dict[str, NonNegativeDuration] = Field(default_factory=dict)
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def validate_membership(self) -> ChangeAnalysisReport:
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")

        for finding in self.findings:
            unknown = set(finding.evidence_ids) - evidence_by_id.keys()
            if unknown:
                raise ValueError("finding references unknown evidence")

        if self.changed_symbols and not self.changed_files:
            raise ValueError(
                "changed_files cannot be empty when changed_symbols is not"
            )
        return self


# ---------------------------------------------------------------------------
# Conversations (Phase 5, ADR-0006).
#
# Additive: `contract_version` stays "1.0" and a client written against Phase 4
# keeps working against a backend that never serves a conversation. Chat history
# is first-class persistent application data (`AGENTS.md` Section 8.2), so these
# models describe stored rows, not view state: the backend owns them and the web
# client consumes them.
# ---------------------------------------------------------------------------


class MessageRole(StrEnum):
    """Who produced a message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM_EVENT = "system_event"


class MessageStatus(StrEnum):
    """Where a message is in its lifecycle.

    A failed or cancelled message stays visible and retryable; the states are
    explicit rather than a boolean so partial and failed work can be told apart
    from work that never started.
    """

    QUEUED = "queued"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    """Where one attempt at answering a message is in its lifecycle."""

    QUEUED = "queued"
    RETRIEVING = "retrieving"
    GENERATING = "generating"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StreamEventType(StrEnum):
    """The Section 11.2 event vocabulary.

    Clients must ignore unknown future types; the ones named here are the
    published set a Phase 5 client may rely on.
    """

    RUN_ACCEPTED = "run.accepted"
    RETRIEVAL_STARTED = "retrieval.started"
    RETRIEVAL_PROGRESS = "retrieval.progress"
    EVIDENCE_AVAILABLE = "evidence.available"
    GENERATION_DELTA = "generation.delta"
    ANSWER_COMPLETED = "answer.completed"
    RUN_WARNING = "run.warning"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    HEARTBEAT = "heartbeat"


class Conversation(ContractModel):
    """One persisted thread, always bound to a single repository.

    A conversation never changes repository: switching requires a new thread
    (Section 14.5), so a historical answer can never be reinterpreted against a
    repository it did not examine.
    """

    conversation_id: OpaqueId
    repository_id: OpaqueId
    title: NonEmptyText
    created_at: UtcDatetime
    updated_at: UtcDatetime
    last_message_at: UtcDatetime | None = None
    archived_at: UtcDatetime | None = None


class Message(ContractModel):
    """One turn in a conversation.

    ``sequence_number`` starts at 1 and orders the thread; it is also the
    stream's resume key, so 0 is reserved to mean "nothing yet".
    """

    message_id: OpaqueId
    conversation_id: OpaqueId
    role: MessageRole
    status: MessageStatus
    sequence_number: Annotated[int, Field(ge=1)]
    content: str = ""
    error_code: NonEmptyText | None = None
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    # Carried with the message rather than fetched per citation. Reading a
    # thread means reading every message's citations, and one request per
    # citation would make reopening a long thread cost dozens of round trips.
    # Since P6-STREAM the submission no longer returns the answer, so this is
    # also the only way a reloaded thread recovers what its answers cited.
    evidence: list[MessageEvidenceItem] = Field(default_factory=list)
    # From the message's most recent run. The snapshot is what lets a reopened
    # thread label an old answer with the tree it actually examined rather than
    # implying it is current (Section 14.5); it is null while a run is queued,
    # because a queued run has not resolved one.
    snapshot_id: OpaqueId | None = None
    warnings: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Message:
        if self.status is MessageStatus.COMPLETE and not self.content.strip():
            # A completed answer with no text is the silent-success failure
            # mode the evidence contract exists to prevent.
            raise ValueError("a complete message must carry content")
        if self.status is MessageStatus.FAILED and not self.error_code:
            raise ValueError("a failed message must carry an error code")
        return self


class MessageRun(ContractModel):
    """One attempt at answering a message, with the snapshot it answered
    against.

    The snapshot ID is what lets a historical message keep its own freshness
    label forever: reopening history must not relabel old evidence as current
    (Section 14.5).
    """

    run_id: OpaqueId
    message_id: OpaqueId
    repository_id: OpaqueId
    snapshot_id: OpaqueId
    normalized_query: str
    intent: NonEmptyText
    retrieval_policy_version: NonEmptyText
    status: RunStatus
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    latency_ms: NonNegativeDuration | None = None
    warnings: list[NonEmptyText] = Field(default_factory=list)


class MessageEvidenceItem(ContractModel):
    """One citation attached to an assistant message.

    The evidence fields are snapshotted rather than joined live: a historical
    message must keep telling the truth it told after its snapshot is
    superseded, which is the same audit rule change analyses follow.
    """

    evidence_id: OpaqueId
    citation_ordinal: Annotated[int, Field(ge=1)]
    file_path: RepositoryRelativePath
    symbol: NonEmptyText | None = None
    start_line: PositiveLine
    end_line: PositiveLine
    content_hash: NonEmptyText
    derivation: Derivation
    confidence: Confidence
    snapshot_id: OpaqueId
    claim_ids: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> MessageEvidenceItem:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class StreamEvent(ContractModel):
    """One typed event on a conversation stream.

    The envelope is :class:`StreamEventMetadata`'s fields plus a typed
    discriminator and payload. Streaming text is provisional; the persisted
    message is authoritative (Section 11.2).
    """

    contract_version: Literal["1.1"] = CONTRACT_VERSION
    request_id: OpaqueId
    conversation_id: OpaqueId
    message_id: OpaqueId
    sequence: Annotated[int, Field(ge=0)]
    timestamp: UtcDatetime
    event: StreamEventType
    payload: dict[str, Any] = Field(default_factory=dict)


class ConversationPage(ContractModel):
    """One page of conversations, newest activity first."""

    items: list[Conversation] = Field(default_factory=list)
    next_cursor: OpaqueId | None = None


class MessagePage(ContractModel):
    """One page of messages, in sequence order."""

    items: list[Message] = Field(default_factory=list)
    next_cursor: OpaqueId | None = None


class MessageSubmission(ContractModel):
    """The result of submitting one question.

    Phase 5 answers deterministically and synchronously, so the submission
    already carries the finished answer. The IDs are returned regardless of
    outcome: a failed or cancelled turn is still a turn the client must be able
    to display and retry.
    """

    contract_version: Literal["1.1"] = CONTRACT_VERSION
    conversation_id: OpaqueId
    user_message_id: OpaqueId
    message_id: OpaqueId
    run_id: OpaqueId
    status: MessageStatus
    sequence_number: Annotated[int, Field(ge=1)]
    content: str = ""
    snapshot_id: OpaqueId | None = None
    intent: NonEmptyText
    evidence: list[MessageEvidenceItem] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    limitations: list[NonEmptyText] = Field(default_factory=list)
    error_code: NonEmptyText | None = None
    latency_ms: NonNegativeDuration | None = None
