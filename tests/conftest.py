"""Shared test fixtures for CodeAtlas."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path

import pytest
import pytest_asyncio

from codeatlas.storage.sqlite.database import Database, build_database

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def copy_fixture(tmp_path: Path) -> Callable[[str], Path]:
    """Copy a named fixture repo into an isolated tmp dir (never mutate fixtures)."""

    def _copy(name: str) -> Path:
        dest = tmp_path / name
        shutil.copytree(FIXTURES_DIR / name, dest)
        return dest

    return _copy


@pytest.fixture
def write_tree() -> Callable[[Path, Mapping[str, str | bytes]], None]:
    """Materialize a {relative_path: content} mapping into a directory tree."""

    def _write(root: Path, files: Mapping[str, str | bytes]) -> None:
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")

    return _write


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    """A fresh SQLite database (schema created via metadata) with a coordinated writer."""
    db = build_database(tmp_path / "codeatlas.db")
    await db.create_all()
    try:
        yield db
    finally:
        await db.dispose()
