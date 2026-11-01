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
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import make_sync_engine
from app.workers.broker import configure_broker

BACKEND_DIR = Path(__file__).resolve().parents[2]
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
    Valkey database is valid and above 0."""
    try:
        database = make_url(TEST_DATABASE_URL).database or ""
    except ArgumentError, ValueError:  # empty or unparseable, a bad port or IPv6 bracket
        database = ""
    if not database.endswith("_test"):
        raise pytest.UsageError(
            "OPENNOTE_TEST_DATABASE_URL must name a database whose name ends in _test"
        )
    if TEST_VALKEY_DB is None or TEST_VALKEY_DB <= 0:  # invalid URL, 0 or negative
        raise pytest.UsageError(
            "OPENNOTE_TEST_VALKEY_URL must be a valid redis:// or rediss:// URL naming a "
            "database above 0 (database 0 is the dev stack's)"
        )


def collect_integration_tests(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Collect tests/integration in a new pytest process with `env_overrides` added to the
    environment, so the guards above run as they would for a developer."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "tests/integration",
        ],
        cwd=BACKEND_DIR,
        env=os.environ | env_overrides,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
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


@pytest.fixture
def engine(pg_url: str, make_settings: Callable[..., Settings]) -> Iterator[Engine]:
    """A sync engine on the test database migrated to head; back to base afterwards."""
    from tests.integration.test_migrations import alembic_downgrade, alembic_upgrade

    alembic_upgrade(pg_url, "head")
    engine = make_sync_engine(make_settings())
    yield engine
    engine.dispose()
    alembic_downgrade(pg_url, "base")


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
