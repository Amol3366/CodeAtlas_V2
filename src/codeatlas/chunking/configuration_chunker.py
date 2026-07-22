"""Configuration key chunker for JSON / YAML / TOML (Blueprint §4.6.1).

Produces one CONFIG_KEY chunk per leaf key, addressed by its dotted path
(e.g. ``notification.channel``, ``database_url``). Values are parsed with stdlib
/ pyyaml; the source line for each leaf is located heuristically so citations
point at the right line. Malformed config yields no chunks (a caller can record
a diagnostic) rather than raising.
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any

import yaml

from codeatlas.chunking.cache import ChunkArtifactCache
from codeatlas.chunking.contracts import Chunk, build_chunk
from codeatlas.domain.enums import ChunkRole, Language

CONFIG_PARSER_VERSION = "config-0.1.0"


class ConfigurationChunker:
    def chunk(
        self,
        source: str,
        language: Language,
        repository_id: str,
        normalized_path: str,
        *,
        cache: ChunkArtifactCache | None = None,
    ) -> list[Chunk]:
        data = _load(source, language)
        if not isinstance(data, dict):
            return []
        source_lines = source.splitlines()
        chunks: list[Chunk] = []
        for path_parts, value in _walk_leaves(data):
            dotted = ".".join(path_parts)
            line = _find_line(source_lines, path_parts[-1], language)
            raw = f"{dotted}: {_render_value(value)}"
            retrieval = (
                f"PATH: {normalized_path}\nTYPE: config_key\nKEY: {dotted}\n"
                f"LINES: {line}-{line}\n\nVALUE:\n{_render_value(value)}"
            )
            chunks.append(
                build_chunk(
                    repository_id=repository_id,
                    normalized_path=normalized_path,
                    qualified_name=dotted,
                    chunk_role=ChunkRole.CONFIG_KEY,
                    parser_version=CONFIG_PARSER_VERSION,
                    start_line=line,
                    end_line=line,
                    raw_content=raw,
                    retrieval_content=retrieval,
                    language=language,
                    references=(dotted,),
                    cache=cache,
                )
            )
        return chunks


def _load(source: str, language: Language) -> Any:
    try:
        if language is Language.JSON:
            return json.loads(source)
        if language is Language.YAML:
            return yaml.safe_load(source)
        if language is Language.TOML:
            return tomllib.loads(source)
    except (json.JSONDecodeError, yaml.YAMLError, tomllib.TOMLDecodeError, ValueError):
        return None
    return None


def _walk_leaves(
    data: dict[str, Any], prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    leaves: list[tuple[tuple[str, ...], Any]] = []
    for key, value in data.items():
        path = (*prefix, str(key))
        if isinstance(value, dict):
            leaves.extend(_walk_leaves(value, path))
        else:
            leaves.append((path, value))
    return leaves


def _render_value(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _find_line(source_lines: list[str], key: str, language: Language) -> int:
    if language is Language.JSON:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:')
    elif language is Language.TOML:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    else:  # YAML
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for index, line in enumerate(source_lines):
        if pattern.search(line):
            return index + 1
    return 1
