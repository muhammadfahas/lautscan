"""Async SQLAlchemy 2.0 engine, session factory, and PostGIS health check."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base declarative class for all LAUT SCAN ORM models."""


_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an `AsyncSession` with rollback on exception."""
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_db_health(timeout_seconds: float = 2.0) -> tuple[bool, str | None]:
    """Probe PostgreSQL connectivity and PostGIS version without raising on failure."""

    async def _probe() -> tuple[bool, str | None]:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            try:
                result = await session.execute(text("SELECT PostGIS_Version()"))
                version: object = result.scalar_one_or_none()
                return True, str(version) if version is not None else None
            except Exception:
                return True, None

    try:
        return await asyncio.wait_for(_probe(), timeout=timeout_seconds)
    except Exception:
        return False, None
