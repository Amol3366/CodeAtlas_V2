"""Stable logical and version identities.

Logical identity answers "which thing is this" and survives edits. Version
identity answers "which exact content and logic produced this" and changes when
either changes. Keeping them separate is what allows unchanged work to be reused
across snapshots while still forcing recomputation when content or parser logic
moves.

Every identity is derived, never generated randomly, so re-running the same
inputs is idempotent.
"""

from __future__ import annotations

import hashlib

_FIELD_SEPARATOR = "\x1f"
_DIGEST_LENGTH = 32


def stable_hash(*parts: str) -> str:
    """Return a deterministic 32-character hex digest over the given fields.

    Fields are joined with a unit separator so that ``("ab", "")`` and
    ``("a", "b")`` cannot collide.
    """
    joined = _FIELD_SEPARATOR.join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]


def repository_id(canonical_root: str) -> str:
    """Identify a repository by its canonical root.

    The root is case-folded because Windows treats ``C:\\Repos\\Demo`` and
    ``c:\\repos\\demo`` as the same directory; registering both must not create
    two repositories.
    """
    return f"repo_{stable_hash(canonical_root.casefold())}"


def file_id(repository_id_value: str, relative_path: str) -> str:
    """Identify a file logically, independent of its content."""
    return f"file_{stable_hash(repository_id_value, relative_path)}"


def symbol_id(
    repository_id_value: str,
    relative_path: str,
    qualified_name: str,
    kind: str,
) -> str:
    """Identify a symbol logically. Editing its body does not change this."""
    digest = stable_hash(repository_id_value, relative_path, qualified_name, kind)
    return f"sym_{digest}"


def symbol_version_id(
    symbol_id_value: str,
    content_hash: str,
    parser_bundle_version: str,
) -> str:
    """Identify one parsed version of a symbol's content."""
    return f"symv_{stable_hash(symbol_id_value, content_hash, parser_bundle_version)}"


def logical_chunk_id(
    repository_id_value: str,
    relative_path: str,
    qualified_name: str,
    chunk_role: str,
) -> str:
    """Identify a chunk logically. Editing its content does not change this.

    The role is included because a file summary and a symbol chunk can share a
    qualified name and a location without being the same chunk.
    """
    digest = stable_hash(
        repository_id_value, relative_path, qualified_name, chunk_role
    )
    return f"chunk_{digest}"


def chunk_version_id(
    logical_chunk_id_value: str,
    content_hash: str,
    parser_bundle_version: str,
    chunker_version: str,
) -> str:
    """Identify one chunked version of a chunk's content.

    The chunker version participates so that changing how chunks are cut
    invalidates every stored chunk, which is the intended way to force a
    re-chunk rather than leaving mixed-vintage rows in the database.
    """
    digest = stable_hash(
        logical_chunk_id_value,
        content_hash,
        parser_bundle_version,
        chunker_version,
    )
    return f"chunkv_{digest}"


def snapshot_id(
    repository_id_value: str,
    working_tree_fingerprint: str,
    parser_bundle_version: str,
    index_version: str,
    chunker_version: str = "",
) -> str:
    """Identify a snapshot by the inputs that determine its content.

    Re-indexing an unchanged tree with unchanged logic yields the same snapshot
    ID, which is what makes indexing idempotent.
    """
    digest = stable_hash(
        repository_id_value,
        working_tree_fingerprint,
        parser_bundle_version,
        index_version,
        chunker_version,
    )
    return f"snap_{digest}"


def evidence_id(
    snapshot_id_value: str,
    file_id_value: str,
    start_line: int,
    end_line: int,
) -> str:
    """Identify one citable region of one file inside one snapshot."""
    digest = stable_hash(
        snapshot_id_value,
        file_id_value,
        str(start_line),
        str(end_line),
    )
    return f"ev_{digest}"
