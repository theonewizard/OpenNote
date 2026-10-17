"""The Alembic baseline: 0001 enables vector and pg_trgm, and its downgrade removes them."""

from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def alembic_config(url: str) -> Config:
    """backend/alembic.ini with the URL given as on the command line: `-x url=...`."""
    return Config(ALEMBIC_INI, cmd_opts=Namespace(x=[f"url={url}"]))


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
