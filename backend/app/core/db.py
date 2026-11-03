"""The SQLAlchemy async engine (psycopg 3) and request-scoped sessions.

The engine lives on app.state.engine, created and disposed by the app's lifespan. The vault
engine and workers use a synchronous engine on the same URL (`make_sync_engine`).
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings

# A server that accepts TCP but never answers must not hold a request forever.
DB_CONNECT_TIMEOUT_SECONDS = 5


def engine_from_settings(settings: Settings) -> AsyncEngine:
    """Build the engine. No I/O: the pool connects on first use."""
    return create_async_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
    )


def make_sync_engine(settings: Settings) -> Engine:
    """The synchronous engine for the vault engine and workers; same URL and timeout."""
    return create_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS},
    )


class Base(DeclarativeBase):
    """ORM models; the schema itself is owned by the Alembic migrations."""


async def session_scope(request: Request) -> AsyncIterator[AsyncSession]:
    """A session on the app's engine, closed afterwards; meant as a FastAPI dependency."""
    async with AsyncSession(request.app.state.engine, expire_on_commit=False) as session:
        yield session
