"""Push, pull, snapshot and server-side changes (sync protocol §4 to §7)."""

import base64
import uuid

import pytest

from app.notes.identity import diff_scan
from app.sync.commit import SERVER_FS, Create, Delete, Move, Update
from app.sync.cursor import RETENTION_SEQ_WINDOW, CursorExpired, decode_cursor, encode_cursor
from app.sync.service import changes, ingest_fs_changes, push, snapshot
from app.vaults.scan import scan
from tests.integration.sync.conftest import BASE, create, sha


@pytest.fixture
def server(world):
    root, factory, _history, vault_id, make = world
    return root, factory, vault_id, make()


def seed(committer, path="n.md", data=BASE):
    op, data = create(path, data)
    result = committer.commit(op, "seed", data)
    assert result.status == "applied"
    return op.file_id


def update(file_id, base, data):
    return [Update(uuid.uuid7(), file_id, base, sha(data))], {sha(data): data}


# Cursor --------------------------------------------------------------------------------


def test_cursor_roundtrip_is_opaque():
    vault = uuid.uuid7()
    cursor = encode_cursor(vault, 42)
    assert str(vault) not in cursor and "42" not in cursor
    assert decode_cursor(cursor, vault) == 42


def test_cursor_from_other_vault_rejected():
    with pytest.raises(ValueError):
        decode_cursor(encode_cursor(uuid.uuid7(), 1), uuid.uuid7())


@pytest.mark.parametrize("junk", ["", "!!!", base64.urlsafe_b64encode(b"short").decode()])
def test_malformed_cursor_rejected(junk):
    with pytest.raises(ValueError):
        decode_cursor(junk, uuid.uuid7())


def test_expired_cursor_raises(server, monkeypatch):
    _root, factory, vault_id, committer = server
    monkeypatch.setattr("app.sync.service.RETENTION_SEQ_WINDOW", 2)
    for i in range(4):
        seed(committer, f"n{i}.md", f"{i}\n".encode())
    with factory() as s:
        with pytest.raises(CursorExpired):
            changes(s, vault_id, encode_cursor(vault_id, 1))
        assert len(changes(s, vault_id, encode_cursor(vault_id, 2)).entries) == 2
    assert RETENTION_SEQ_WINDOW > 1000


# Pull (§4): the entries each row of the client's table acts on ---------------------------


def test_pull_pages_in_seq_order(server):
    _root, factory, vault_id, committer = server
    for i in range(5):
        seed(committer, f"n{i}.md", f"{i}\n".encode())
    with factory() as s:
        first = changes(s, vault_id, None, limit=3)
        assert [e.seq for e in first.entries] == [1, 2, 3] and first.has_more
        rest = changes(s, vault_id, first.next_cursor, limit=3)
        assert [e.seq for e in rest.entries] == [4, 5] and not rest.has_more
        idle = changes(s, vault_id, rest.next_cursor)
        assert idle.entries == [] and idle.next_cursor == rest.next_cursor


def test_pull_unknown_or_clean_entry_carries_what_to_download(server):
    _root, factory, vault_id, committer = server
    file_id = seed(committer)
    with factory() as s:
        [entry] = changes(s, vault_id, None).entries
    assert (entry.file_id, entry.revision, entry.path, entry.kind) == (file_id, 1, "n.md", "note")
    assert (entry.content_hash, entry.size, entry.deleted) == (sha(BASE), len(BASE), False)
    assert (entry.device_id, entry.op) == ("seed", "create")


def test_pull_tombstone_entry(server):
    _root, factory, vault_id, committer = server
    file_id = seed(committer)
    committer.commit(Delete(uuid.uuid7(), file_id, 1), "a", None)
    with factory() as s:
        tomb = changes(s, vault_id, None).entries[-1]
    assert (tomb.revision, tomb.deleted, tomb.content_hash, tomb.path) == (2, True, None, "n.md")


