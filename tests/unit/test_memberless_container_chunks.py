"""A container with no member symbols carries its body.

A class chunk is deliberately an outline: it names its members instead of
repeating their bodies, because each member is chunked separately and repeating
them would index the same bytes twice.

An enum has no member *symbols*. Its values are assignments, not methods, so
nothing extracts them and nothing else chunks them. The outline rule therefore
reduced an enum to one line:

    SYMBOL: OrderStatus
    TYPE: CLASS
    PARENT: src.orders.models
    LINES: 6-12
    CODE:
    class OrderStatus(Enum):

`DRAFT`, `PLACED`, `SHIPPED`, `CANCELLED` and the docstring "Where an order sits
in its lifecycle" were absent from the index entirely — so s013, "What stages
can an order move through?", could not retrieve the symbol that answers it
literally. Neither the lexical nor the semantic channel found `OrderStatus`;
both reached it only through the containing file chunk.

The rule: a container with no members is not a container. It is a leaf, and
leaves carry their code.
"""

from __future__ import annotations

from codeatlas.chunking.chunker import CHUNKER_VERSION, ChunkRequest, CodeChunker
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.ids import file_id
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest

ENUM_SOURCE = (
    b'"""The nouns of the ordering domain."""\n'
    b"\n"
    b"from enum import Enum\n"
    b"\n"
    b"\n"
    b"class OrderStatus(Enum):\n"
    b'    """Where an order sits in its lifecycle."""\n'
    b"\n"
    b'    DRAFT = "draft"\n'
    b'    PLACED = "placed"\n'
    b'    SHIPPED = "shipped"\n'
    b'    CANCELLED = "cancelled"\n'
)

CLASS_WITH_MEMBERS = (
    b"class Money:\n"
    b'    """An amount in minor units."""\n'
    b"\n"
    b"    def is_zero(self) -> bool:\n"
    b"        return self.minor_units == 0\n"
)


def _chunk(content: bytes, relative_path: str) -> tuple[LogicalChunk, ...]:
    """Parse and chunk one file.

    Deliberately a local copy rather than an import from
    `test_code_chunking`: importing a private helper across test modules makes
    the same file resolvable under two module names, which mypy rejects
    outright.
    """
    identifier = file_id("repo_1", relative_path)
    parsed = PythonParser().parse(
        ParseRequest(
            repository_id="repo_1",
            snapshot_id="snap_1",
            file_id=identifier,
            relative_path=relative_path,
            language="python",
            content=content,
        )
    )
    record = FileRecord(
        file_id=identifier,
        relative_path=relative_path,
        display_path=relative_path,
        content_hash="hash",
        size_bytes=len(content),
        line_count=content.decode("utf-8").count("\n"),
        language="python",
        classification=FileClassification.SOURCE_CODE,
    )
    return CodeChunker().chunk(
        ChunkRequest(
            repository_id="repo_1",
            file=record,
            content=content,
            symbols=parsed.symbols,
        )
    )


def _text(source: bytes, name: str, path: str = "src/orders/models.py") -> str:
    chunks = _chunk(source, path)
    return next(
        chunk.retrieval_text
        for chunk in chunks
        if chunk.qualified_name == name and chunk.role is not ChunkRole.FILE_SUMMARY
    )


def test_an_enum_chunk_carries_its_values() -> None:
    """The literal answer to "what stages can an order move through"."""
    text = _text(ENUM_SOURCE, "OrderStatus")

    for value in ("DRAFT", "PLACED", "SHIPPED", "CANCELLED"):
        assert value in text, f"{value} is not retrievable"


def test_an_enum_chunk_carries_its_docstring() -> None:
    """Free with the body, and the strongest semantic signal the class has.

    `SymbolRecord` has no docstring field and every `build_symbol_retrieval_text`
    call site passes `docstring=None`, so the builder's `DOCSTRING:` line is
    unreachable today. Carrying the body picks the docstring up anyway, which is
    why wiring extraction was not needed for this fix.
    """
    assert "Where an order sits in its lifecycle" in _text(ENUM_SOURCE, "OrderStatus")


def test_a_class_with_members_still_carries_only_its_outline() -> None:
    """The guard. Without it this widens into "every class repeats its members".

    `Money.is_zero` is chunked separately, so repeating its body inside the
    class chunk would index the same bytes twice and make the container match
    every query its members match.
    """
    text = _text(CLASS_WITH_MEMBERS, "Money")

    assert "Money.is_zero" in text
    assert "return self.minor_units == 0" not in text


def test_the_memberless_container_is_still_one_chunk_at_its_own_lines() -> None:
    """Carrying the body must not change what the chunk claims to be."""
    chunks = _chunk(ENUM_SOURCE, "src/orders/models.py")
    matching = [
        chunk
        for chunk in chunks
        if chunk.qualified_name == "OrderStatus"
        and chunk.role is ChunkRole.SYMBOL
    ]

    assert len(matching) == 1
    chunk: LogicalChunk = matching[0]
    assert (chunk.start_line, chunk.end_line) == (6, 12)
    assert chunk.symbol_id is not None


def test_the_chunker_version_moved() -> None:
    """Chunk text changed, so existing snapshots are stale and must re-index.

    `indexing.py` refuses a stale chunker version rather than mixing two
    chunking rules in one snapshot. Pinning the constant here makes the cost
    explicit rather than leaving it to be discovered on someone's next index.
    """
    assert CHUNKER_VERSION == "1.1.0"
