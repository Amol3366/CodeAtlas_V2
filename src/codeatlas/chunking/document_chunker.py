"""Markdown document chunker (Blueprint §4.6).

One DOCUMENT_SECTION chunk per heading, spanning from the heading to just before
the next heading. Preserves heading ancestry, keeps code blocks and tables with
their explanatory text (contiguous line range), extracts references and
normative language, and classifies ADR sections. Exact source lines are kept for
citation.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from codeatlas.chunking.cache import ChunkArtifactCache
from codeatlas.chunking.contracts import Chunk, build_chunk
from codeatlas.chunking.references import (
    classify_adr_section,
    extract_normative,
    extract_references,
    is_adr_document,
)
from codeatlas.domain.enums import ChunkRole, Language

DOC_PARSER_VERSION = "markdown-0.1.0"
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


class MarkdownChunker:
    def chunk(
        self,
        source: str,
        repository_id: str,
        normalized_path: str,
        *,
        cache: ChunkArtifactCache | None = None,
    ) -> list[Chunk]:
        raw_lines = source.splitlines()
        keep_lines = source.splitlines(keepends=True)
        headings = [
            (index + 1, len(m.group(1)), m.group(2).strip())
            for index, line in enumerate(raw_lines)
            if (m := _HEADING.match(line))
        ]
        if not headings:
            return [self._whole_document(source, repository_id, normalized_path, cache)]

        adr = is_adr_document(normalized_path, headings[0][2])
        chunks: list[Chunk] = []
        ancestry: list[tuple[int, str]] = []
        for position, (line_no, level, text) in enumerate(headings):
            end = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(keep_lines)
            raw = "".join(keep_lines[line_no - 1 : end])
            while ancestry and ancestry[-1][0] >= level:
                ancestry.pop()
            ancestor_path = [t for _, t in ancestry]
            metadata = [
                ("level", str(level)),
                ("ancestry", " > ".join(ancestor_path)),
            ]
            if adr and (section := classify_adr_section(text)) is not None:
                metadata.append(("adr_section", section))
            normative = extract_normative(raw)
            if normative:
                metadata.append(("normative", ", ".join(normative)))
            chunks.append(
                build_chunk(
                    repository_id=repository_id,
                    normalized_path=normalized_path,
                    qualified_name=text,
                    chunk_role=ChunkRole.DOCUMENT_SECTION,
                    parser_version=DOC_PARSER_VERSION,
                    start_line=line_no,
                    end_line=end,
                    raw_content=raw,
                    retrieval_content=_doc_header(normalized_path, ancestor_path, text) + raw,
                    language=Language.MARKDOWN,
                    references=extract_references(raw),
                    metadata=metadata,
                    cache=cache,
                )
            )
            ancestry.append((level, text))
        return chunks

    def _whole_document(
        self,
        source: str,
        repository_id: str,
        normalized_path: str,
        cache: ChunkArtifactCache | None,
    ) -> Chunk:
        title = PurePosixPath(normalized_path).stem
        line_count = max(1, len(source.splitlines()))
        return build_chunk(
            repository_id=repository_id,
            normalized_path=normalized_path,
            qualified_name=title,
            chunk_role=ChunkRole.DOCUMENT_SECTION,
            parser_version=DOC_PARSER_VERSION,
            start_line=1,
            end_line=line_count,
            raw_content=source,
            retrieval_content=_doc_header(normalized_path, [], title) + source,
            language=Language.MARKDOWN,
            references=extract_references(source),
            cache=cache,
        )


def _doc_header(path: str, ancestry: list[str], heading: str) -> str:
    header = [f"PATH: {path}", "TYPE: document_section", f"HEADING: {heading}"]
    if ancestry:
        header.append(f"SECTION: {' > '.join(ancestry)} > {heading}")
    return "\n".join(header) + "\n\nCONTENT:\n"
