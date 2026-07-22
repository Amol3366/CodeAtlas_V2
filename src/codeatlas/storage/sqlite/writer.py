"""Coordinated single-writer for SQLite (Blueprint §4.10, §8.6, CLAUDE.md §2.12).

All writes go through one serialized path with short, batched transactions to
avoid SQLite write contention. Reads can use their own sessions concurrently;
only writes are funnelled through the lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CoordinatedWriter:
    """Serializes write transactions across the process (one logical writer)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Acquire the writer lock and yield a session inside a single transaction.

        The transaction commits on clean exit and rolls back on exception.
        """
        async with (
            self._lock,
            self._session_factory() as session,
            session.begin(),
        ):
            yield session

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        """A read session (not serialized by the writer lock)."""
        async with self._session_factory() as session:
            yield session
