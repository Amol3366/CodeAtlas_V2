"""Tests for file classification (Blueprint §4.3.4)."""

from __future__ import annotations

import pytest

from codeatlas.domain.enums import FileClassification as FC
from codeatlas.domain.enums import Language
from codeatlas.repositories.classifier import classify
from codeatlas.settings.config import default_language_index

INDEX = default_language_index()


@pytest.mark.parametrize(
    ("path", "expected_language", "expected_classification"),
    [
        ("src/app.py", Language.PYTHON, FC.SOURCE_CODE),
        ("src/api/orderRoutes.ts", Language.TYPESCRIPT, FC.SOURCE_CODE),
        ("tests/test_auth.py", Language.PYTHON, FC.TEST_CODE),
        ("src/services/auth_service_test.py", Language.PYTHON, FC.TEST_CODE),
        ("test/orderService.test.ts", Language.TYPESCRIPT, FC.TEST_CODE),
        ("README.md", Language.MARKDOWN, FC.DOCUMENTATION),
        ("docs/adr/0001-idempotency.md", Language.MARKDOWN, FC.ARCHITECTURE_DECISION),
        ("pyproject.toml", Language.TOML, FC.DEPENDENCY_MANIFEST),
        ("package.json", Language.JSON, FC.DEPENDENCY_MANIFEST),
        ("uv.lock", None, FC.LOCKFILE),
        ("package-lock.json", Language.JSON, FC.LOCKFILE),
        ("config/app.yaml", Language.YAML, FC.CONFIGURATION),
        ("config/app.json", Language.JSON, FC.CONFIGURATION),
        ("db/schema.sql", None, FC.DATABASE_SCHEMA),
        ("migrations/0001_init.py", Language.PYTHON, FC.MIGRATION),
        ("Dockerfile", None, FC.INFRASTRUCTURE),
        (".github/workflows/ci.yml", Language.YAML, FC.INFRASTRUCTURE),
        ("openapi.yaml", Language.YAML, FC.API_SPECIFICATION),
        ("data/notes.rst", None, FC.UNKNOWN),
    ],
)
def test_classify(
    path: str, expected_language: Language | None, expected_classification: FC
) -> None:
    language, classification = classify(path, is_binary=False, language_index=INDEX)
    assert language == expected_language
    assert classification == expected_classification


def test_binary_wins_over_extension() -> None:
    language, classification = classify("src/app.py", is_binary=True, language_index=INDEX)
    assert classification is FC.BINARY
    assert language is Language.PYTHON
