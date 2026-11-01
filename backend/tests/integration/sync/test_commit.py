"""The commit path: history, PostgreSQL, log, vault, in that order (sync protocol §2.3)."""

import hashlib
import os
import threading
import uuid
from dataclasses import astuple

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.notes.models import File
from app.sync.commit import Committer, Create, Delete, Move, Restore, Update
from app.sync.history import HistoryStore, RevisionLogEntry
from app.sync.models import Revision
from app.vaults.fsio import open_root
from app.vaults.registry import open_vault

BASE = b"one\ntwo\nthree\nfour\nfive\n"


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class SimulatedCrash(Exception):
    pass


@pytest.fixture
def world(tmp_path, engine):
    root = tmp_path / "vault"
    root.mkdir()
    factory = sessionmaker(engine)
    with factory.begin() as s:
        vault_id = open_vault(s, root)
    history = HistoryStore(tmp_path / "history", vault_id)
    root_fd = open_root(root)

    def make(**kwargs):
        return Committer(factory, history, root_fd, vault_id, **kwargs)

    yield root, factory, history, vault_id, make
    os.close(root_fd)


def create(path="n.md", data=BASE, file_id=None):
    op = Create(uuid.uuid7(), file_id or uuid.uuid7(), path, "note", sha(data))
    return op, data


def assert_consistent(root, factory, history, vault_id):
    with factory() as s:
        rows = s.scalars(select(File).where(File.vault_id == vault_id)).all()
        seqs = sorted(s.scalars(select(Revision.seq).where(Revision.vault_id == vault_id)))
    for row in rows:
        target = root / row.path
        if row.deleted:
            assert not target.exists()
        else:
            assert sha(target.read_bytes()) == row.content_hash
    assert sorted(e.seq for e in history.read_log()) == seqs
    assert seqs == list(range(1, len(seqs) + 1))


def test_create_update_move_delete_restore(world):
    root, factory, history, vault_id, make = world
    c = make()
    op, data = create()
    r1 = c.commit(op, "dev", data)
    assert (r1.status, r1.revision, r1.seq, r1.path) == ("applied", 1, 1, "n.md")
    assert (root / "n.md").read_bytes() == BASE
    new = BASE + b"six\n"
    r2 = c.commit(Update(uuid.uuid7(), op.file_id, 1, sha(new)), "dev", new)
    assert (r2.status, r2.revision) == ("applied", 2) and (root / "n.md").read_bytes() == new
    r3 = c.commit(Move(uuid.uuid7(), op.file_id, 2, "sub/m.md"), "dev", None)
    assert (r3.status, r3.revision, r3.path) == ("applied", 3, "sub/m.md")
    assert (root / "sub/m.md").read_bytes() == new and not (root / "n.md").exists()
    r4 = c.commit(Delete(uuid.uuid7(), op.file_id, 3), "dev", None)
    assert (r4.status, r4.revision) == ("applied", 4) and not (root / "sub/m.md").exists()
    assert [p.read_bytes() for p in (history.root / "recovery").iterdir()] == [new]
    r5 = c.commit(Restore(uuid.uuid7(), op.file_id, 1), "dev", None)
    assert (r5.status, r5.revision) == ("applied", 5)
    assert (root / "sub/m.md").read_bytes() == BASE
    assert_consistent(root, factory, history, vault_id)


def test_rejected_operations_change_nothing(world):
    root, factory, history, vault_id, make = world
    c = make()
    bad_path = c.commit(
        Create(uuid.uuid7(), uuid.uuid7(), "a/../b.md", "note", sha(BASE)), "d", BASE
    )
    no_blob = c.commit(Create(uuid.uuid7(), uuid.uuid7(), "x.md", "note", sha(BASE)), "d", None)
    wrong_blob = c.commit(Create(uuid.uuid7(), uuid.uuid7(), "x.md", "note", sha(BASE)), "d", b"x")
    unknown = c.commit(Update(uuid.uuid7(), uuid.uuid7(), 1, sha(BASE)), "d", BASE)
    for result in (bad_path, no_blob, wrong_blob, unknown):
        assert result.status == "rejected" and result.problem["status"] in (404, 409, 422)
        assert result.seq is None
    assert list(root.iterdir()) == []
    assert_consistent(root, factory, history, vault_id)


def test_stale_update_is_merged(world):
    root, _factory, _history, _vault_id, make = world
    c = make()
    op, data = create()
    c.commit(op, "a", data)
    theirs = BASE.replace(b"five", b"FIVE")
    c.commit(Update(uuid.uuid7(), op.file_id, 1, sha(theirs)), "a", theirs)
    ours = BASE.replace(b"one", b"ONE")
    result = c.commit(Update(uuid.uuid7(), op.file_id, 1, sha(ours)), "b", ours)
    merged = BASE.replace(b"one", b"ONE").replace(b"five", b"FIVE")
    assert (result.status, result.revision, result.content_hash) == ("merged", 3, sha(merged))
    assert (root / "n.md").read_bytes() == merged


