"""Integration fixtures: the app against real PostgreSQL and Valkey, without Docker.

The services are found through OPENNOTE_TEST_DATABASE_URL and OPENNOTE_TEST_VALKEY_URL,
which default to the dev Compose addresses; opennote/opennote is a throwaway placeholder.
"""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient

from app.api.main import create_app
from app.core.config import Settings

DEFAULT_DATABASE_URL = "postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote_test"
DEFAULT_VALKEY_URL = "redis://127.0.0.1:6379/0"
# Nothing listens on port 9, so connecting is refused at once. The password is a marker
# that tests look for in logs.
DEAD_DATABASE_URL = "postgresql+psycopg://opennote:dead-db-password@127.0.0.1:9/opennote_test"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def pg_url() -> str:
    return os.environ.get("OPENNOTE_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture
def valkey_url() -> str:
    return os.environ.get("OPENNOTE_TEST_VALKEY_URL", DEFAULT_VALKEY_URL)


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
