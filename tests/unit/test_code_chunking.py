"""Syntax-aware code chunking.

Chunk boundaries must follow the code's own structure. A chunk that begins or
ends mid-definition produces evidence a reader cannot trust, so every assertion
here is about boundaries, exact line mapping, and identity stability rather than
about how the retrieval text happens to read.
"""

from __future__ import annotations

from itertools import pairwise

from codeatlas.chunking.chunker import (
    HARD_MAX_CHARACTERS,
    ChunkRequest,
    CodeChunker,
)
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.ids import file_id
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.parsing.python_parser import PythonParser
from codeatlas.parsing.registry import ParseRequest

SERVICE_SOURCE = (
    b"from .idempotency import IdempotencyStore\n"
    b"\n"
    b"class PaymentService:\n"
    b"    def __init__(self, store: IdempotencyStore) -> None:\n"
    b"        self.store = store\n"
    b"\n"
    b"    def capture(self, key: str) -> str:\n"
    b"        return self.store.claim(key)\n"
)


def _chunk(content: bytes, relative_path: str) -> tuple[LogicalChunk, ...]:
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


def _by_name(chunks: tuple[LogicalChunk, ...]) -> dict[str, LogicalChunk]:
    return {
        chunk.qualified_name: chunk
        for chunk in chunks
        if chunk.role is not ChunkRole.FILE_SUMMARY
    }


def test_each_symbol_produces_one_chunk_with_exact_lines() -> None:
    by_name = _by_name(_chunk(SERVICE_SOURCE, "src/payments/service.py"))

    capture = by_name["PaymentService.capture"]
    assert capture.role is ChunkRole.SYMBOL
    assert (capture.start_line, capture.end_line) == (7, 8)
    assert by_name["PaymentService.__init__"].start_line == 4
    assert by_name["PaymentService"].start_line == 3


def test_a_file_summary_chunk_is_emitted_with_deterministic_metadata() -> None:
    chunks = _chunk(SERVICE_SOURCE, "src/payments/service.py")
    summary = next(item for item in chunks if item.role is ChunkRole.FILE_SUMMARY)

    assert "src/payments/service.py" in summary.retrieval_text
    assert "PaymentService" in summary.retrieval_text
    assert summary.symbol_id is None


def test_a_container_chunk_names_its_members_without_their_bodies() -> None:
    by_name = _by_name(_chunk(SERVICE_SOURCE, "src/payments/service.py"))

    container = by_name["PaymentService"]
    assert "PaymentService.capture" in container.retrieval_text
    assert "return self.store.claim(key)" not in container.retrieval_text


def test_retrieval_text_carries_the_evidence_header() -> None:
    by_name = _by_name(_chunk(SERVICE_SOURCE, "src/payments/service.py"))

    text = by_name["PaymentService.capture"].retrieval_text
    for field in ("PATH:", "LANGUAGE:", "SYMBOL:", "TYPE:", "LINES:", "CODE:"):
        assert field in text
    assert "return self.store.claim(key)" in text


def test_chunking_is_deterministic() -> None:
    first = _chunk(SERVICE_SOURCE, "src/payments/service.py")
    second = _chunk(SERVICE_SOURCE, "src/payments/service.py")
    assert [item.chunk_version_id for item in first] == [
        item.chunk_version_id for item in second
    ]


def test_editing_one_symbol_changes_only_that_chunk_version() -> None:
    before = {
        item.qualified_name: item
        for item in _chunk(SERVICE_SOURCE, "src/payments/service.py")
    }
    edited = SERVICE_SOURCE.replace(
        b"return self.store.claim(key)", b"return self.store.claim(key.strip())"
    )
    after = {
        item.qualified_name: item
        for item in _chunk(edited, "src/payments/service.py")
    }

    changed = {
        name
        for name, item in before.items()
        if item.chunk_version_id != after[name].chunk_version_id
    }
    assert changed == {"PaymentService.capture"}
    assert (
        before["PaymentService.capture"].logical_chunk_id
        == after["PaymentService.capture"].logical_chunk_id
    )


