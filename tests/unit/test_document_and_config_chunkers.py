"""Tests for the Markdown document and configuration chunkers (Blueprint §4.6)."""

from __future__ import annotations

from pathlib import Path

from codeatlas.chunking.configuration_chunker import ConfigurationChunker
from codeatlas.chunking.document_chunker import MarkdownChunker
from codeatlas.domain.enums import ChunkRole, Language

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _meta(chunk: object) -> dict[str, str]:
    return dict(chunk.metadata)  # type: ignore[attr-defined]


# --- Markdown -----------------------------------------------------------------


def test_markdown_sections_and_ancestry() -> None:
    source = (FIXTURES / "python_repo" / "docs" / "architecture.md").read_text(encoding="utf-8")
    chunks = MarkdownChunker().chunk(source, "repo_x", "docs/architecture.md")
    by_qn = {c.qualified_name: c for c in chunks}
    assert "Payments Service Architecture" in by_qn
    assert "Payment capture flow" in by_qn
    # A subsection records its parent heading in ancestry.
    assert _meta(by_qn["Payment capture flow"])["ancestry"] == "Payments Service Architecture"
    assert all(c.chunk_role is ChunkRole.DOCUMENT_SECTION for c in chunks)


def test_markdown_line_spans_are_contiguous_and_cover_document() -> None:
    source = (FIXTURES / "python_repo" / "docs" / "architecture.md").read_text(encoding="utf-8")
    chunks = sorted(
        MarkdownChunker().chunk(source, "repo_x", "docs/architecture.md"),
        key=lambda c: c.start_line,
    )
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert earlier.end_line + 1 == later.start_line


def test_adr_section_classification_and_normative() -> None:
    source = (FIXTURES / "python_repo" / "docs" / "adr" / "0001-idempotency.md").read_text(
        encoding="utf-8"
    )
    chunks = MarkdownChunker().chunk(source, "repo_x", "docs/adr/0001-idempotency.md")
    by_qn = {c.qualified_name: c for c in chunks}
    assert _meta(by_qn["Decision"])["adr_section"] == "Decision"
    assert "MUST" in _meta(by_qn["Decision"])["normative"]


def test_markdown_reference_extraction() -> None:
    source = (FIXTURES / "python_repo" / "docs" / "architecture.md").read_text(encoding="utf-8")
    config = next(
        c
        for c in MarkdownChunker().chunk(source, "repo_x", "docs/architecture.md")
        if c.qualified_name == "Configuration"
    )
    assert "DATABASE_URL" in config.references
    assert "src/config/settings.py" in config.references


def test_markdown_is_idempotent() -> None:
    source = (FIXTURES / "python_repo" / "docs" / "architecture.md").read_text(encoding="utf-8")
    first = MarkdownChunker().chunk(source, "repo_x", "docs/architecture.md")
    second = MarkdownChunker().chunk(source, "repo_x", "docs/architecture.md")
    assert [c.chunk_version_id for c in first] == [c.chunk_version_id for c in second]


# --- Configuration ------------------------------------------------------------


def test_yaml_config_keys() -> None:
    source = (FIXTURES / "mixed_repo" / "config" / "app.yaml").read_text(encoding="utf-8")
    chunks = ConfigurationChunker().chunk(source, Language.YAML, "repo_x", "config/app.yaml")
    by_qn = {c.qualified_name: c for c in chunks}
    assert "notification.channel" in by_qn
    assert "database_url" in by_qn
    assert by_qn["database_url"].start_line == 7
    assert all(c.chunk_role is ChunkRole.CONFIG_KEY for c in chunks)


def test_json_config_keys() -> None:
    source = (FIXTURES / "mixed_repo" / "config" / "app.json").read_text(encoding="utf-8")
    chunks = ConfigurationChunker().chunk(source, Language.JSON, "repo_x", "config/app.json")
    names = {c.qualified_name for c in chunks}
    assert "notification.channel" in names
    assert "notification.retry.maxAttempts" in names


def test_config_is_idempotent() -> None:
    source = (FIXTURES / "mixed_repo" / "config" / "app.yaml").read_text(encoding="utf-8")
    first = ConfigurationChunker().chunk(source, Language.YAML, "repo_x", "config/app.yaml")
    second = ConfigurationChunker().chunk(source, Language.YAML, "repo_x", "config/app.yaml")
    assert [c.chunk_version_id for c in first] == [c.chunk_version_id for c in second]


def test_malformed_config_yields_no_chunks() -> None:
    chunks = ConfigurationChunker().chunk("{ not: valid: json", Language.JSON, "r", "bad.json")
    assert chunks == []
