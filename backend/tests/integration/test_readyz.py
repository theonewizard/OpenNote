"""GET /readyz against real PostgreSQL and Valkey: ok only when every dependency is."""

import logging
import os
import re
import time

import anyio
import pytest

from app.api import health
from app.api.health import check_valkey
from app.api.main import create_app
from app.core.logging import JsonFormatter
from tests.integration.conftest import serve

pytestmark = pytest.mark.anyio

STANDARD_RECORD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def failed_checks(caplog):
    """The check named by each readiness WARNING, in order."""
    return [r.check for r in caplog.records if r.levelno == logging.WARNING]


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


async def test_concurrent_probes_share_one_set_of_checks(make_settings, monkeypatch):
    calls = 0
    real_check_database = health.check_database

    async def slow_counted_check_database(engine):
        nonlocal calls
        calls += 1
        await anyio.sleep(0.2)  # keeps the checks in flight while the other probes arrive
        return await real_check_database(engine)

    monkeypatch.setattr(health, "check_database", slow_counted_check_database)
    answers = []
    async with serve(create_app(make_settings())) as client:

        async def probe():
            r = await client.get("/readyz")
            answers.append((r.status_code, r.json()))

        async with anyio.create_task_group() as probes:
            for _ in range(20):
                probes.start_soon(probe)
        assert calls == 1
        assert answers == [(200, {"status": "ok"})] * 20
        await client.get("/readyz")  # a later probe checks afresh: no cached result
        assert calls == 2


async def test_readyz_503_when_valkey_unreachable(make_settings, caplog):
    async with serve(create_app(make_settings(valkey_url="redis://127.0.0.1:9/0"))) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}
    assert failed_checks(caplog) == ["valkey"]


async def test_check_valkey_fails_closed_when_the_client_cannot_be_built(caplog):
    assert await check_valkey("not-a-redis-url") is False
    assert failed_checks(caplog) == ["valkey"]


@pytest.mark.parametrize("field", ["vault_root", "history_root"])
async def test_readyz_503_when_a_data_directory_is_missing(make_settings, tmp_path, field, caplog):
    settings = make_settings(**{field: tmp_path / "missing"})
    async with serve(create_app(settings)) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}
    assert failed_checks(caplog) == [field]


# CI runs as a normal user; as root, os.access() grants writing to any directory.
@pytest.mark.skipif(os.geteuid() == 0, reason="root may write to any directory")
@pytest.mark.parametrize("field", ["vault_root", "history_root"])
async def test_readyz_503_when_a_data_directory_is_read_only(
    make_settings, tmp_path, field, caplog
):
    read_only = tmp_path / "read-only"
    read_only.mkdir(mode=0o555)
    async with serve(create_app(make_settings(**{field: read_only}))) as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "fail"}
    assert failed_checks(caplog) == [field]


async def test_readyz_logs_the_failed_check_by_name_only(client_with_dead_db, caplog):
    await client_with_dead_db.get("/readyz")
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert set(vars(record)) - STANDARD_RECORD_ATTRIBUTES == {"check", "error", "request_id"}
    assert record.check == "database"
    assert re.fullmatch(r"[A-Za-z_]+", record.error)  # a class name, no message or port
    line = JsonFormatter().format(record).lower()
    for fragment in ("127.0.0.1", "port", "password", "postgresql", "redis://"):
        assert fragment not in line
