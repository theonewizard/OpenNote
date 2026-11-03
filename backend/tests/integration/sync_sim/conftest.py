"""The simulation runs against the integration test database, migrated once per module."""

import os

import pytest

SEEDS = int(os.environ.get("SYNC_SIM_SEEDS", "500"))
SEED_START = int(os.environ.get("SYNC_SIM_SEED_START", "0"))


@pytest.fixture(scope="module")
def sim_engine(tmp_path_factory):
    from app.core.config import Settings
    from app.core.db import make_sync_engine
    from tests.integration.conftest import TEST_DATABASE_URL
    from tests.integration.test_migrations import alembic_downgrade, alembic_upgrade

    alembic_upgrade(TEST_DATABASE_URL, "head")
    root = tmp_path_factory.mktemp("sim-settings")
    engine = make_sync_engine(
        Settings(database_url=TEST_DATABASE_URL, vault_root=root, history_root=root)
    )
    yield engine
    engine.dispose()
    alembic_downgrade(TEST_DATABASE_URL, "base")
