"""Integration fixtures: the app against real PostgreSQL and Valkey, without Docker.

The services are found through OPENNOTE_TEST_DATABASE_URL and OPENNOTE_TEST_VALKEY_URL,
which default to the dev Compose addresses; opennote/opennote is a throwaway placeholder.
The test database's name must end in _test: the migration tests downgrade it to base,
which drops the vector and pg_trgm extensions, so the run refuses any other database.
Valkey database 0 is the dev stack's, so the run refuses it too and defaults to database 1:
the worker tests delete the ping keys and the broker's default-queue, ack and heartbeat
keys there.
"""

import os
import socket
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import make_url
from sqlalchemy.exc import ArgumentError

from app.api.main import create_app
from app.core.config import Settings
from app.workers.broker import configure_broker

DEFAULT_DATABASE_URL = "postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote_test"
DEFAULT_VALKEY_URL = "redis://127.0.0.1:6379/1"
# Nothing listens on port 9, so connecting is refused at once. The password is a marker
# that tests look for in logs.
DEAD_DATABASE_URL = "postgresql+psycopg://opennote:dead-db-password@127.0.0.1:9/opennote_test"
TEST_DATABASE_URL = os.environ.get("OPENNOTE_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
TEST_VALKEY_URL = os.environ.get("OPENNOTE_TEST_VALKEY_URL", DEFAULT_VALKEY_URL)


def _configure_test_broker() -> int | None:
    """Set the test broker and return the Valkey database it uses, or None when
    OPENNOTE_TEST_VALKEY_URL is invalid. Actors bind to dramatiq's global broker when
    app.workers.jobs is imported, so this runs before any test module imports the jobs.
    The other settings are the placeholders tests/conftest.py puts in the environment.
    Nothing connects yet."""
    try:
        broker = configure_broker(Settings(valkey_url=TEST_VALKEY_URL))
    except ValueError:  # pydantic's message echoes the URL, password included
        return None
    return broker.client.connection_pool.connection_kwargs.get("db", 0)


TEST_VALKEY_DB = _configure_test_broker()


def pytest_collection_modifyitems() -> None:
    """Stop before any test runs unless the test database is named *_test and the test
    Valkey database is valid and not 0."""
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except ArgumentError:  # empty or unparseable
        database = ""
    if not database.endswith("_test"):
        raise pytest.UsageError(
            "OPENNOTE_TEST_DATABASE_URL must name a database whose name ends in _test"
        )
    if not TEST_VALKEY_DB:  # None (invalid URL) or 0
        raise pytest.UsageError(
            "OPENNOTE_TEST_VALKEY_URL must be a valid redis:// URL naming a database "
            "other than 0, which is the dev stack's"
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def pg_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture
def valkey_url() -> str:
    return TEST_VALKEY_URL


@pytest.fixture
def make_settings(pg_url: str, valkey_url: str, tmp_path: Path) -> Callable[..., Settings]:
    """Settings for the test services with fresh writable data directories; kwargs override."""
    vaults, history = tmp_path / "vaults", tmp_path / "history"
    vaults.mkdir()
    history.mkdir()

    def make(**overrides: Any) -> Settings:
        values = {
            "database_url": pg_url,
            "valkey_url": valkey_url,
            "vault_root": vaults,
            "history_root": history,
            "environment": "test",
        }
        return Settings(**(values | overrides))

    return make


@pytest.fixture
def silent_port() -> Iterator[int]:
    """A local port that accepts connections and never answers, like a hung server."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield server.getsockname()[1]


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An async client for the app with its lifespan running, as under uvicorn."""
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def client(make_settings: Callable[..., Settings]) -> AsyncIterator[AsyncClient]:
    async with serve(create_app(make_settings())) as client:
        yield client


@pytest.fixture
async def client_with_dead_db(
    make_settings: Callable[..., Settings],
) -> AsyncIterator[AsyncClient]:
    async with serve(create_app(make_settings(database_url=DEAD_DATABASE_URL))) as client:
        yield client
