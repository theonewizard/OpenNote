"""GET /readyz against real PostgreSQL and Valkey: ok only when every dependency is."""

import logging
import os
import socket
import time

import pytest

from app.api.main import create_app
from tests.integration.conftest import DEAD_DATABASE_URL, serve

pytestmark = pytest.mark.anyio


@pytest.fixture
def silent_port():
    """A local port that accepts connections and never answers, like a hung server."""
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield server.getsockname()[1]


async def test_readyz_503_within_3s_when_db_unreachable(client_with_dead_db):
    t = time.monotonic()
    r = await client_with_dead_db.get("/readyz")
    assert r.status_code == 503 and time.monotonic() - t < 3
    assert r.json() == {"status": "fail"}


async def test_readyz_503_within_3s_when_db_and_valkey_hang(make_settings, silent_port):
    # Each check gives up after 2 s; only if they run concurrently does the probe end < 3 s.
    settings = make_settings(
        database_url=f"postgresql+psycopg://opennote:opennote@127.0.0.1:{silent_port}/opennote_test",
        valkey_url=f"redis://127.0.0.1:{silent_port}/0",
    )
    async with serve(create_app(settings)) as client:
        t = time.monotonic()
        r = await client.get("/readyz")
        elapsed = time.monotonic() - t
    assert r.status_code == 503 and elapsed < 3
    assert r.json() == {"status": "fail"}


async def test_readyz_200_when_all_up(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_503_when_valkey_unreachable(make_settings):
    async with serve(create_app(make_settings(valkey_url="redis://127.0.0.1:9/0"))) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}


@pytest.mark.parametrize("field", ["vault_root", "history_root"])
async def test_readyz_503_when_a_data_directory_is_missing(make_settings, tmp_path, field):
    settings = make_settings(**{field: tmp_path / "missing"})
    async with serve(create_app(settings)) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}


# CI runs as a normal user; as root, os.access() grants writing to any directory.
@pytest.mark.skipif(os.geteuid() == 0, reason="root may write to any directory")
@pytest.mark.parametrize("field", ["vault_root", "history_root"])
async def test_readyz_503_when_a_data_directory_is_read_only(make_settings, tmp_path, field):
    read_only = tmp_path / "read-only"
    read_only.mkdir(mode=0o555)
    async with serve(create_app(make_settings(**{field: read_only}))) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}


async def test_readyz_logs_the_failed_check_by_name_only(client_with_dead_db, caplog):
    await client_with_dead_db.get("/readyz")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert [getattr(r, "check", None) for r in warnings] == ["database"]
    logged = repr([r.__dict__ for r in caplog.records])
    assert "dead-db-password" not in logged
    assert DEAD_DATABASE_URL.split("@")[1] not in logged
