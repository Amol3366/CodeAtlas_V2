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
import re

from codeatlas.domain.errors import PathSafetyError

_FIELD_SEPARATOR = "\x1f"
_DIGEST_LENGTH = 32

# A namespace ID becomes a directory name under the vectors root, and one of
# its inputs is a model ID a user types into settings. Allowing only this set
# means no separator, no traversal, no drive letter, no control character, and
# no bidirectional-override character can reach a path join.
_NAMESPACE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Model IDs are conventionally `org/name` — `sentence-transformers/all-MiniLM-L6-v2`
# is the one this product pins. So a slash is legitimate and cannot simply be
# banned; each side of it is validated as its own token instead, which keeps
# `..`, a backslash, a drive letter, and a control character out while letting
# a real model ID through.
_MAX_MODEL_ID_LENGTH = 96


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
    resolver_version: str = "",
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
        resolver_version,
    )
    return f"snap_{digest}"


def relation_id(
    source_symbol_id_value: str,
    kind: str,
    target_hint: str,
    start_line: int,
    part: int = 0,
) -> str:
    """Identify one relation by the call site that produced it.

    The ID is stable across snapshots for an unchanged call site, which is what
    makes relation reuse observable and what will let change analysis say "this
    edge is new" rather than "these two edge sets differ somewhere".

    ``part`` separates two otherwise identical references on one line, as in
    ``f(f(x))``; without it the second occurrence would collide with the first
    and one real edge would be silently lost.
    """
    digest = stable_hash(
        source_symbol_id_value,
        kind,
        target_hint,
        str(start_line),
        str(part),
    )
    return f"rel_{digest}"


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


def embedding_key(
    content_hash: str,
    model_id: str,
    dimensions: int,
    normalization_version: str,
) -> str:
    """Identify one embedding of one piece of content under one model.

    Content-addressed on purpose: an unchanged chunk keeps its key across
    snapshots and branches, so a normal edit embeds only what changed rather
    than the corpus (blueprint 8.21). The model, dimensions, and normalization
    participate because vectors from different models must never share a
    similarity space (blueprint 4.7.6) — an identity that ignored them would
    let one model's vector answer for another's.
    """
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    digest = stable_hash(
        content_hash, model_id, str(dimensions), normalization_version
    )
    return f"emb_{digest}"


def embedding_namespace_id(
    model_id: str,
    dimensions: int,
    normalization_version: str,
) -> str:
    """Name one similarity space.

    Unlike every other identity here this is a readable slug rather than a
    digest, because it names a directory an operator will read while deciding
    whether a migration is safe to cut over.

    That readability is exactly why the inputs are validated: a model ID can
    arrive from settings, and settings are untrusted input. Nothing dangerous
    is sanitised into something acceptable — a traversal segment, a backslash,
    a drive letter, or a control character is rejected outright, because
    quietly rewriting an attack into a plausible name hides that it happened.

    The one transformation that *is* applied is the conventional ``org/name``
    separator: a slash becomes ``__``. A real model ID contains one — the
    pinned default is ``sentence-transformers/all-MiniLM-L6-v2`` — so banning
    it would leave the shipped provider unable to name its own namespace. A
    short digest of the exact inputs is appended so that mapping can never let
    two model IDs share a namespace: vectors from different models in one
    similarity space is blueprint 4.7.6's named error, and it is invisible when
    it happens.
    """
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    model = _model_slug(model_id)
    normalization = _namespace_token(
        normalization_version, field="normalization_version"
    )
    digest = stable_hash(model_id, str(dimensions), normalization_version)[:6]
    return f"{model}_{dimensions}d_{normalization}_{digest}"


def embedding_migration_id(
    repository_id_value: str,
    source_namespace_id: str,
    target_namespace_id: str,
) -> str:
    """Identify one requested namespace migration for one repository.

    Deterministic so retrying a start request for the same source and target
    resumes the same migration record rather than creating duplicates.
    """
    digest = stable_hash(
        repository_id_value, source_namespace_id, target_namespace_id
    )
    return f"mig_{digest}"


def _model_slug(model_id: str) -> str:
    """Validate a model ID and render it as a single path-safe segment."""
    value = model_id.strip().casefold()
    if not value or len(value) > _MAX_MODEL_ID_LENGTH:
        raise PathSafetyError(
            "A model identifier is missing or too long.",
            details={"field": "model_id"},
        )
    segments = value.split("/")
    for segment in segments:
        # `.` and `..` are already excluded by the token pattern, which
        # requires a leading letter or digit. Named here anyway, because they
        # are the reason this validation exists at all.
        if segment in {".", ".."} or not _NAMESPACE_TOKEN.match(segment):
            raise PathSafetyError(
                "A model identifier must be a name, optionally `org/name`.",
                details={"field": "model_id"},
            )
    return "__".join(segments)


def _namespace_token(value: str, *, field: str) -> str:
    token = value.strip().casefold()
    if not _NAMESPACE_TOKEN.match(token):
        raise PathSafetyError(
            "A vector namespace name must be a simple identifier.",
            details={"field": field},
        )
    return token


def validate_namespace_id(namespace_id: str) -> str:
    """Reject a namespace ID that could not safely become a directory name.

    Defence in depth. Identity construction already validates its inputs, but
    a namespace ID can also arrive from a stored row or a request body, and
    every path that reaches a filesystem join must be checked at that join
    rather than trusting where the string came from.
    """
    if not namespace_id or len(namespace_id) > 128:
        raise PathSafetyError("A vector namespace name is missing or too long.")
    if not _NAMESPACE_TOKEN.match(namespace_id):
        raise PathSafetyError("A vector namespace name must be a simple identifier.")
    return namespace_id
