"""File classification and language detection."""

from __future__ import annotations

import pytest

from codeatlas.domain.repository import FileClassification
from codeatlas.repositories.classification import classify


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("src/payments/service.py", (FileClassification.SOURCE_CODE, "python")),
        ("tests/test_service.py", (FileClassification.TEST_CODE, "python")),
        ("src/payments/service_test.py", (FileClassification.TEST_CODE, "python")),
        ("src/orders.ts", (FileClassification.SOURCE_CODE, "typescript")),
        ("src/orders.spec.ts", (FileClassification.TEST_CODE, "typescript")),
        ("src/client.js", (FileClassification.SOURCE_CODE, "javascript")),
        ("README.md", (FileClassification.DOCUMENTATION, "markdown")),
        ("docs/adr/0001-x.md", (FileClassification.ARCHITECTURE_DECISION, "markdown")),
        ("openapi.yaml", (FileClassification.API_SPECIFICATION, "yaml")),
        ("config/settings.yaml", (FileClassification.CONFIGURATION, "yaml")),
        ("pyproject.toml", (FileClassification.DEPENDENCY_MANIFEST, "toml")),
        ("package.json", (FileClassification.DEPENDENCY_MANIFEST, "json")),
        ("uv.lock", (FileClassification.LOCKFILE, "unknown")),
        ("pnpm-lock.yaml", (FileClassification.LOCKFILE, "yaml")),
        ("migrations/0001_init.sql", (FileClassification.MIGRATION, "sql")),
        ("db/schema.sql", (FileClassification.DATABASE_SCHEMA, "sql")),
        ("Dockerfile", (FileClassification.INFRASTRUCTURE, "unknown")),
        (".github/workflows/ci.yml", (FileClassification.INFRASTRUCTURE, "yaml")),
        ("vendor/lib/thing.py", (FileClassification.VENDOR, "python")),
        ("src/schema_pb2.py", (FileClassification.GENERATED, "python")),
        ("assets/logo.png", (FileClassification.BINARY, "unknown")),
        ("notes.unknownext", (FileClassification.UNKNOWN, "unknown")),
    ],
)
def test_classification_and_language(
    relative_path: str, expected: tuple[FileClassification, str]
) -> None:
    assert classify(relative_path) == expected


def test_classification_is_case_insensitive_on_extensions() -> None:
    assert classify("src/App.PY") == (FileClassification.SOURCE_CODE, "python")
    assert classify("README.MD") == (FileClassification.DOCUMENTATION, "markdown")
