"""A repository containing every known collision construct still indexes.

``tests/unit/test_symbol_identity_collisions.py`` asserts at the **parser**
level -- that ``parser.parse()`` emits distinct ``symbol_id`` values. Every
defect ADR-0069 found *behind* the first one lived below that line:

* ``logical_chunk_id`` has the identical shape, so the failure moved to
  ``chunks`` the moment symbols stopped colliding;
* ``query_relations`` minted the **invented** owner ``module_{file_id}`` for a
  file defining nothing, and snapshot validation refused the dangling endpoint
  (``package-info.java`` is the common shape);
* ``relations.relation_id`` collided where Go and Rust attributed every path in
  a grouped import to the *declaration* rather than to the path.

None of those is visible to a parser-level assertion. The layer that matters is
"does a repository containing these files produce an **active snapshot**",
which is the layer a user meets: before ADR-0069 this raised
``sqlite3.IntegrityError`` inside ``_stage``, which the CLI turned into
``INTERNAL_ERROR`` and exit 6, with **no snapshot at all**.

The constructs are the ones measured on real repositories in ADR-0069 rather
than ones invented here, because the point of this file is to hold the corpus
to real code. Every fixture in this repository is a two-file toy containing
none of them, which is why seven phases of gates passed over a defect that made
indexing fail outright.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.application.container import build_services
from codeatlas.application.registration import RegisterRepositoryRequest
from codeatlas.domain.snapshot import SnapshotState
from codeatlas.storage.sqlite.connection import connect
from codeatlas.storage.sqlite.migrations import apply_migrations

_SOURCES: dict[str, str] = {
    # Python: a property and its setter share qualified name and kind. This is
    # the one that proves the defect predates ADR-0065 by six phases.
    "thing.py": (
        "class Thing:\n"
        "    @property\n"
        "    def value(self) -> int:\n"
        "        return self._v\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, v: int) -> None:\n"
        "        self._v = v\n"
    ),
    # Java: method overloads. gson collided in 55 files this way, including
    # Gson.fromJson x11 -- the library's whole public API.
    "Codec.java": (
        "package app;\n"
        "\n"
        "public class Codec {\n"
        "    public String encode(String s) { return s; }\n"
        "    public String encode(int i) { return String.valueOf(i); }\n"
        "}\n"
    ),
    # Java: a file that defines nothing **while stating an import**. Both
    # halves are load-bearing. This is what minted the invented owner id
    # `module_{file_id}` and made snapshot validation refuse the whole
    # snapshot. A `package-info.java` holding only `package app;` does NOT
    # reproduce it -- with no reference to attribute there is no dangling
    # endpoint -- which a mutation check caught here on 2026-08-31 after the
    # first version of this fixture was written that way.
    "package-info.java": "package app;\n\nimport java.util.List;\n",
    # Go: function-local type declarations, and a grouped import binding two
    # different paths to names that collided on relation_id in gin.
    "local.go": (
        "package app\n"
        "\n"
        "import (\n"
        '\tcrand "crypto/rand"\n'
        '\tmrand "math/rand"\n'
        ")\n"
        "\n"
        "func A() { type key struct{}; _ = key{}; _ = crand.Reader }\n"
        "\n"
        "func B() { type key struct{}; _ = key{}; _ = mrand.Int }\n"
    ),
    # Rust: one method name implemented for two traits. Neither signature nor
    # lexical scope distinguishes these -- only the trait does.
    "s.rs": (
        "use std::fmt::{self, Debug, Display};\n"
        "\n"
        "pub struct S;\n"
        "\n"
        "impl Display for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {\n"
        '        write!(f, "s")\n'
        "    }\n"
        "}\n"
        "\n"
        "impl Debug for S {\n"
        "    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {\n"
        '        write!(f, "S")\n'
        "    }\n"
        "}\n"
    ),
    # Scala: overloads plus a companion trait/object pair. scalaz collided in
    # 270 files, overwhelmingly on companions.
    "Codec.scala": (
        "package app\n"
        "\n"
        "trait Codec { def encode(s: String): String = s }\n"
        "\n"
        "object Codec { def encode(i: Int): String = i.toString }\n"
    ),
    # TypeScript: the passing control. It has its own disambiguator
    # (`_disambiguate_repeated_symbols`) and must keep working unchanged.
    "codec.ts": (
        "export function encode(s: string): string;\n"
        "export function encode(i: number): string;\n"
        "export function encode(v: string | number): string {\n"
        "  return String(v);\n"
        "}\n"
    ),
}


@pytest.fixture()
def colliding_repo(tmp_path: Path) -> Path:
    """A repository holding one file per collision construct."""
    root = tmp_path / "colliding"
    root.mkdir()
    for name, source in _SOURCES.items():
        (root / name).write_text(source, encoding="utf-8", newline="\n")
    return root


def test_a_repository_of_colliding_constructs_produces_an_active_snapshot(
    tmp_path: Path, colliding_repo: Path
) -> None:
    """Indexing succeeds and activates.

    Asserted on the snapshot state rather than on an absence of exceptions,
    because the failure mode being guarded produced a *staging* snapshot that
    never activated as well as one that raised.
    """
    with connect(tmp_path / "db.sqlite") as connection:
        apply_migrations(connection)
        services = build_services(connection)
        repository = services.registration.register(
            RegisterRepositoryRequest(path=str(colliding_repo))
        )

        result = services.indexing.index(repository.repository_id)

        assert result.snapshot.state is SnapshotState.ACTIVE, (
            f"indexing did not activate: state={result.snapshot.state}, "
            f"warnings={result.warnings}"
        )
        assert result.snapshot.file_count == len(_SOURCES), (
            f"expected all {len(_SOURCES)} construct files in the snapshot, "
            f"got {result.snapshot.file_count} -- a file silently skipped "
            f"would make this test pass while proving nothing"
        )
