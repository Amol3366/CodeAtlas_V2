"""LanceDB-backed vector storage.

Imported only through :func:`codeatlas.semantic.vector_store.build_lancedb_store`,
so nothing here loads on an installation without the extra.

The design constraint from ADR-0009 decision 3 is that this file holds *derived*
data. A row carries an embedding key, a content hash, and a vector; the file
path, the lines, and the snapshot it belongs to all stay in SQLite. Deleting the
vectors directory is therefore a recoverable act — the cost is re-embedding, not
lost truth — and there is no second copy of the repository outside the database
that governs it.

Base and delta are two physical tables per namespace (blueprint 4.7.5), so a
normal edit appends a few rows to a small table instead of rewriting a large
one.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codeatlas.domain.ids import validate_namespace_id
from codeatlas.semantic.vector_store import VectorMatch, VectorRecord

# LanceDB reports cosine *distance*; similarity is its complement. Converting
# here means callers compare scores the same way regardless of which store they
# were given, which is what lets the in-memory implementation stand in for this
# one in the evaluation harness.
_DISTANCE_METRIC = "cosine"


class LanceDBVectorStore:
    """Vectors on disk, one directory per store, two tables per namespace."""

    def __init__(self, directory: Path) -> None:
        import lancedb

        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._connection = lancedb.connect(str(directory))

    # --- writing ---------------------------------------------------------

    def upsert(self, namespace_id: str, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        validate_namespace_id(namespace_id)

        width = self._width(namespace_id)
        for record in records:
            if width is not None and len(record.vector) != width:
                raise ValueError(
                    "vector width does not match the namespace: "
                    f"{len(record.vector)} != {width}"
                )
            width = len(record.vector)

        table_name = self._table_name(namespace_id, "delta")
        rows = [
            {
                "embedding_key": record.embedding_key,
                "content_hash": record.content_hash,
                "vector": [float(value) for value in record.vector],
            }
            for record in records
        ]

        if table_name in self._table_names():
            table = self._connection.open_table(table_name)
            # Delete-then-add rather than append: re-embedding after a failed
            # run must replace a key, not leave two rows competing for the
            # caller's limited result slots with one of them stale.
            self._delete_keys(table, [record.embedding_key for record in records])
            table.add(rows)
        else:
            self._connection.create_table(table_name, data=rows)

    def compact(self, namespace_id: str) -> None:
        """Fold delta into base.

        Retrieval must not notice. The base table is only replaced once the
        merged rows are in hand, so an interruption leaves the previous base
        and the delta both intact and searchable — the same "validate before
        switching" rule the snapshot activation follows.
        """
        delta_name = self._table_name(namespace_id, "delta")
        if delta_name not in self._table_names():
            return

        delta_rows = self._connection.open_table(delta_name).to_arrow().to_pylist()
        if not delta_rows:
            self._connection.drop_table(delta_name)
            return

        base_name = self._table_name(namespace_id, "base")
        if base_name in self._table_names():
            base = self._connection.open_table(base_name)
            self._delete_keys(base, [row["embedding_key"] for row in delta_rows])
            base.add(delta_rows)
        else:
            self._connection.create_table(base_name, data=delta_rows)

        self._connection.drop_table(delta_name)

    def delete_namespace(self, namespace_id: str) -> None:
        for suffix in ("base", "delta"):
            name = self._table_name(namespace_id, suffix)
            if name in self._table_names():
                self._connection.drop_table(name)

    # --- reading ---------------------------------------------------------

    def search(
        self, namespace_id: str, query_vector: Sequence[float], *, limit: int
    ) -> tuple[VectorMatch, ...]:
        width = self._width(namespace_id)
        if width is None:
            return ()
        if len(query_vector) != width:
            raise ValueError(
                "query width does not match the namespace: "
                f"{len(query_vector)} != {width}"
            )

        query = [float(value) for value in query_vector]
        # Both tables are asked for the full limit and merged, because the
        # split between them is a storage decision: a delta holding the best
        # match must not lose it to a base that happened to fill the quota.
        matches: dict[str, VectorMatch] = {}
        for suffix in ("base", "delta"):
            for match in self._search_table(namespace_id, suffix, query, limit):
                # Delta is searched second and wins on a collision: it holds
                # the newer vector for content re-embedded while the old one is
                # still in base.
                matches[match.embedding_key] = match

        ordered = sorted(
            matches.values(), key=lambda match: (-match.score, match.embedding_key)
        )
        return tuple(ordered[:limit])

    def count(self, namespace_id: str) -> int:
        keys: set[str] = set()
        for suffix in ("base", "delta"):
            name = self._table_name(namespace_id, suffix)
            if name in self._table_names():
                rows = self._connection.open_table(name).to_arrow().to_pylist()
                keys.update(row["embedding_key"] for row in rows)
        return len(keys)

    def base_count(self, namespace_id: str) -> int:
        return self._table_count(namespace_id, "base")

    def delta_count(self, namespace_id: str) -> int:
        return self._table_count(namespace_id, "delta")

    # --- internals -------------------------------------------------------

    def _table_names(self) -> list[str]:
        """Every table in this store, across the pinned LanceDB range.

        `table_names` was renamed to `list_tables` inside the allowed
        `>=0.34,<0.36` window, so the older name warns on newer builds. The
        replacement is not a drop-in: it returns a paginated response object,
        not a list, so the pages are followed here. Treating it as a list
        yields an empty result and every lookup silently decides the table does
        not exist — which is how this first showed up.
        """
        lister = getattr(self._connection, "list_tables", None)
        if lister is None:  # pragma: no cover - older builds in the pinned range
            return [str(name) for name in self._connection.table_names()]

        names: list[str] = []
        page_token: str | None = None
        while True:
            response = lister(page_token=page_token)
            names.extend(str(name) for name in response.tables)
            page_token = getattr(response, "page_token", None)
            if not page_token:
                return names

    def _search_table(
        self, namespace_id: str, suffix: str, query: list[float], limit: int
    ) -> list[VectorMatch]:
        name = self._table_name(namespace_id, suffix)
        if name not in self._table_names():
            return []
        results = (
            self._connection.open_table(name)
            .search(query)
            .metric(_DISTANCE_METRIC)
            .limit(limit)
            .to_list()
        )
        return [
            VectorMatch(
                embedding_key=row["embedding_key"],
                content_hash=row["content_hash"],
                score=1.0 - float(row["_distance"]),
            )
            for row in results
        ]

    def _table_count(self, namespace_id: str, suffix: str) -> int:
        name = self._table_name(namespace_id, suffix)
        if name not in self._table_names():
            return 0
        return int(self._connection.open_table(name).count_rows())

    def _width(self, namespace_id: str) -> int | None:
        for suffix in ("delta", "base"):
            name = self._table_name(namespace_id, suffix)
            if name not in self._table_names():
                continue
            rows = self._connection.open_table(name).head(1).to_pylist()
            if rows:
                return len(rows[0]["vector"])
        return None

    @staticmethod
    def _delete_keys(table: Any, keys: Sequence[str]) -> None:
        if not keys:
            return
        # Keys are hex digests produced by `embedding_key`, so they cannot
        # contain a quote. The assertion is cheap and turns a would-be
        # injection into a crash rather than a silently mangled predicate.
        for key in keys:
            if "'" in key or '"' in key:
                raise ValueError("an embedding key may not contain a quote")
        quoted = ", ".join(f"'{key}'" for key in keys)
        table.delete(f"embedding_key IN ({quoted})")

    @staticmethod
    def _table_name(namespace_id: str, suffix: str) -> str:
        # Validated because it becomes a table name and, underneath, a
        # directory: the namespace ID's inputs include a model ID typed into
        # settings.
        return f"{validate_namespace_id(namespace_id)}__{suffix}"
