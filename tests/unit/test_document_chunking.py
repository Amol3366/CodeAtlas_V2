"""Markdown and configuration structure, sections, and chunks."""

from __future__ import annotations

from codeatlas.chunking.chunker import ChunkRequest
from codeatlas.chunking.documents import DocumentChunker
from codeatlas.domain.chunks import ChunkRole, LogicalChunk
from codeatlas.domain.ids import file_id
from codeatlas.domain.repository import FileClassification, FileRecord
from codeatlas.parsing.document_parser import DocumentParser, DocumentSection
from codeatlas.parsing.registry import ParseRequest

MARKDOWN = (
    b"# Title\n\nIntro paragraph.\n\n"
    b"## Setup\n\nYou MUST install `uv`.\n\n"
    b"See src/payments/service.py for details.\n\n"
    b"### Windows\n\nRun the script.\n"
)


def _request(content: bytes, relative_path: str, language: str) -> ParseRequest:
    return ParseRequest(
        repository_id="repo_1",
        snapshot_id="snap_1",
        file_id=file_id("repo_1", relative_path),
        relative_path=relative_path,
        language=language,
        content=content,
    )


def _sections(
    content: bytes, relative_path: str, language: str = "markdown"
) -> tuple[DocumentSection, ...]:
    return DocumentParser().sections(_request(content, relative_path, language))