def test_retry_with_same_client_op_id_returns_duplicate(world):
    root, factory, history, vault_id, make = world
    c = make()
    op, data = create()
    first = c.commit(op, "dev", data)
    again = c.commit(op, "dev", None)  # a retry need not resend the blob
    assert again.status == "duplicate"
    assert astuple(again)[1:] == astuple(first)[1:]
    assert_consistent(root, factory, history, vault_id)


def test_seq_is_gap_free_under_concurrent_commits(world):
    root, factory, history, vault_id, make = world
    errors = []

    def worker(n):
        c = make()
        try:
            for i in range(50):
                data = f"{n}-{i}\n".encode()
                op, _ = create(f"t{n}/n{i}.md", data)
                assert c.commit(op, f"dev{n}", data).status == "applied"
        except Exception as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with factory() as s:
        seqs = sorted(s.scalars(select(Revision.seq).where(Revision.vault_id == vault_id)))
    assert seqs == list(range(1, 201))
    assert_consistent(root, factory, history, vault_id)


@pytest.mark.parametrize("point", ["history", "db", "log", "vault"])
def test_crash_then_recover_restores_consistency(world, point):
    root, factory, history, vault_id, make = world
    op, data = create()
    make().commit(op, "dev", data)
    new = BASE + b"six\n"
    update = Update(uuid.uuid7(), op.file_id, 1, sha(new))

    def crash(step):
        if step == point:
            raise SimulatedCrash(step)

    with pytest.raises(SimulatedCrash):
        make(crash=crash).commit(update, "dev", new)
    restarted = make()
    restarted.recover()
    assert_consistent(root, factory, history, vault_id)
    retry = restarted.commit(update, "dev", new)
    assert retry.status == ("applied" if point == "history" else "duplicate")
    assert retry.revision == 2
    assert (root / "n.md").read_bytes() == new
    assert_consistent(root, factory, history, vault_id)


def test_external_edit_during_commit_is_merged_not_clobbered(world):
    root, factory, history, vault_id, make = world
    op, data = create()
    make().commit(op, "dev", data)
    external = BASE.replace(b"five", b"FIVE")

    def edit_on_disk(step):
        if step == "log":  # an editor saves between the log line and the vault write
            (root / "n.md").write_bytes(external)

    ours = BASE.replace(b"one", b"ONE")
    result = make(crash=edit_on_disk).commit(
        Update(uuid.uuid7(), op.file_id, 1, sha(ours)), "dev", ours
    )
    assert (result.status, result.revision) == ("applied", 2)
    merged = BASE.replace(b"one", b"ONE").replace(b"five", b"FIVE")
    assert (root / "n.md").read_bytes() == merged
    with factory() as s:
        revs = s.execute(
            select(Revision.revision, Revision.device_id, Revision.content_hash)
            .where(Revision.file_id == op.file_id)
            .order_by(Revision.revision)
        ).all()
    assert revs == [(1, "dev", sha(BASE)), (2, "dev", sha(ours)), (3, "server-fs", sha(merged))]
    assert history.get(sha(external)) == external  # the external save is kept in history
    assert_consistent(root, factory, history, vault_id)


def test_log_rebuild_reproduces_revisions(world):
    _root, factory, history, vault_id, make = world
    c = make()
    op, data = create()
    c.commit(op, "dev", data)
    c.commit(Move(uuid.uuid7(), op.file_id, 1, "m.md"), "dev", None)
    c.commit(Delete(uuid.uuid7(), op.file_id, 2), "dev", None)
    columns = (
        Revision.seq,
        Revision.file_id,
        Revision.revision,
        Revision.path,
        Revision.kind,
        Revision.content_hash,
        Revision.deleted,
        Revision.device_id,
        Revision.op,
    )
    with factory.begin() as s:
        before = s.execute(
            select(*columns).where(Revision.vault_id == vault_id).order_by(Revision.seq)
        ).all()
        s.execute(delete(Revision).where(Revision.vault_id == vault_id))
    rebuilt = sorted(
        (e.seq, e.file_id, e.revision, e.path, e.kind, e.content_hash, e.deleted, e.device_id, e.op)
        for e in history.read_log()
    )
    assert rebuilt == [tuple(r) for r in before]
    assert all(isinstance(e, RevisionLogEntry) for e in history.read_log())
