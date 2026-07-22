"""Alembic migration tests: upgrade + downgrade, and parity with the ORM models."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from codeatlas.storage.sqlite.models import Base

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _table_names(db_path: Path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def test_upgrade_creates_all_model_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    command.upgrade(_alembic_config(db_path), "head")

    tables = _table_names(db_path)
    # Every ORM table exists after upgrade (migration stays in sync with models).
    for table in Base.metadata.tables:
        assert table in tables, table
    assert "alembic_version" in tables


def test_downgrade_removes_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    tables = _table_names(db_path)
    for table in Base.metadata.tables:
        assert table not in tables, table
