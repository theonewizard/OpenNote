"""The SQLAlchemy async engine (psycopg 3) and request-scoped sessions.

The engine lives on app.state.engine, created and disposed by the app's lifespan.
"""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.core.config import Settings


def engine_from_settings(settings: Settings) -> AsyncEngine:
    """Build the engine. No I/O: the pool connects on first use."""
    return create_async_engine(str(settings.database_url), pool_pre_ping=True)


async def session_scope(request: Request) -> AsyncIterator[AsyncSession]:
    """A session on the app's engine, closed afterwards; meant as a FastAPI dependency."""
    async with AsyncSession(request.app.state.engine, expire_on_commit=False) as session:
        yield session
