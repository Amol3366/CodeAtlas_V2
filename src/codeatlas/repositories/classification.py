"""File classification and language detection from a repository-relative path.

Classification is path-based only: it never reads or executes file content. The
order of the checks matters — a test file is source code too, and a lockfile is a
dependency artifact rather than plain configuration — so the more specific rule
must run first.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from codeatlas.domain.repository import FileClassification

_LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
}

_BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".tar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".class",
        ".woff",
        ".woff2",
        ".ttf",
    }
)

_LOCKFILE_NAMES: frozenset[str] = frozenset(
    {
        "uv.lock",
        "poetry.lock",
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
    }
)

_DEPENDENCY_MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "requirements.txt",
        "package.json",
        "cargo.toml",
        "go.mod",
        "gemfile",
        "composer.json",
    }
)

_INFRASTRUCTURE_NAMES: frozenset[str] = frozenset(
    {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "makefile",
        ".dockerignore",
    }
)

_INFRASTRUCTURE_DIRECTORIES: frozenset[str] = frozenset(
    {".github", ".gitlab", "terraform", "helm", "k8s", "kubernetes", "deploy"}
)

_API_SPECIFICATION_STEMS: frozenset[str] = frozenset({"openapi", "swagger", "asyncapi"})
_CONFIGURATION_SUFFIXES: frozenset[str] = frozenset(
    {".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".env"}
)
_GENERATED_MARKERS: tuple[str, ...] = ("_pb2", ".generated", ".gen", "_generated")
_VENDOR_DIRECTORIES: frozenset[str] = frozenset({"vendor", "third_party", "thirdparty"})
_TEST_DIRECTORIES: frozenset[str] = frozenset({"tests", "test", "__tests__", "spec"})


def classify(relative_path: str) -> tuple[FileClassification, str]:
    """Return ``(classification, language)`` for a repository-relative path."""
    path = PurePosixPath(relative_path)
    name = path.name.lower()
    stem = path.stem.lower()
    suffix = path.suffix.lower()
    directories = tuple(part.lower() for part in path.parts[:-1])
    language = _LANGUAGE_BY_SUFFIX.get(suffix, "unknown")

    if suffix in _BINARY_SUFFIXES:
        return FileClassification.BINARY, "unknown"
    if name in _LOCKFILE_NAMES:
        return FileClassification.LOCKFILE, language
    if any(directory in _VENDOR_DIRECTORIES for directory in directories):
        return FileClassification.VENDOR, language
    if any(marker in stem for marker in _GENERATED_MARKERS):
        return FileClassification.GENERATED, language
    if "adr" in directories and language == "markdown":
        return FileClassification.ARCHITECTURE_DECISION, language
    if stem in _API_SPECIFICATION_STEMS:
        return FileClassification.API_SPECIFICATION, language
    if name in _INFRASTRUCTURE_NAMES or any(
        directory in _INFRASTRUCTURE_DIRECTORIES for directory in directories
    ):
        return FileClassification.INFRASTRUCTURE, language
    if suffix == ".sql":
        if "migration" in " ".join(directories) or "migration" in stem:
            return FileClassification.MIGRATION, language
        return FileClassification.DATABASE_SCHEMA, language
    if "migrations" in directories:
        return FileClassification.MIGRATION, language
    if name in _DEPENDENCY_MANIFEST_NAMES:
        return FileClassification.DEPENDENCY_MANIFEST, language
    if _is_test_path(stem, directories):
        return FileClassification.TEST_CODE, language
    if language == "markdown":
        return FileClassification.DOCUMENTATION, language
    if language in {"python", "typescript", "javascript"}:
        return FileClassification.SOURCE_CODE, language
    if suffix in _CONFIGURATION_SUFFIXES:
        return FileClassification.CONFIGURATION, language
    return FileClassification.UNKNOWN, language


def _is_test_path(stem: str, directories: tuple[str, ...]) -> bool:
    if any(directory in _TEST_DIRECTORIES for directory in directories):
        return True
    # `conftest.py` is pytest's fixture file and is frequently placed at a
    # repository root or beside a package, where no other rule here matches it.
    # Fixtures defined in one are invisible to test-edge derivation unless the
    # file is classified as test code.
    if stem == "conftest":
        return True
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith(".spec")
        or stem.endswith(".test")
    )
