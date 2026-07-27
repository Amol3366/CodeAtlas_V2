"""Domain types for change assurance.

These are intentionally smaller than the public contract models in
:mod:`codeatlas.contracts`: they describe what the analysis engine operates on,
not what adapters render. The contract models add validation, envelope fields,
and serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from codeatlas.contracts import ChangeKind, FileChangeKind, SymbolKind
from codeatlas.domain.repository import FileClassification


@dataclass(frozen=True)
class StateFile:
    """One file in one side of a change.

    A :class:`StateView` exposes these so the engine can diff paths and content
    hashes without reading every byte up front. The content reader lives on the
    view, keeping the file descriptor lifecycle explicit.
    """

    relative_path: str
    language: str
    classification: FileClassification
    content_hash: str
    size_bytes: int
    line_count: int


@dataclass(frozen=True)
class FileChange:
    """One file-level difference between a base state and a target state."""

    path: str
    kind: FileChangeKind
    base_path: str | None = None
    content_hash_changed: bool = False


ChangeSide = Literal["base", "target"]


class SignatureChangeClass(StrEnum):
    """How a symbol's signature changed, independent of its body."""

    NONE = "none"
    ONLY_OPTIONAL_PARAMETERS_ADDED = "only_optional_parameters_added"
    OTHER = "other"


class BodyChangeClass(StrEnum):
    """What kind of statement-level change occurred in a modified body."""

    NONE = "none"
    RETURN_VALUE_CHANGED = "return_value_changed"
    ERROR_BEHAVIOR_CHANGED = "error_behavior_changed"
    STATE_INITIALIZATION_CHANGED = "state_initialization_changed"
    PUBLIC_BEHAVIOR_CHANGED = "public_behavior_changed"
    PUBLIC_CONTRACT_CHANGED = "public_contract_changed"


@dataclass(frozen=True)
class SymbolChange:
    """One symbol-level difference between a base state and a target state.

    A moved symbol carries both sides' file paths. A modified symbol carries
    target-side line ranges and, when the symbol moved, the base file path.
    """

    qualified_name: str
    symbol_kind: SymbolKind
    change_kind: ChangeKind
    file_path: str
    base_file_path: str | None = None
    base_start_line: int | None = None
    base_end_line: int | None = None
    target_start_line: int | None = None
    target_end_line: int | None = None
    signature_change_class: SignatureChangeClass = SignatureChangeClass.NONE
    public: bool = False
    body_change_class: BodyChangeClass = BodyChangeClass.NONE
    # Target-side citation override: the precise span proving the change (the
    # modified statement slice, or an import binding through its reference).
    # None means findings cite the whole symbol.
    evidence_start_line: int | None = None
    evidence_end_line: int | None = None
