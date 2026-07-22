"""Tests for the syntax-aware code chunker (Blueprint §4.5, Phase 5)."""

from __future__ import annotations

from pathlib import Path

from codeatlas.chunking.cache import ChunkArtifactCache
from codeatlas.chunking.code_chunker import CodeChunker
from codeatlas.chunking.contracts import Chunk
from codeatlas.domain.enums import ChunkRole, Language
from codeatlas.parsing.contracts import ParseRequest
from codeatlas.parsing.python.parser import PythonParser

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "python_repo"
    / "src"
    / "services"
    / "payment_service.py"
)
_REL = "src/services/payment_service.py"


def _chunk(source: str, *, cache: ChunkArtifactCache | None = None) -> list[Chunk]:
    result = PythonParser().parse(ParseRequest("repo_x", _REL, Language.PYTHON, source.encode()))
    return CodeChunker().chunk(result, source, "repo_x", cache=cache)


def _by_key(chunks: list[Chunk]) -> dict[tuple[ChunkRole, str | None], Chunk]:
    return {(c.chunk_role, c.qualified_name): c for c in chunks}


def test_produces_file_summary_and_symbol_chunks() -> None:
    chunks = _chunk(FIXTURE.read_text(encoding="utf-8"))
    roles = {c.chunk_role for c in chunks}
    assert ChunkRole.FILE_SUMMARY in roles
    assert ChunkRole.SYMBOL_IMPLEMENTATION in roles
    assert ChunkRole.CALL_SITE in roles
    by_key = _by_key(chunks)
    assert (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.capture") in by_key
    assert (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.refund") in by_key


def test_class_chunk_excludes_method_bodies() -> None:
    chunks = _by_key(_chunk(FIXTURE.read_text(encoding="utf-8")))
    cls = chunks[(ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService")]
    capture = chunks[(ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.capture")]
    # The class chunk stops before its first method, so a method edit can't touch it.
    assert cls.end_line < capture.start_line


def test_retrieval_header_and_raw_separation() -> None:
    chunks = _by_key(_chunk(FIXTURE.read_text(encoding="utf-8")))
    capture = chunks[(ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.capture")]
    assert "PATH: src/services/payment_service.py" in capture.retrieval_content
    assert "SYMBOL: PaymentService.capture" in capture.retrieval_content
    assert "LINES: 20-33" in capture.retrieval_content
    assert "CODE:" in capture.retrieval_content
    # raw_content is the exact source, with no header.
    assert capture.raw_content.startswith("    def capture(")
    assert "PATH:" not in capture.raw_content


def test_chunking_is_idempotent() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    first = _chunk(source)
    second = _chunk(source)
    assert [c.logical_chunk_id for c in first] == [c.logical_chunk_id for c in second]
    assert [c.chunk_version_id for c in first] == [c.chunk_version_id for c in second]


def test_editing_one_function_leaves_unrelated_chunks_unchanged() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    modified = source.replace(
        "        transaction_id = self._gateway.charge",
        "        extra = 1\n        transaction_id = self._gateway.charge",
    )
    assert modified != source

    base = _by_key(_chunk(source))
    after = _by_key(_chunk(modified))

    # All logical chunk ids are unchanged (no symbols added/removed/renamed).
    assert set(base) == set(after)

    # The edited method's version changes...
    key = (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.capture")
    assert base[key].chunk_version_id != after[key].chunk_version_id

    # ...while unrelated chunks keep their versions even though lines shifted.
    for unrelated in [
        (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.refund"),
        (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentError"),
        (ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService"),
        (ChunkRole.FILE_SUMMARY, None),
    ]:
        assert base[unrelated].chunk_version_id == after[unrelated].chunk_version_id, unrelated
    # refund shifted down by one line — proof the version is line-independent.
    assert after[(ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.refund")].start_line == (
        base[(ChunkRole.SYMBOL_IMPLEMENTATION, "PaymentService.refund")].start_line + 1
    )


def test_cache_hit_on_unchanged_content() -> None:
    source = FIXTURE.read_text(encoding="utf-8")
    cache = ChunkArtifactCache()
    first = _chunk(source, cache=cache)
    # A miss per unique content hash (some chunks legitimately share content).
    assert cache.misses == len({c.content_hash for c in first})
    misses_after_first = cache.misses
    hits_after_first = cache.hits

    # Re-chunk identical content -> every chunk is a cache hit, no new misses.
    _chunk(source, cache=cache)
    assert cache.misses == misses_after_first
    assert cache.hits == hits_after_first + len(first)
