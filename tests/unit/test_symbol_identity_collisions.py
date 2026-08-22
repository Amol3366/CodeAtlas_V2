"""Two distinct symbols in one file must not share a ``symbol_id``.

``symbol_id`` is ``hash(repository_id, relative_path, qualified_name, kind)``
(``domain/ids.py``), so two symbols that legitimately share a file, a qualified
name and a kind collapse onto one id. ``symbols`` is keyed
``(snapshot_id, symbol_id)``, so the collision is not a bad answer -- it is
``sqlite3.IntegrityError: UNIQUE constraint failed`` inside ``_stage``, which
``cli/main.py`` turns into ``INTERNAL_ERROR`` and exit 6. **No snapshot is
produced at all**, so the repository cannot be indexed by any surface.

Found 2026-08-22 by indexing real repositories rather than fixtures, which is
the same way ADR-0041 through ADR-0045 and ADR-0064 were found. Measured:

  ==================  ======================================================
  google/gson (Java)  55 files, 264 excess symbols. ``Gson.fromJson`` x11,
                      ``Gson.toJson`` x8 -- the library's whole public API
  spf13/cobra (Go)    ``type key struct{}`` declared inside four different
                      test functions, all flattening to one ``key``
  gin-gonic/gin (Go)  3 files, 4 excess symbols
  ==================  ======================================================

**This is not specific to the query-backed tier.** ``python_parser.py:314`` and
``query_backed/engine.py:154`` build the id with the identical call, so the
defect is shared by both tiers and predates ADR-0065 by six phases. It has
stayed invisible because no fixture and no file in this repository uses the
constructs below -- a probe over ``src/codeatlas`` and ``apps/web/src`` finds
zero collisions, which is why every gate has passed while an eight-line Python
file using a plain property cannot be indexed:

    class Thing:
        @property
        def value(self) -> int: ...
        @value.setter
        def value(self, v: int) -> None: ...

**Six of seven languages are affected, and each for its own reason**, which is
why no single disambiguator fixes them all -- the ruling has to choose:

  * Python -- ``@property`` / ``@x.setter``, and plain redefinition
  * Java, Scala -- method overloads; the signature is what distinguishes them
  * Go -- function-local ``type`` declarations; the enclosing scope distinguishes
  * Rust -- one method name implemented for two traits (``Display::fmt`` and
    ``Debug::fmt``); neither signature nor lexical scope distinguishes those,
    only the trait does
  * TypeScript -- **not** affected; it is the passing control below, so this
    module cannot pass vacuously if the parser stops emitting symbols

An arity-based fix resolves Python, Java and Scala but not Rust or Go; a
scope-based fix resolves Go and Rust but not the overloads. Any fix changes
symbol identity and therefore needs a ``PARSER_BUNDLE_VERSION`` bump and a
reindex.

The failing cases are ``strict`` xfails carrying their diagnosis here, the
pattern ADR-0065 used for a declared limit awaiting a ruling (ADR-0066 and
ADR-0067 then closed both). Strict means a fix turns these red until the marks
come off, so the ruling cannot land silently.
"""

from __future__ import annotations

import pytest

from codeatlas.parsing.registry import ParseRequest, default_registry

_PROPERTY_AND_SETTER = b"""class Thing:
    @property
    def value(self) -> int:
        return self._v

    @value.setter
    def value(self, v: int) -> None:
        self._v = v
"""

_JAVA_OVERLOADS = b"""class Codec {
  void write(int value) {}
  void write(String value) {}
}
"""

_GO_FUNCTION_LOCAL_TYPES = b"""package m

func First() { type key struct{}; _ = key{} }
func Second() { type key struct{}; _ = key{} }
"""

_RUST_TWO_TRAIT_IMPLS = b"""struct S;

impl std::fmt::Display for S {
    fn fmt(&self) -> () {}
}

impl std::fmt::Debug for S {
    fn fmt(&self) -> () {}
}
"""

_SCALA_OVERLOADS = b"""class Codec {
  def write(value: Int): Unit = {}
  def write(value: String): Unit = {}
}
"""

# The control. TypeScript declares overloads as signatures over one
# implementation, so it has nothing to collide -- and a passing case here is
# what stops the whole module from going green on a parser that returns nothing.
_TS_OVERLOAD_SIGNATURES = b"""export function write(value: string): void;
export function write(value: number): void;
export function write(value: unknown): void {}
"""

_STRICT_XFAIL = pytest.mark.xfail(
    strict=True,
    reason="symbol_id omits any disambiguator for same-file, same-name, "
    "same-kind symbols; awaiting the ruling recorded in the Deferred Register",
)


@pytest.mark.parametrize(
    ("language", "relative_path", "source"),
    [
        pytest.param(
            "python",
            "thing.py",
            _PROPERTY_AND_SETTER,
            marks=_STRICT_XFAIL,
            id="python-property-and-setter",
        ),
        pytest.param(
            "java",
            "Codec.java",
            _JAVA_OVERLOADS,
            marks=_STRICT_XFAIL,
            id="java-method-overloads",
        ),
        pytest.param(
            "go",
            "local.go",
            _GO_FUNCTION_LOCAL_TYPES,
            marks=_STRICT_XFAIL,
            id="go-function-local-types",
        ),
        pytest.param(
            "rust",
            "s.rs",
            _RUST_TWO_TRAIT_IMPLS,
            marks=_STRICT_XFAIL,
            id="rust-two-trait-impls",
        ),
        pytest.param(
            "scala",
            "Codec.scala",
            _SCALA_OVERLOADS,
            marks=_STRICT_XFAIL,
            id="scala-method-overloads",
        ),
        pytest.param(
            "typescript",
            "codec.ts",
            _TS_OVERLOAD_SIGNATURES,
            id="typescript-overload-signatures-control",
        ),
    ],
)
def test_a_file_never_emits_two_symbols_with_one_id(
    language: str, relative_path: str, source: bytes
) -> None:
    """Every symbol a parser emits for one file carries a distinct id.

    Asserted on the ``symbol_id`` the parser itself stamps rather than on a
    recomputed hash, so the test fails for the reason indexing fails instead of
    for a reason a test helper invented.
    """
    parser = default_registry().parser_for(language)
    assert parser is not None, f"no parser registered for {language}"

    result = parser.parse(
        ParseRequest(
            repository_id="repo_test",
            snapshot_id="snap_test",
            file_id="file_test",
            relative_path=relative_path,
            language=language,
            content=source,
        )
    )

    assert result.symbols, "the parser emitted no symbols, so nothing was proven"

    ids = [symbol.symbol_id for symbol in result.symbols]
    duplicated = sorted(
        {
            symbol.qualified_name
            for symbol in result.symbols
            if ids.count(symbol.symbol_id) > 1
        }
    )
    assert not duplicated, (
        f"{language}: {len(ids) - len(set(ids))} symbol(s) share an id with "
        f"another symbol in the same file: {duplicated}. Indexing a repository "
        f"containing this file raises UNIQUE constraint failed on "
        f"(snapshot_id, symbol_id) and produces no snapshot."
    )
