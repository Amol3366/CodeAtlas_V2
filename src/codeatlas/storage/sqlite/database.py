"""Database facade: engine + session factory + coordinated writer (Phase 2).

Bundles the async engine, a session factory, and the single coordinated writer so
callers (CLI bootstrap, API DI, tests) wire storage in one place. Schema creation
in production goes through Alembic; :meth:`create_all` is a convenience for tests
and first-run bootstrap that mirrors the migrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codeatlas.storage.sqlite.engine import create_async_db_engine, make_session_factory
from codeatlas.storage.sqlite.models import Base
from codeatlas.storage.sqlite.writer import CoordinatedWriter


@dataclass
class Database:
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    writer: CoordinatedWriter

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


def build_database(db_path: Path) -> Database:
    engine = create_async_db_engine(db_path)
    session_factory = make_session_factory(engine)
    return Database(
        engine=engine,
        session_factory=session_factory,
        writer=CoordinatedWriter(session_factory),
    )