def test_pull_dirty_client_pushes_on_old_base_and_server_merges(server):
    _root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    theirs = BASE.replace(b"five", b"FIVE")
    push(
        committer, "a", *update(file_id, 1, theirs)
    )  # the remote revision the dirty client records
    ours = BASE.replace(b"one", b"ONE")
    [result] = push(committer, "b", *update(file_id, 1, ours))
    assert result.status == "merged"


def test_pull_pending_delete_is_decided_on_push(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    [result] = push(committer, "b", [Delete(uuid.uuid7(), file_id, 1)], {})
    assert result.status == "applied" and not (root / "n.md").exists()


def test_full_reconcile_snapshot_lists_live_files(server):
    _root, factory, vault_id, committer = server
    keep, gone = seed(committer, "keep.md"), seed(committer, "gone.md", b"g\n")
    committer.commit(Delete(uuid.uuid7(), gone, 1), "a", None)
    committer.commit(Move(uuid.uuid7(), keep, 1, "kept.md"), "a", None)
    with factory() as s:
        [entry] = snapshot(s, vault_id)
    assert (entry.file_id, entry.path, entry.revision, entry.seq) == (keep, "kept.md", 2, 4)


# Push results (§5) ------------------------------------------------------------------------


def test_push_applied(server):
    _root, _factory, _vault_id, committer = server
    op, data = create()
    [result] = push(committer, "a", [op], {op.content_hash: data})
    assert (result.status, result.revision, result.seq) == ("applied", 1, 1)


def test_push_merged(server):
    test_pull_dirty_client_pushes_on_old_base_and_server_merges(server)


def test_push_conflict(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    push(committer, "a", *update(file_id, 1, BASE.replace(b"three", b"theirs")))
    [result] = push(committer, "b", *update(file_id, 1, BASE.replace(b"three", b"ours")))
    assert result.status == "conflict" and result.path.startswith("n (conflict b ")
    assert result.problem["original_file_id"] == str(file_id)
    assert (root / result.path).read_bytes() == BASE.replace(b"three", b"ours")
    assert (root / "n.md").read_bytes() == BASE.replace(b"three", b"theirs")


def test_push_rejected(server):
    _root, _factory, _vault_id, committer = server
    op = Create(uuid.uuid7(), uuid.uuid7(), "bad:name.md", "note", sha(BASE))
    [result] = push(committer, "a", [op], {sha(BASE): BASE})
    assert result.status == "rejected" and result.problem["status"] == 422


def test_push_duplicate(server):
    _root, _factory, _vault_id, committer = server
    op, data = create()
    first = push(committer, "a", [op], {op.content_hash: data})
    again = push(committer, "a", [op], {})
    assert [r.status for r in again] == ["duplicate"] and again[0].seq == first[0].seq


def test_push_processes_ops_in_order_and_independently(server):
    _root, _factory, _vault_id, committer = server
    a, data = create("a.md")
    bad = Create(uuid.uuid7(), uuid.uuid7(), "b|.md", "note", sha(BASE))
    c, _ = create("c.md")
    results = push(committer, "a", [a, bad, c], {sha(BASE): data})
    assert [r.status for r in results] == ["applied", "rejected", "applied"]
    assert [r.seq for r in results] == [1, None, 2]


def test_push_refuses_more_than_100_ops(server):
    _root, _factory, _vault_id, committer = server
    with pytest.raises(ValueError):
        push(committer, "a", [create(f"n{i}.md")[0] for i in range(101)], {})


# Other cases (§6) -------------------------------------------------------------------------


def test_move_vs_update(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    [moved] = push(committer, "a", [Move(uuid.uuid7(), file_id, 1, "m.md")], {})
    edited = BASE + b"six\n"
    [updated] = push(committer, "b", *update(file_id, 1, edited))
    assert moved.status == "applied" and updated.status == "applied"
    assert (root / "m.md").read_bytes() == edited and not (root / "n.md").exists()


def test_move_vs_move_to_different_paths(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    push(committer, "a", [Move(uuid.uuid7(), file_id, 1, "a.md")], {})
    [later] = push(committer, "b", [Move(uuid.uuid7(), file_id, 1, "b.md")], {})
    assert (later.status, later.path, later.revision) == ("merged", "b.md", 3)
    assert (root / "b.md").read_bytes() == BASE and not (root / "a.md").exists()


def test_update_vs_delete_edit_wins_when_delete_comes_first(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    push(committer, "a", [Delete(uuid.uuid7(), file_id, 1)], {})
    edited = BASE + b"six\n"
    [result] = push(committer, "b", *update(file_id, 1, edited))
    assert (result.status, result.revision) == ("applied", 3)
    assert (root / "n.md").read_bytes() == edited


def test_update_vs_delete_edit_wins_when_update_comes_first(server):
    root, _factory, _vault_id, committer = server
    file_id = seed(committer)
    edited = BASE + b"six\n"
    push(committer, "a", *update(file_id, 1, edited))
    [result] = push(committer, "b", [Delete(uuid.uuid7(), file_id, 1)], {})
    assert result.status == "merged" and result.problem["type"].endswith("/delete-superseded")
    assert (root / "n.md").read_bytes() == edited


def test_create_vs_create_same_path(server):
    root, _factory, _vault_id, committer = server
    seed(committer)
    op, data = create("n.md", b"other\n")
    [result] = push(committer, "dev2", [op], {op.content_hash: data})
    assert result.status == "conflict" and result.file_id == op.file_id
    assert result.path.startswith("n (conflict dev2 ") and result.path.endswith(").md")
    assert (root / result.path).read_bytes() == b"other\n"


def test_attachments_update_vs_update(server):
    root, _factory, _vault_id, committer = server
    op = Create(uuid.uuid7(), uuid.uuid7(), "img.png", "attachment", sha(b"v1"))
    committer.commit(op, "a", b"v1")
    push(committer, "a", *update(op.file_id, 1, b"v2"))
    [result] = push(committer, "b", *update(op.file_id, 1, b"v3"))
    assert result.status == "conflict" and result.path.endswith(").png")
    assert (root / "img.png").read_bytes() == b"v2" and (root / result.path).read_bytes() == b"v3"


# Server-side changes (§7) -----------------------------------------------------------------


def fs_changes(root, factory, vault_id):
    with factory() as s:
        return diff_scan(s, vault_id, scan(root), root=root)


def test_ingest_fs_changes(server):
    root, factory, vault_id, committer = server
    file_id = seed(committer)
    (root / "n.md").write_bytes(BASE + b"edited on the share\n")
    (root / "new.md").write_bytes(b"made by a script\n")
    results = ingest_fs_changes(committer, fs_changes(root, factory, vault_id))
    assert sorted(r.status for r in results) == ["applied", "applied"]
    (root / "n.md").rename(root / "renamed.md")
    [moved] = ingest_fs_changes(committer, fs_changes(root, factory, vault_id))
    assert (moved.file_id, moved.path, moved.revision) == (file_id, "renamed.md", 3)
    (root / "renamed.md").unlink()
    [deleted] = ingest_fs_changes(committer, fs_changes(root, factory, vault_id))
    assert deleted.revision == 4
    assert fs_changes(root, factory, vault_id) == []
    with factory() as s:
        devices = {e.device_id for e in changes(s, vault_id, None).entries if e.seq > 1}
    assert devices == {SERVER_FS}
    assert sorted(p.name for p in root.iterdir()) == ["new.md"]  # ingest wrote nothing


def test_ingest_moved_and_edited_file(server):
    root, factory, vault_id, committer = server
    note_id = uuid.uuid7()
    data = f"---\nid: {note_id}\n---\nbody\n".encode()
    committer.commit(Create(uuid.uuid7(), note_id, "a.md", "note", sha(data)), "seed", data)
    (root / "a.md").unlink()
    (root / "b.md").write_bytes(data + b"more\n")
    [move, edit] = ingest_fs_changes(committer, fs_changes(root, factory, vault_id))
    assert (move.path, edit.revision, edit.content_hash) == ("b.md", 3, sha(data + b"more\n"))
