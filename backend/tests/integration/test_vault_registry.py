"""Vault registration and opening against PostgreSQL (storage contract §1, §1.2)."""

import json
import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.db import make_sync_engine
from app.vaults.config import SUPPORTED_SCHEMA_VERSION
from app.vaults.models import Vault
from app.vaults.registry import open_vault, register_vault
from app.vaults.scan import scan
from tests.conftest import tree_digest
from tests.integration.test_migrations import alembic_downgrade, alembic_upgrade


@pytest.fixture
def engine(pg_url, make_settings):
    alembic_upgrade(pg_url, "head")
    engine = make_sync_engine(make_settings())
    yield engine
    engine.dispose()
    alembic_downgrade(pg_url, "base")


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


def config(root):
    return json.loads((root / ".opennote" / "config.json").read_text())


def test_open_existing_vault_writes_nothing(obsidian_vault, session):
    before = tree_digest(obsidian_vault)
    open_vault(session, obsidian_vault)
    list(scan(obsidian_vault))
    assert tree_digest(obsidian_vault) == before


def test_opening_twice_keeps_the_id_in_the_database_only(obsidian_vault, session):
    first = open_vault(session, obsidian_vault)
    session.commit()
    assert open_vault(session, obsidian_vault) == first
    assert not (obsidian_vault / ".opennote").exists()
    row = session.get(Vault, first)
    assert row is not None and row.root_path == str(obsidian_vault)


def test_register_writes_the_config_with_the_existing_id(obsidian_vault, session):
    opened = open_vault(session, obsidian_vault)
    registered = register_vault(session, obsidian_vault, "Work")
    assert registered == opened
    assert config(obsidian_vault) == {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "vault_id": str(opened),
        "name": "Work",
    }
    assert session.get(Vault, opened).name == "Work"


def test_open_uses_the_config_vault_id(obsidian_vault, session):
    vault_id = uuid.uuid7()
    (obsidian_vault / ".opennote").mkdir()
    (obsidian_vault / ".opennote" / "config.json").write_text(
        json.dumps({"schema_version": 1, "vault_id": str(vault_id), "name": "Moved"})
    )
    assert open_vault(session, obsidian_vault) == vault_id
    assert session.get(Vault, vault_id).name == "Moved"


def test_register_refuses_a_newer_vault(obsidian_vault, session):
    (obsidian_vault / ".opennote").mkdir()
    newer = {"schema_version": SUPPORTED_SCHEMA_VERSION + 1, "vault_id": str(uuid.uuid7())}
    (obsidian_vault / ".opennote" / "config.json").write_text(json.dumps(newer | {"name": "N"}))
    with pytest.raises(PermissionError):
        register_vault(session, obsidian_vault, "Mine")
    assert config(obsidian_vault)["name"] == "N"


def test_downgrade_drops_the_vaults_table(pg_url, engine):
    assert "vaults" in inspect(engine).get_table_names()
    alembic_downgrade(pg_url, "-1")
    engine.dispose()
    assert "vaults" not in inspect(engine).get_table_names()
    with Session(engine) as s:
        assert s.scalars(select(1)).one() == 1
