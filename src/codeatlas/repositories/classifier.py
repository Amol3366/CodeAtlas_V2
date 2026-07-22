"""File classification (Blueprint §4.3.4).

Maps a repository-relative path (plus a binary flag and the language index) to a
``(Language | None, FileClassification)`` pair. Classification is deterministic
and order-sensitive: the more specific categories (lockfile, dependency
manifest, migration, infrastructure, API spec, SQL, ADR, test) are decided
before falling back to the extension's base classification.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from codeatlas.domain.enums import FileClassification, Language
from codeatlas.settings.config import LanguageIndex

_LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
}

_DEPENDENCY_MANIFEST_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pipfile",
    "package.json",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "gemfile",
}

_ADR_FILENAME = re.compile(r"^\d{3,4}[-_].+\.(md|markdown)$")


def classify(
    relative_posix: str,
    *,
    is_binary: bool,
    language_index: LanguageIndex,
) -> tuple[Language | None, FileClassification]:
    """Classify a repository-relative POSIX path."""
    pure = PurePosixPath(relative_posix)
    name = pure.name
    lower_name = name.lower()
    ext = pure.suffix.lower()
    parts_lower = [part.lower() for part in pure.parts]
    entry = language_index.lookup(ext)
    language = entry.language if entry is not None else None

    if is_binary:
        return language, FileClassification.BINARY

    # --- Specific categories, most specific first ---
    if ext == ".lock" or lower_name in _LOCKFILE_NAMES:
        return language, FileClassification.LOCKFILE

    if lower_name in _DEPENDENCY_MANIFEST_NAMES or re.fullmatch(r"requirements.*\.txt", lower_name):
        return language, FileClassification.DEPENDENCY_MANIFEST

    if "migrations" in parts_lower:
        return language, FileClassification.MIGRATION

    if _is_infrastructure(lower_name, parts_lower):
        return language, FileClassification.INFRASTRUCTURE

    if lower_name.startswith(("openapi", "swagger")) and ext in {".yaml", ".yml", ".json"}:
        return language, FileClassification.API_SPECIFICATION

    if ext == ".sql":
        return language, FileClassification.DATABASE_SCHEMA

    if _is_adr(lower_name, parts_lower):
        return language, FileClassification.ARCHITECTURE_DECISION

    if _is_test(entry, lower_name, ext, parts_lower):
        return language, FileClassification.TEST_CODE

    if ext in {".md", ".markdown"} or lower_name in {"readme", "changelog", "license", "notice"}:
        return language, FileClassification.DOCUMENTATION

    if entry is not None:
        return language, entry.classification

    return None, FileClassification.UNKNOWN


def _is_infrastructure(lower_name: str, parts_lower: list[str]) -> bool:
    if lower_name == "dockerfile" or lower_name.startswith("dockerfile."):
        return True
    if lower_name.startswith("docker-compose") and lower_name.endswith((".yml", ".yaml")):
        return True
    if ".github" in parts_lower and "workflows" in parts_lower:
        return True
    return lower_name.endswith((".tf", ".tfvars"))


def _is_adr(lower_name: str, parts_lower: list[str]) -> bool:
    if "adr" in parts_lower:
        return True
    return "docs" in parts_lower and _ADR_FILENAME.match(lower_name) is not None


def _is_test(
    entry: object,
    lower_name: str,
    ext: str,
    parts_lower: list[str],
) -> bool:
    if entry is None:
        return False
    in_test_dir = any(part in {"test", "tests", "__tests__"} for part in parts_lower)
    if ext in {".py", ".pyi"}:
        if lower_name.startswith("test_") or lower_name.endswith("_test.py"):
            return True
        return in_test_dir and lower_name.startswith("test")
    if ext in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        stem = lower_name.rsplit(".", 1)[0]
        if stem.endswith((".test", ".spec")):
            return True
        return in_test_dir
    return False
