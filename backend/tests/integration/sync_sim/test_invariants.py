"""The invariant checker is tested on its own (plan Task 15 step 1): each test settles a
small fault-free world, breaks one invariant by hand and expects exactly that report."""

import uuid

import pytest

from app.sync.commit import Create
from tests.integration.sync_sim.client import sha
from tests.integration.sync_sim.invariants import (
    check_idempotent,
    check_invariants,
    check_no_loops,
)
from tests.integration.sync_sim.world import Delivery, World

pytestmark = pytest.mark.sync_sim


@pytest.fixture
def world(sim_engine, tmp_path):
    w = World(1, sim_engine, tmp_path, 2, faults=False)
    c0, _c1 = w.clients
    marker = w.new_marker("c0")
    (c0.root / "Beta.md").write_bytes(f"# Beta\n{marker}\n".encode())
    w.quiesce()
    yield w
    w.close()


def codes(violations) -> set[str]:
    return {v.code for v in violations}


def test_settled_world_has_no_violations(world):
    assert check_invariants(world) == []
    assert check_no_loops(world) == []
    assert check_idempotent(world) == []


def test_invariant_checker_catches_lost_edit(world):  # I1
    world.new_marker("c1")  # acknowledged to the user, never committed
    assert codes(check_invariants(world)) == {"I1"}


def test_invariant_checker_catches_dropped_content(world):  # I2
    c0 = world.clients[0]
    (c0.root / "Beta.md").write_bytes(b"# Beta\n")
    c0.sync()
    world.quiesce()
    assert codes(check_invariants(world)) == {"I2"}


def test_invariant_checker_catches_divergent_client(world):  # I3
    (world.clients[1].root / "Beta.md").write_bytes(b"# Beta\nother\n")
    assert codes(check_invariants(world)) == {"I3"}


def test_invariant_checker_catches_non_idempotent_replay(world):  # I4
    data = b"# Gamma\n"
    op = Create(uuid.uuid4(), uuid.uuid4(), "Gamma.md", "note", sha(data))
    world.deliveries.append(Delivery("c0", [op], {sha(data): data}))
    assert codes(check_idempotent(world)) == {"I4"}


def test_invariant_checker_catches_sync_loop(world):  # I5
    (world.clients[0].root / "Late.md").write_bytes(b"# Late\n")
    assert codes(check_no_loops(world)) == {"I5"}


def test_invariant_checker_catches_server_vault_drift(world):
    (world.server_root / "Stray.md").write_bytes(b"# Stray\n")
    assert "server-vault" in codes(check_invariants(world))


def test_invariant_checker_catches_missing_history(world):
    blob = next((world.history.root / "objects").rglob("*"), None)
    while blob is not None and blob.is_dir():
        blob = next(blob.iterdir())
    assert blob is not None
    blob.unlink()
    assert "history" in codes(check_invariants(world))


def test_invariant_checker_catches_invented_conflict_copy(sim_engine, tmp_path):
    w = World(2, sim_engine, tmp_path, 2, faults=False)
    try:
        for c in w.clients:  # both create Beta.md offline: one becomes a conflict copy
            (c.root / "Beta.md").write_bytes(f"# Beta\n{w.new_marker(c.name)}\n".encode())
            c.scan()
        w.quiesce()
        assert check_invariants(w) == []
        w.pushed_hashes.clear()
        assert codes(check_invariants(w)) == {"conflict-copy"}
    finally:
        w.close()