def test_adding_a_symbol_changes_the_container_and_summary() -> None:
    before = {
        item.qualified_name: item
        for item in _chunk(SERVICE_SOURCE, "src/payments/service.py")
    }
    extended = SERVICE_SOURCE + (
        b"\n    def refund(self, key: str) -> str:\n        return key\n"
    )
    after = {
        item.qualified_name: item
        for item in _chunk(extended, "src/payments/service.py")
    }

    assert "PaymentService.refund" in after
    assert (
        before["PaymentService"].chunk_version_id
        != after["PaymentService"].chunk_version_id
    )
    assert (
        before["src/payments/service.py"].chunk_version_id
        != after["src/payments/service.py"].chunk_version_id
    )
    assert (
        before["PaymentService.capture"].chunk_version_id
        == after["PaymentService.capture"].chunk_version_id
    )


def _huge_source() -> bytes:
    body = "\n".join(f"    value_{index} = {index}" for index in range(1200))
    return f"def huge() -> None:\n{body}\n".encode()


def test_oversized_symbol_splits_at_statement_boundaries() -> None:
    source = _huge_source()
    parts = [
        item
        for item in _chunk(source, "src/huge.py")
        if item.role is ChunkRole.SYMBOL_PART
    ]

    assert len(parts) > 1
    assert {item.part_count for item in parts} == {len(parts)}
    assert [item.part_index for item in parts] == list(range(len(parts)))
    assert all(len(item.retrieval_text) <= HARD_MAX_CHARACTERS for item in parts)
    assert parts[0].start_line == 1
    assert parts[-1].end_line == source.decode("utf-8").count("\n")


def test_split_parts_preserve_the_parent_signature_and_symbol_id() -> None:
    parts = [
        item
        for item in _chunk(_huge_source(), "src/huge.py")
        if item.role is ChunkRole.SYMBOL_PART
    ]

    assert len({item.symbol_id for item in parts}) == 1
    assert all("def huge" in item.retrieval_text for item in parts)
    assert all(item.qualified_name == "huge" for item in parts)
    assert len({item.logical_chunk_id for item in parts}) == 1
    assert len({item.chunk_version_id for item in parts}) == len(parts)


def test_split_parts_cover_the_whole_symbol_without_gaps() -> None:
    parts = [
        item
        for item in _chunk(_huge_source(), "src/huge.py")
        if item.role is ChunkRole.SYMBOL_PART
    ]

    for earlier, later in pairwise(parts):
        # Overlap is allowed and intended; a gap is not.
        assert later.start_line <= earlier.end_line + 1


def test_an_unsplit_symbol_is_never_labeled_a_part() -> None:
    chunks = _chunk(SERVICE_SOURCE, "src/payments/service.py")
    assert all(item.role is not ChunkRole.SYMBOL_PART for item in chunks)
    assert all(item.part_count == 1 for item in chunks)


def test_no_chunk_exceeds_the_hard_maximum() -> None:
    for source, path in (
        (SERVICE_SOURCE, "src/payments/service.py"),
        (_huge_source(), "src/huge.py"),
    ):
        assert all(
            len(item.retrieval_text) <= HARD_MAX_CHARACTERS
            for item in _chunk(source, path)
        )


def test_renaming_a_symbol_retires_its_logical_chunk() -> None:
    before = _chunk(SERVICE_SOURCE, "src/payments/service.py")
    renamed = SERVICE_SOURCE.replace(b"def capture", b"def capture_payment")
    after = _chunk(renamed, "src/payments/service.py")

    before_ids = {item.logical_chunk_id for item in before}
    after_ids = {item.logical_chunk_id for item in after}
    assert before_ids - after_ids


def test_a_one_line_definition_still_produces_a_chunk() -> None:
    by_name = _by_name(_chunk(b"def tiny() -> int: return 1\n", "src/tiny.py"))
    assert "tiny" in by_name


def test_every_chunk_line_range_is_inside_the_file() -> None:
    source = _huge_source()
    line_count = source.decode("utf-8").count("\n")
    for item in _chunk(source, "src/huge.py"):
        assert 1 <= item.start_line <= item.end_line <= line_count


def test_a_file_without_symbols_still_gets_a_summary() -> None:
    chunks = _chunk(b"# just a comment\n", "src/empty.py")
    roles = {item.role for item in chunks}
    assert ChunkRole.FILE_SUMMARY in roles


def test_an_empty_file_chunks_without_error() -> None:
    """An empty `__init__.py` still parses to a module symbol claiming line 1;
    the chunker must not read a line that does not exist."""
    chunks = _chunk(b"", "src/pkg/__init__.py")

    for chunk in chunks:
        assert chunk.end_line >= chunk.start_line >= 1
