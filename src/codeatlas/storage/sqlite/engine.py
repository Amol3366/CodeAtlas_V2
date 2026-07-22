"""SQLite engine construction and mandatory pragmas (CLAUDE.md §3, Blueprint §4.7.1).

Every connection — async (app) or sync (Alembic/tests) — gets the required
pragmas set on connect:

    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;
    PRAGMA synchronous = NORMAL;
    PRAGMA busy_timeout = 5000;

The app uses the aiosqlite async driver; Alembic uses the sync pysqlite driver
against the same file. Both share ``models.Base.metadata``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def async_database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def sync_database_url(db_path: Path) -> str:
    return f"sqlite:///{db_path.as_posix()}"


def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_async_db_engine(db_path: Path) -> AsyncEngine:
    """Create the async engine used by the application, with pragmas installed."""
    engine = create_async_engine(async_database_url(db_path), future=True)
    event.listen(engine.sync_engine, "connect", _set_pragmas)
    return engine


def create_sync_db_engine(db_path: Path) -> Engine:
    """Create a sync engine (Alembic migrations / test setup), with pragmas installed."""
    engine = create_engine(sync_database_url(db_path), future=True)
    event.listen(engine, "connect", _set_pragmas)
    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory that does not expire attributes on commit (safe post-commit reads)."""
    return async_sessionmaker(engine, expire_on_commit=False)
