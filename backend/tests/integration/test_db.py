"""The app's engine is created by the lifespan and serves request-scoped sessions."""

import time
from contextlib import asynccontextmanager

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.api.main import create_app
from app.core import db
from app.core.db import session_scope

pytestmark = pytest.mark.anyio

# session_scope as FastAPI runs it: an async context manager around the generator.
session_for = asynccontextmanager(session_scope)


async def test_session_scope_queries_through_the_app_engine(make_settings):
    app = create_app(make_settings())
    async with (
        app.router.lifespan_context(app),
        session_for(Request({"type": "http", "app": app})) as session,
    ):
        assert await session.scalar(text("SELECT 1")) == 1
        assert session.bind is app.state.engine


async def test_session_query_gives_up_when_the_database_never_answers(
    make_settings, silent_port, monkeypatch
):
    monkeypatch.setattr(db, "DB_CONNECT_TIMEOUT_SECONDS", 2)  # libpq's minimum
    url = f"postgresql+psycopg://opennote:opennote@127.0.0.1:{silent_port}/opennote_test"
    app = create_app(make_settings(database_url=url))
    async with app.router.lifespan_context(app):
        t = time.monotonic()
        with anyio.fail_after(10), pytest.raises(OperationalError):  # fail_after: no hang
            async with session_for(Request({"type": "http", "app": app})) as session:
                await session.execute(text("SELECT 1"))
        assert time.monotonic() - t < 5


async def test_lifespan_disposes_the_engine_on_shutdown(make_settings):
    app = create_app(make_settings())
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        assert engine.sync_engine.pool.checkedin() == 1
    assert engine.sync_engine.pool.checkedin() == 0
