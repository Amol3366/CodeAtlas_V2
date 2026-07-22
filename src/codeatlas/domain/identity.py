"""Content-addressed identity functions (Blueprint §4.3.5, CLAUDE.md §5).

Pure, deterministic, framework-free. These drive all caching and incrementality:

    logical_chunk_id = stable_hash(repository_id, normalized_path, qualified_name, chunk_role)
    chunk_version_id = stable_hash(logical_chunk_id, content_hash, parser_version, chunker_version)
    embedding_key    = stable_hash(content_hash, model_id, dimensions, normalization_version)

``content_hash`` itself (SHA-256 of normalized content) is produced by the
scanner/parser, not here. ``stable_hash`` is length-prefixed so component
boundaries can never collide (``("a", "b") != ("ab", "")``), and it never uses
Python's salted ``hash()`` — identical inputs yield identical ids across
processes and runs (idempotent indexing, CLAUDE.md §2.9).
"""

from __future__ import annotations

import hashlib

from codeatlas.domain.enums import ChunkRole, RelationType, SymbolType

# Bumped only if the hashing scheme itself changes (would invalidate all ids).
IDENTITY_SCHEME_VERSION = "1"

_NULL = b"\x00"


def _encode(part: str | int | None) -> bytes:
    """Type-tagged encoding so None, "", 0, and "0" never alias each other."""
    if part is None:
        return b"N"
    if isinstance(part, bool):  # guard: bool is an int subclass
        return b"b" + (b"1" if part else b"0")
    if isinstance(part, int):
        return b"i" + str(part).encode("utf-8")
    return b"s" + part.encode("utf-8")


def stable_hash(*parts: str | int | None) -> str:
    """Deterministic SHA-256 over an ordered sequence of parts (length-prefixed)."""
    hasher = hashlib.sha256()
    hasher.update(b"v" + IDENTITY_SCHEME_VERSION.encode("utf-8") + _NULL)
    for part in parts:
        data = _encode(part)
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
    return hasher.hexdigest()


def logical_chunk_id(
    repository_id: str,
    normalized_path: str,
    qualified_name: str | None,
    chunk_role: ChunkRole | str,
) -> str:
    """Stable identity of a chunk's *logical slot* (independent of its content)."""
    role = chunk_role.value if isinstance(chunk_role, ChunkRole) else chunk_role
    return "lc_" + stable_hash(repository_id, normalized_path, qualified_name, role)


def chunk_version_id(
    logical_chunk_id: str,
    content_hash: str,
    parser_version: str,
    chunker_version: str,
) -> str:
    """Stable identity of a specific content version of a logical chunk."""
    return "cv_" + stable_hash(logical_chunk_id, content_hash, parser_version, chunker_version)


def embedding_key(
    content_hash: str,
    embedding_model_id: str,
    dimensions: int,
    normalization_version: str,
) -> str:
    """Stable identity of an embedding — changing the model creates a new key/namespace."""
    return "ek_" + stable_hash(content_hash, embedding_model_id, dimensions, normalization_version)


def symbol_id(
    repository_id: str,
    normalized_path: str,
    qualified_name: str,
    symbol_type: SymbolType | str,
) -> str:
    """Stable identity of a symbol.

    Independent of line numbers so moving a symbol within a file preserves its
    id (idempotence + future rename linking). Derived from repo + path +
    qualified name + type.
    """
    stype = symbol_type.value if isinstance(symbol_type, SymbolType) else symbol_type
    return "sym_" + stable_hash(repository_id, normalized_path, qualified_name, stype)


def relation_id(
    source_id: str,
    relation_type: RelationType | str,
    target_name: str,
    evidence_start_line: int,
) -> str:
    """Stable identity of a relation (source + type + target + evidence line)."""
    rtype = relation_type.value if isinstance(relation_type, RelationType) else relation_type
    return "rel_" + stable_hash(source_id, rtype, target_name, evidence_start_line)
