"""Finalized CodeAtlas domain enumerations.

These enums are part of the product contract (Phase 0). They are pure stdlib
(no framework/I/O imports) so the domain layer stays dependency-free per
CLAUDE.md §4 layering rules.

- SymbolType: Blueprint §4.4.6
- RelationType: Blueprint §4.4.7
Other enums encode the vocabulary the Blueprint uses throughout (derivation,
confidence bands, file classification, snapshot lifecycle, query intent, etc.).
"""

from __future__ import annotations

from enum import StrEnum


class SymbolType(StrEnum):
    """Normalized symbol types (Blueprint §4.4.6). Fixed for the MVP."""

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


class RelationType(StrEnum):
    """Normalized relation types (Blueprint §4.4.7). Fixed for the MVP.

    Invariant (CLAUDE.md §2.11): CALLS is static_resolved certainty; MAY_CALL is
    heuristic. They must never be conflated.
    """

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


class Derivation(StrEnum):
    """How a relation/claim was derived. Drives transparent uncertainty.

    Ordered from most to least certain. `static_resolved` is the only value that
    may carry confidence == 1.0.
    """

    STATIC_RESOLVED = "static_resolved"
    AST_ENRICHED = "ast_enriched"
    NAME_AND_IMPORT_HEURISTIC = "name_and_import_heuristic"
    NAMING_CONVENTION = "naming_convention"
    LEXICAL_MATCH = "lexical_match"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    CO_CHANGE = "co_change"
    MANUAL_LINK = "manual_link"
    RULE_ENGINE = "rule_engine"


class ConfidenceBand(StrEnum):
    """Confidence labels (Blueprint §7.7): high 0.80-1.00, medium 0.55-0.79, low <0.55."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FileClassification(StrEnum):
    """File classification categories (Blueprint §4.3.4)."""

    SOURCE_CODE = "source_code"
    TEST_CODE = "test_code"
    DOCUMENTATION = "documentation"
    ARCHITECTURE_DECISION = "architecture_decision"
    API_SPECIFICATION = "api_specification"
    CONFIGURATION = "configuration"
    DATABASE_SCHEMA = "database_schema"
    MIGRATION = "migration"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    LOCKFILE = "lockfile"
    INFRASTRUCTURE = "infrastructure"
    GENERATED = "generated"
    VENDOR = "vendor"
    BINARY = "binary"
    UNKNOWN = "unknown"


class Language(StrEnum):
    """Languages fixed for the MVP (Blueprint §1.3, CLAUDE.md Phase 0)."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    MARKDOWN = "markdown"
    JSON = "json"
    YAML = "yaml"
    TOML = "toml"


class SnapshotStatus(StrEnum):
    """Snapshot lifecycle state machine (CLAUDE.md §2.10, Blueprint §4.3.6)."""

    STAGING = "staging"
    VALIDATING = "validating"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class IndexStatus(StrEnum):
    """Deterministic / semantic index readiness (Blueprint §4.3.7)."""

    PENDING = "pending"
    PARTIAL = "partial"
    READY = "ready"
    FAILED = "failed"


class SnapshotType(StrEnum):
    """What a snapshot represents (Blueprint §4.3.6)."""

    GIT_COMMIT = "git_commit"
    WORKING_TREE = "working_tree"
    DIRECTORY = "directory"  # non-Git local directory


class ChunkRole(StrEnum):
    """Logical role of a chunk (Blueprint §4.5.2-4.5.3). Part of chunk identity."""

    FILE_SUMMARY = "file_summary"
    SYMBOL_IMPLEMENTATION = "symbol_implementation"
    OVERSIZED_SYMBOL_PART = "oversized_symbol_part"
    CALL_SITE = "call_site"
    DOCUMENT_SECTION = "document_section"
    CONFIG_KEY = "config_key"


class ParseStatus(StrEnum):
    """Per-file parse state (parse failures are first-class, visible states)."""

    PENDING = "pending"
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobType(StrEnum):
    """Indexing job kinds (Blueprint §4.10, indexing job table)."""

    FULL_INDEX = "full_index"
    INCREMENTAL_INDEX = "incremental_index"


class JobStatus(StrEnum):
    """Resumable/recoverable indexing job states (CLAUDE.md §2.12, Phase 2).

    ``RUNNING`` is the only unsafe-on-crash state; startup recovery moves any
    such job back to ``PENDING`` so it can be retried.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IntentType(StrEnum):
    """Query intent types (Blueprint §7.2)."""

    LOCATE = "LOCATE"
    EXPLAIN = "EXPLAIN"
    TRACE_FLOW = "TRACE_FLOW"
    FIND_CALLERS = "FIND_CALLERS"
    FIND_DEPENDENCIES = "FIND_DEPENDENCIES"
    FIND_TESTS = "FIND_TESTS"
    FIND_DOCUMENTS = "FIND_DOCUMENTS"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    ARCHITECTURE = "ARCHITECTURE"
    CONFIGURATION = "CONFIGURATION"
    DATABASE = "DATABASE"
    HISTORY = "HISTORY"
    GENERAL_PROJECT = "GENERAL_PROJECT"


class ChangeKind(StrEnum):
    """Classification of a changed symbol (Blueprint §3.6, Phase 8)."""

    ADDED = "added"
    MODIFIED = "modified"
    MOVED = "moved"
    DELETED = "deleted"


class EvidenceKind(StrEnum):
    """Kind of an evidence item (Blueprint §7.6 / §4.8.9 evidence roles)."""

    CODE = "code"
    TEST = "test"
    DOCUMENT = "document"
    CONFIGURATION = "configuration"
    SCHEMA = "schema"
    HISTORY = "history"
    RELATION = "relation"


class Severity(StrEnum):
    """Finding severity (Blueprint §3.7 rule severities, §10.9 Finding)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingCategory(StrEnum):
    """Finding categories produced by the change-impact and rule engines."""

    CONTRACT_CHANGE = "contract_change"
    IMPACT = "impact"
    TEST_GAP = "test_gap"
    DOCUMENTATION_DRIFT = "documentation_drift"
    ARCHITECTURE_VIOLATION = "architecture_violation"
    CONFIGURATION_IMPACT = "configuration_impact"
    SCHEMA_IMPACT = "schema_impact"
    RISK = "risk"
