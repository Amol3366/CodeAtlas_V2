"""Configuration values consumed by the Phase 1 scanner.

Kept deliberately small and free of runtime YAML coupling: the scanner takes a
plain :class:`ScanConfig` and a :class:`LanguageIndex`, both of which have
in-code defaults that mirror ``config/default.yaml`` and ``config/languages.yaml``.
A YAML loader is provided for callers that want to honour on-disk overrides, but
tests and the core code path never require the config directory to be present.

Layering (CLAUDE.md §4): this module performs no scanning I/O itself; it only
resolves configuration. The language map here is the source of truth for
extension dispatch (the YAML file documents the same mapping).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from codeatlas.domain.enums import FileClassification, Language


@dataclass(frozen=True)
class ScanConfig:
    """Scanner behaviour (mirrors the ``scanning`` block of default.yaml).

    ``normalization_version`` participates in artifact identity downstream
    (CLAUDE.md §2.14); it is recorded on the manifest but never mixed into the
    content hash itself (the hash stays a pure SHA-256 of normalized content).
    """

    allow_unc_paths: bool = False
    follow_external_junctions: bool = False
    max_file_size_bytes: int = 2_000_000
    long_paths_enabled: bool = True
    normalization_version: str = "0.1.0"
    # User-configured ignore patterns (lowest precedence, applied after builtins).
    user_ignore_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class LanguageEntry:
    """The (language, base classification) a file extension dispatches to."""

    language: Language
    classification: FileClassification


@dataclass(frozen=True)
class LanguageIndex:
    """Extension -> :class:`LanguageEntry` lookup (case-insensitive)."""

    by_extension: dict[str, LanguageEntry] = field(default_factory=dict)
    # Globs that must never be auto-excluded (Blueprint §4.3.3 non-exclusion guarantee).
    never_exclude_globs: tuple[str, ...] = ()

    def lookup(self, extension: str) -> LanguageEntry | None:
        return self.by_extension.get(extension.lower())


# Source of truth for extension dispatch (mirrors config/languages.yaml).
_DEFAULT_LANGUAGE_SPECS: tuple[tuple[Language, FileClassification, tuple[str, ...]], ...] = (
    (Language.PYTHON, FileClassification.SOURCE_CODE, (".py", ".pyi")),
    (Language.TYPESCRIPT, FileClassification.SOURCE_CODE, (".ts", ".tsx")),
    (Language.JAVASCRIPT, FileClassification.SOURCE_CODE, (".js", ".jsx", ".mjs", ".cjs")),
    (Language.MARKDOWN, FileClassification.DOCUMENTATION, (".md", ".markdown")),
    (Language.JSON, FileClassification.CONFIGURATION, (".json",)),
    (Language.YAML, FileClassification.CONFIGURATION, (".yaml", ".yml")),
    (Language.TOML, FileClassification.CONFIGURATION, (".toml",)),
)

_DEFAULT_NEVER_EXCLUDE_GLOBS: tuple[str, ...] = (
    "**/*.lock",
    "**/uv.lock",
    "**/package-lock.json",
    "**/poetry.lock",
    "**/migrations/**",
    "**/openapi*.yaml",
    "**/openapi*.yml",
    "**/openapi*.json",
    "**/*.sql",
    "**/Dockerfile",
    "**/.github/workflows/**",
)


def default_language_index() -> LanguageIndex:
    """Build the in-code language index that mirrors ``config/languages.yaml``."""
    by_ext: dict[str, LanguageEntry] = {}
    for language, classification, extensions in _DEFAULT_LANGUAGE_SPECS:
        for ext in extensions:
            by_ext[ext.lower()] = LanguageEntry(language=language, classification=classification)
    return LanguageIndex(by_extension=by_ext, never_exclude_globs=_DEFAULT_NEVER_EXCLUDE_GLOBS)


def load_language_index(languages_yaml: Path) -> LanguageIndex:
    """Load a language index from a ``languages.yaml`` file (optional override path)."""
    data = yaml.safe_load(languages_yaml.read_text(encoding="utf-8")) or {}
    by_ext: dict[str, LanguageEntry] = {}
    for name, spec in (data.get("languages") or {}).items():
        language = Language(name)
        classification = FileClassification(spec["classification"])
        for ext in spec.get("extensions", []):
            by_ext[str(ext).lower()] = LanguageEntry(
                language=language, classification=classification
            )
    never_exclude = tuple(str(g) for g in (data.get("never_exclude_globs") or ()))
    return LanguageIndex(
        by_extension=by_ext,
        never_exclude_globs=never_exclude or _DEFAULT_NEVER_EXCLUDE_GLOBS,
    )


def load_scan_config(default_yaml: Path) -> ScanConfig:
    """Load :class:`ScanConfig` from a ``default.yaml`` file (optional override path)."""
    data = yaml.safe_load(default_yaml.read_text(encoding="utf-8")) or {}
    scanning = data.get("scanning") or {}
    versions = data.get("versions") or {}
    defaults = ScanConfig()
    return ScanConfig(
        allow_unc_paths=bool(scanning.get("allow_unc_paths", defaults.allow_unc_paths)),
        follow_external_junctions=bool(
            scanning.get("follow_external_junctions", defaults.follow_external_junctions)
        ),
        max_file_size_bytes=int(scanning.get("max_file_size_bytes", defaults.max_file_size_bytes)),
        long_paths_enabled=bool(scanning.get("long_paths_enabled", defaults.long_paths_enabled)),
        normalization_version=str(
            versions.get("normalization_version", defaults.normalization_version)
        ),
    )
