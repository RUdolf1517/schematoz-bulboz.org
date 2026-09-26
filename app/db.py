"""Асинхронный доступ к PostgreSQL: SQLAlchemy 2.0 AsyncEngine + asyncpg.

Важно: Flask выполняет каждую async-вьюху в отдельном event loop, а пул asyncpg
привязан к loop'у. Поэтому используем NullPool (пулингом занимается PgBouncer),
а сессию открываем и закрываем внутри одной корутины — через `session_scope()`.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    _engine = create_async_engine(url, poolclass=NullPool)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("DB engine is not initialised; call init_engine() first")
    return _engine


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Сессия с транзакцией: commit при успехе, rollback при исключении."""
    if _sessionmaker is None:
        raise RuntimeError("DB engine is not initialised; call init_engine() first")
    async with _sessionmaker() as session:
        async with session.begin():
            yield session
