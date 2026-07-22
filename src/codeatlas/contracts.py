"""Shared evidence & response contracts (Pydantic v2).

These are the wire/serialization contracts carried identically across every
delivery surface — CLI, MCP, REST, JSON, Markdown, SARIF (CLAUDE.md §11). Every
output must carry the same evidence contract: repository, snapshot, file, symbol,
lines, relation path, confidence, derivation, warnings.

Drafted in Phase 0; concrete producers/validators arrive in later phases. Kept
separate from `domain/` (which is framework-free) and from ORM models.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from codeatlas.domain.enums import (
    Derivation,
    EvidenceKind,
    FindingCategory,
    IntentType,
    RelationType,
    Severity,
)


class _Contract(BaseModel):
    """Base for all contract models: strict, immutable, forbids unknown fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Scope(_Contract):
    """The repository + active snapshot every response is pinned to.

    Snapshot consistency (CLAUDE.md §2.7): all evidence in one response belongs to
    this scope unless the query is explicitly historical.
    """

    repository_id: str
    snapshot_id: str
    branch: str | None = None
    commit_sha: str | None = None


class RelationStep(_Contract):
    """One hop in a relation path, e.g. login --CALLS--> AuthService.authenticate."""

    source_symbol: str
    relation_type: RelationType
    target_symbol: str
    confidence: float = Field(ge=0.0, le=1.0)
    derivation: Derivation


class EvidenceItem(_Contract):
    """A single piece of verified evidence (Blueprint §10.7 / §7.6).

    Every important claim must be backed by one or more EvidenceItems whose file,
    lines, symbol identity, and snapshot are validated before display
    (CLAUDE.md §2.2 evidence-before-explanation).
    """

    id: str
    snapshot_id: str
    kind: EvidenceKind
    file_path: str
    symbol: str | None = None
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    content: str | None = None
    relation_path: list[str] | None = None
    retrieval_scores: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    derivation: Derivation


class Claim(_Contract):
    """A single asserted statement, each grounded in evidence IDs (Blueprint §7.6)."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1)


class Finding(_Contract):
    """A deterministic-or-heuristic finding (Blueprint §10.9).

    Invariant (CLAUDE.md §Phase 9): every finding carries deterministic evidence
    OR an explicit heuristic derivation label. `deterministic` records which.
    """

    id: str
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    deterministic: bool
    derivation: Derivation
    rule_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class QueryResponse(_Contract):
    """The canonical response contract (Blueprint §7.6).

    Returned (in JSON form) by every query surface. `answer` is either a
    deterministic template or an evidence-grounded model draft; either way every
    claim is validated against `evidence` before this leaves the system.
    """

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    intent: IntentType | None = None
    scope: Scope
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