def _chunk_document(
    content: bytes, relative_path: str, language: str = "markdown"
) -> tuple[LogicalChunk, ...]:
    identifier = file_id("repo_1", relative_path)
    parsed = DocumentParser().parse(_request(content, relative_path, language))
    record = FileRecord(
        file_id=identifier,
        relative_path=relative_path,
        display_path=relative_path,
        content_hash="hash",
        size_bytes=len(content),
        line_count=max(content.decode("utf-8").count("\n"), 1),
        language=language,
        classification=(
            FileClassification.DOCUMENTATION
            if language == "markdown"
            else FileClassification.CONFIGURATION
        ),
    )
    return DocumentChunker().chunk(
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


def test_each_heading_becomes_a_chunk_with_its_ancestry() -> None:
    by_title = _by_name(_chunk_document(MARKDOWN, "docs/guide.md"))

    assert by_title["Windows"].heading_path == "Title > Setup > Windows"
    assert by_title["Setup"].role is ChunkRole.DOCUMENT_SECTION
    assert by_title["Setup"].heading_path == "Title > Setup"


def test_heading_line_ranges_are_exact() -> None:
    by_title = _by_name(_chunk_document(MARKDOWN, "docs/guide.md"))

    setup = by_title["Setup"]
    assert setup.start_line == 5
    assert setup.end_line == 10
    assert by_title["Windows"].start_line == 11


def test_normative_terms_and_referenced_paths_are_extracted() -> None:
    sections = _sections(MARKDOWN, "docs/guide.md")

    setup = next(item for item in sections if item.title == "Setup")
    assert "MUST" in setup.normative_terms
    assert "src/payments/service.py" in setup.referenced_paths


def test_a_traversal_path_is_not_recorded_as_a_reference() -> None:
    hostile = b"# T\n\nSee ../../etc/passwd and C:/Windows/system32 for details.\n"
    sections = _sections(hostile, "docs/guide.md")
    assert all(not item.referenced_paths for item in sections)


def test_markdown_symbols_are_emitted_for_exact_lookup() -> None:
    result = DocumentParser().parse(_request(MARKDOWN, "docs/guide.md", "markdown"))

    names = {symbol.qualified_name for symbol in result.symbols}
    assert {"Title", "Setup", "Windows"} <= names
    assert result.success is True


def test_a_fenced_code_block_stays_with_its_section() -> None:
    content = (
        b"# Title\n\n## Run\n\nUse this:\n\n```bash\n# Setup\nuv sync\n```\n\nDone.\n"
    )
    by_title = _by_name(_chunk_document(content, "docs/run.md"))

    assert "Setup" not in by_title  # a comment inside a fence is not a heading
    assert "uv sync" in by_title["Run"].retrieval_text


def test_toml_top_level_keys_become_chunks() -> None:
    chunks = _chunk_document(
        b'[tool.ruff]\nline-length = 88\n', "pyproject.toml", "toml"
    )
    assert any(item.role is ChunkRole.CONFIG_KEY for item in chunks)


def test_json_top_level_keys_become_chunks() -> None:
    content = b'{"name": "demo", "scripts": {"build": "vite build"}}\n'
    by_key = _by_name(_chunk_document(content, "package.json", "json"))

    # A nested key is its own chunk as well as being summarised into its
    # parent's retrieval text (ADR-0025): the summary makes the parent findable,
    # the chunk makes the leaf citable. Equality rather than a subset, so a
    # future change that quietly stops emitting one of these fails here.
    assert set(by_key) == {"name", "scripts", "scripts.build"}
    assert by_key["scripts"].role is ChunkRole.CONFIG_KEY
    assert by_key["scripts.build"].role is ChunkRole.CONFIG_KEY
    assert "scripts.build" in by_key["scripts"].retrieval_text


def test_yaml_top_level_keys_are_scanned_by_line() -> None:
    content = b"version: 1\nservices:\n  api:\n    image: demo\n"
    by_key = _by_name(_chunk_document(content, "config/app.yaml", "yaml"))

    assert set(by_key) == {
        "version",
        "services",
        "services.api",
        "services.api.image",
    }
    assert by_key["services"].start_line == 2
    assert by_key["services"].end_line == 4
    # Each leaf cites the line that writes it, not its parent's block.
    assert by_key["services.api"].start_line == 3
    assert by_key["services.api.image"].start_line == 4


def test_malformed_json_yields_a_diagnostic_not_an_exception() -> None:
    result = DocumentParser().parse(_request(b"{ broken", "config/app.json", "json"))

    assert result.success is False
    assert any(item.code == "PARSE_SYNTAX_ERROR" for item in result.diagnostics)
    assert result.symbols == ()


def test_malformed_toml_yields_a_diagnostic_not_an_exception() -> None:
    result = DocumentParser().parse(_request(b"[broken\n", "pyproject.toml", "toml"))

    assert result.success is False
    assert any(item.code == "PARSE_SYNTAX_ERROR" for item in result.diagnostics)


def test_ambiguous_yaml_is_reported_rather_than_guessed() -> None:
    result = DocumentParser().parse(
        _request(b"- one\n- two\n", "config/list.yaml", "yaml")
    )

    assert any(item.code == "PARSE_UNSUPPORTED" for item in result.diagnostics)
    assert result.symbols == ()


def test_document_chunking_is_deterministic() -> None:
    assert [
        item.chunk_version_id for item in _chunk_document(MARKDOWN, "docs/guide.md")
    ] == [item.chunk_version_id for item in _chunk_document(MARKDOWN, "docs/guide.md")]


def test_editing_one_section_changes_only_that_chunk_version() -> None:
    before = _by_name(_chunk_document(MARKDOWN, "docs/guide.md"))
    edited = MARKDOWN.replace(b"Run the script.", b"Run the other script.")
    after = _by_name(_chunk_document(edited, "docs/guide.md"))

    assert (
        before["Setup"].chunk_version_id == after["Setup"].chunk_version_id
    )
    assert (
        before["Windows"].chunk_version_id != after["Windows"].chunk_version_id
    )
    assert before["Windows"].logical_chunk_id == after["Windows"].logical_chunk_id


def test_a_document_without_headings_still_produces_a_chunk() -> None:
    chunks = _chunk_document(b"Just a paragraph.\n", "docs/plain.md")
    assert any(item.role is ChunkRole.FILE_SUMMARY for item in chunks)


def test_no_document_chunk_exceeds_the_hard_maximum() -> None:
    from codeatlas.chunking.chunker import HARD_MAX_CHARACTERS

    body = b"\n".join(b"Sentence number %d in a long section." % i for i in range(900))
    content = b"# Big\n\n" + body + b"\n"
    chunks = _chunk_document(content, "docs/big.md")

    assert all(len(item.retrieval_text) <= HARD_MAX_CHARACTERS for item in chunks)
    assert len([item for item in chunks if item.part_count > 1]) > 1


def test_every_document_chunk_line_range_is_inside_the_file() -> None:
    line_count = MARKDOWN.decode("utf-8").count("\n")
    for item in _chunk_document(MARKDOWN, "docs/guide.md"):
        assert 1 <= item.start_line <= item.end_line <= line_count
