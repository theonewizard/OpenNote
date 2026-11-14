"""Retention in days and history GC (P5-07, design D6, sync protocol §2.1)."""

import datetime as dt
import os
import uuid

import pytest
from sqlalchemy import select, update

from app.notes.models import File
from app.sync.commit import Delete, Update
from app.sync.cursor import CursorExpired, encode_cursor
from app.sync.models import ClientOp, Conflict, Revision, VaultSeq
from app.sync.retention import GRACE, prune
from app.sync.service import changes
from tests.integration.sync.conftest import create, sha

NOW = dt.datetime(2026, 11, 14, 12, tzinfo=dt.UTC)
POLICY = {"keep_all_days": 30, "keep_daily_days": 365, "tombstone_days": 90}


@pytest.fixture
def aged(world):
    """A committer whose commits are dated `days` before NOW, set through `at`."""
    _root, factory, history, vault_id, make = world
    clock = {"days": 0.0}
    committer = make(clock=lambda: NOW - dt.timedelta(days=clock["days"]))

    def at(days, op, data=None):
        clock["days"] = days
        result = committer.commit(op, "dev", data)
        assert result.status in {"applied", "conflict"}, result
        return result

    return factory, history, vault_id, committer, at


def _revisions(factory, file_id):
    with factory() as s:
        return list(
            s.scalars(
                select(Revision.revision)
                .where(Revision.file_id == file_id)
                .order_by(Revision.revision)
            )
        )


def _update(file_id, base, data):
    return Update(uuid.uuid7(), file_id, base, sha(data)), data


def test_history_thins_out_with_age_and_keeps_the_current_revision(aged):
    factory, _history, _vault, committer, at = aged
    op, data = create("n.md", b"r1\n")
    at(400, op, data)  # r1: past keep-daily
    at(100.2, *_update(op.file_id, 1, b"r2\n"))  # r2 and r3 share a day: r3 is its last
    at(100.1, *_update(op.file_id, 2, b"r3\n"))
    at(10, *_update(op.file_id, 3, b"r4\n"))  # inside keep-all
    old, old_data = create("old.md", b"only\n")
    at(1000, old, old_data)  # a lone ancient revision is current: it stays

    removed = prune(committer, **POLICY, now=NOW)

    assert _revisions(factory, op.file_id) == [3, 4]
    assert _revisions(factory, old.file_id) == [1]
    assert removed["revisions"] == 2


def test_revisions_a_conflict_names_are_kept(aged):
    factory, _history, vault_id, committer, at = aged
    op, data = create("n.md", b"base\n")
    at(200, op, data)
    at(200, *_update(op.file_id, 1, b"theirs\n"))
    at(200, *_update(op.file_id, 2, b"later\n"))
    # An edit based on r1 against a file at r3; both rewrote the only line, so no merge.
    conflict = at(199, *_update(op.file_id, 1, b"ours\n"))
    assert conflict.status == "conflict"
    with factory() as s:
        row = s.scalars(select(Conflict).where(Conflict.vault_id == vault_id)).one()
        assert (row.base_revision, row.their_revision) == (1, 3)

    prune(committer, **POLICY, now=NOW)

    assert _revisions(factory, op.file_id) == [1, 3]  # r2 was neither


def test_expired_tombstones_are_forgotten_and_set_the_horizon(aged):
    factory, _history, vault_id, committer, at = aged
    gone, data = create("gone.md", b"bye\n")
    at(120, gone, data)
    deleted = at(100, Delete(uuid.uuid7(), gone.file_id, 1))
    recent, data = create("recent.md", b"bye too\n")
    at(50, recent, data)
    at(50, Delete(uuid.uuid7(), recent.file_id, 1))

    assert prune(committer, **POLICY, now=NOW)["files"] == 1

    with factory() as s:
        assert s.get(File, gone.file_id) is None
        assert s.get(File, recent.file_id) is not None
        horizon = s.get(VaultSeq, vault_id).horizon_seq
        assert horizon == deleted.seq
        with pytest.raises(CursorExpired):
            changes(s, vault_id, encode_cursor(vault_id, horizon - 1))
        assert changes(s, vault_id, encode_cursor(vault_id, horizon)).entries
        assert changes(s, vault_id, None).entries  # a first pull has nothing to miss
    assert _revisions(factory, gone.file_id) == []


def test_old_results_and_resolved_conflicts_are_removed(aged):
    factory, _history, vault_id, committer, at = aged
    op, data = create("n.md", b"one\n")
    at(5, op, data)
    at(5, *_update(op.file_id, 1, b"two\n"))
    at(5, *_update(op.file_id, 1, b"three\n"))  # a conflict
    old_time = NOW - dt.timedelta(days=91)
    with factory.begin() as s:
        s.execute(update(ClientOp).values(created_at=old_time))
        s.execute(update(Conflict).values(status="resolved", resolved_at=old_time))

    removed = prune(committer, **POLICY, now=NOW)

    assert (removed["client_ops"], removed["conflicts"]) == (3, 1)
    with factory() as s:
        assert s.scalars(select(Conflict).where(Conflict.vault_id == vault_id)).all() == []


def test_garbage_collection_spares_referenced_and_recent_objects(aged):
    _factory, history, _vault, committer, at = aged
    op, data = create("n.md", b"kept\n")
    at(0, op, data)
    orphan_old = history.put(b"never committed, long ago\n")
    orphan_new = history.put(b"uploaded just now\n")
    part = history.root / "uploads" / ("0" * 64 + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"half")
    stale = (NOW - GRACE - dt.timedelta(hours=1)).timestamp()
    for path in (history._object(sha(data)), history._object(orphan_old), part):
        os.utime(path, (stale, stale))

    assert prune(committer, **POLICY, now=NOW)["objects"] == 2

    assert history.has(sha(data))
    assert history.has(orphan_new)
    assert not history.has(orphan_old)
    assert not part.exists()
