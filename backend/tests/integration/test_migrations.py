"""The Alembic baseline: 0001 enables vector and pg_trgm, and its downgrade removes them."""

import json
import os
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config(url: str | None = None) -> Config:
    """backend/alembic.ini, with the URL given as on the command line (`-x url=...`).
    Called in-process, so env.py leaves the test run's logging alone."""
    return Config(
        ALEMBIC_INI,
        cmd_opts=Namespace(x=[f"url={url}"] if url else None),
        attributes={"configure_logger": False},
    )


def alembic_upgrade(url: str, revision: str) -> None:
    command.upgrade(alembic_config(url), revision)


def alembic_downgrade(url: str, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)


def extensions(url: str) -> set[str]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return set(connection.scalars(text("SELECT extname FROM pg_extension")))
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def back_to_base(pg_url):
    """Leave the test database at base, also when the test fails halfway."""
    yield
    alembic_downgrade(pg_url, "base")


def test_upgrade_then_downgrade_roundtrip(pg_url):
    alembic_upgrade(pg_url, "head")
    assert extensions(pg_url) >= {"vector", "pg_trgm"}
    alembic_downgrade(pg_url, "base")
    assert not extensions(pg_url) & {"vector", "pg_trgm"}


def test_migrations_need_only_the_database_url(pg_url, monkeypatch):
    for name in [n for n in os.environ if n.startswith("OPENNOTE_")]:
        if not name.startswith("OPENNOTE_TEST_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OPENNOTE_DATABASE_URL", pg_url)
    command.upgrade(alembic_config(), "head")
    assert extensions(pg_url) >= {"vector", "pg_trgm"}


def test_cli_offline_mode_prints_sql_and_logs_without_connecting():
    # Nothing listens on port 9, so any attempt to connect would fail at once.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-x",
            "url=postgresql+psycopg://opennote:opennote@127.0.0.1:9/opennote_test",
            "upgrade",
            "head",
            "--sql",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in result.stdout
    logs = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert any(e["level"] == "INFO" and e["msg"].startswith("Running upgrade") for e in logs)


def test_revision_renders_a_new_migration_from_the_template(tmp_path, monkeypatch):
    # A copy, so no file is left in the repository; alembic.ini prepends its dir to sys.path.
    monkeypatch.setattr(sys, "path", list(sys.path))
    shutil.copy(ALEMBIC_INI, tmp_path)
    shutil.copytree(
        BACKEND_DIR / "migrations",
        tmp_path / "migrations",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    command.revision(Config(tmp_path / "alembic.ini"), message="probe", rev_id="probe")
    [new] = (tmp_path / "migrations" / "versions").glob("probe_*.py")
    source = new.read_text()
    compile(source, str(new), "exec")
    assert "revision: str = 'probe'" in source
    assert "= '0001'" in source  # down_revision: chained onto the baseline


def test_integration_tests_refuse_a_database_not_named_test():
    env = os.environ | {
        "OPENNOTE_TEST_DATABASE_URL": "postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote"
    }
    result = subprocess.run(
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
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "must name a database whose name ends in _test" in result.stderr
