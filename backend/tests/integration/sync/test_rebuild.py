"""P8-05: the database's vault rows rebuilt from the history store after losing them."""

import json
import os
import uuid

import pytest
from sqlalchemy import delete, select

from app.auth.admin import create_user
from app.notes.models import File, Note, NoteLink, NoteTag, SearchDocument
from app.sync import rebuild
from app.sync.commit import Create, Delete, Move, Update
from app.sync.history import HistoryCorrupt
from app.sync.models import Revision, VaultSeq
from app.sync.service import ingest_fs_changes
from app.vaults.config import VaultConfig, write_config
from app.vaults.fsio import open_root
from app.vaults.models import Vault, VaultMember
from tests.integration.sync.conftest import create, sha
from tests.integration.sync.test_service import fs_changes

PIC = b"\x89PNG\r\n"


def _seed(c):
    """Creates, an update, a move, a delete, a path reused after a delete, an attachment."""
    c.commit(Create(uuid.uuid7(), uuid.uuid7(), "pic.png", "attachment", sha(PIC)), "dev", PIC)
    a, data = create("A.md", b"---\ntags: [x]\n---\n[[B]] ![[pic.png]] #inline\n")
    c.commit(a, "dev", data)
    b, data = create("B.md", b"first\n")
    c.commit(b, "dev", data)
    c.commit(Update(uuid.uuid7(), b.file_id, 1, sha(b"second\n")), "dev", b"second\n")
    c.commit(Move(uuid.uuid7(), b.file_id, 2, "sub/B.md"), "dev", None)
    gone, data = create("Gone.md", b"bye\n")
    c.commit(gone, "dev", data)
    c.commit(Delete(uuid.uuid7(), gone.file_id, 1), "dev", None)
    again, data = create("Gone.md", b"back\n")
    c.commit(again, "dev", data)


def _state(s, vault_id):
    """Everything the rebuild must restore, keyed so that row order does not matter."""
    files = s.scalars(select(File).where(File.vault_id == vault_id)).all()
    ids = [f.file_id for f in files]
    cols = lambda row: {  # noqa: E731
        k: v for k, v in vars(row).items() if not k.startswith("_") and k != "tsv"
    }
    return {
        "files": sorted(map(str, (sorted(cols(f).items()) for f in files))),
        "revisions": sorted(
            map(
                str,
                (
                    sorted(cols(r).items())
                    for r in s.scalars(select(Revision).where(Revision.vault_id == vault_id))
                ),
            )
        ),
        "seq": s.get(VaultSeq, vault_id).last_seq,
        **{
            model.__tablename__: sorted(
                map(
                    str,
                    (
                        sorted(cols(r).items())
                        for r in s.scalars(select(model).where(model.file_id.in_(ids)))
                    ),
                )
            )
            for model in (Note, NoteTag, NoteLink, SearchDocument)
        },
    }


def _lose_database(factory, vault_id):
    with factory.begin() as s:
        s.execute(delete(Vault).where(Vault.id == vault_id))  # cascades to every vault row


def test_rebuild_restores_every_vault_row(world):
    root, factory, history, vault_id, make = world
    _seed(make())
    with factory() as s:
        before = _state(s, vault_id)
    _lose_database(factory, vault_id)

    with factory.begin() as s:
        rebuild.rebuild_vault(s, history, vault_id, root, "vault")
    with factory() as s:
        assert _state(s, vault_id) == before
        assert s.get(Vault, vault_id).root_path == str(root)


def test_the_watcher_then_commits_what_the_folder_holds(world):
    """Edits made while the database was down become new revisions, never reverted."""
    root, factory, history, vault_id, make = world
    _seed(make())
    _lose_database(factory, vault_id)
    (root / "A.md").write_bytes(b"edited while the database was down\n")
    (root / "New.md").write_bytes(b"new while down\n")
    with factory.begin() as s:
        rebuild.rebuild_vault(s, history, vault_id, root, "vault")

    c = make()
    c.recover()  # what the API and the watcher do first (Committers.get)
    ingest_fs_changes(c, fs_changes(root, factory, vault_id))
    assert fs_changes(root, factory, vault_id) == []
    with factory() as s:
        live = {
            f.path: (f.revision, f.content_hash) for f in s.scalars(select(File)) if not f.deleted
        }
    assert live["A.md"] == (2, sha(b"edited while the database was down\n"))
    assert live["New.md"] == (1, sha(b"new while down\n"))
    assert (root / "A.md").read_bytes() == b"edited while the database was down\n"


def test_plan_finds_folders_by_config_then_by_files(world, tmp_path, engine):
    root, factory, history, vault_id, make = world
    _seed(make())
    _lose_database(factory, vault_id)
    vault_root, history_root = tmp_path, tmp_path / "history"
    (tmp_path / "empty").mkdir()
    (history_root / "not-a-vault").mkdir()

    [p] = rebuild.plan(factory, history_root, vault_root, {})
    assert (p.vault_id, p.folder, p.name, p.revisions, p.live) == (vault_id, root, None, 8, 4)
    assert p.note == "100% of the live files"

    root_fd = open_root(root)
    try:
        write_config(root_fd, VaultConfig(1, vault_id, "Work"))
    finally:
        os.close(root_fd)
    [p] = rebuild.plan(factory, history_root, vault_root, {})
    assert (p.folder, p.name, p.note) == (root, "Work", "config")

    other = uuid.uuid4()
    (history_root / str(other) / "log").mkdir(parents=True)
    plans = {p.vault_id: p for p in rebuild.plan(factory, history_root, vault_root, {})}
    assert plans[other].folder is None and "--map" in plans[other].note
    mapped = rebuild.plan(factory, history_root, vault_root, {other: tmp_path / "empty"})
    assert {p.vault_id: p.folder for p in mapped}[other] == tmp_path / "empty"

    with factory.begin() as s:
        rebuild.rebuild_vault(s, history, vault_id, root, "Work")
    plans = {p.vault_id: p for p in rebuild.plan(factory, history_root, vault_root, {})}
    assert plans[vault_id].folder is None and plans[vault_id].note == "already in the database"


def test_a_repeated_sequence_number_is_refused(world):
    root, factory, history, vault_id, make = world
    _seed(make())
    _lose_database(factory, vault_id)
    [log] = (history.root / "log").glob("*.jsonl")
    first = log.read_bytes().split(b"\n")[0]
    with open(log, "ab") as fh:
        fh.write(first + b"\n")
    with pytest.raises(HistoryCorrupt), factory.begin() as s:
        rebuild.rebuild_vault(s, history, vault_id, root, "vault")


def test_cli_rebuilds_with_an_owner(world, tmp_path, monkeypatch, make_settings, capsys):
    root, factory, _history, vault_id, make = world
    _seed(make())
    _lose_database(factory, vault_id)
    settings = make_settings(vault_root=tmp_path, history_root=tmp_path / "history")
    monkeypatch.setattr(rebuild, "get_settings", lambda: settings)
    with factory.begin() as s:
        admin_id = create_user(
            s, "admin", "correct horse battery", admin=True, display_name=None
        ).id

    assert rebuild.main(["--dry-run"]) == 0
    [line] = capsys.readouterr().out.splitlines()
    assert json.loads(line)["action"] == "plan"
    with factory() as s:
        assert s.get(Vault, vault_id) is None

    assert rebuild.main(["--owner", "nobody"]) == 1
    assert rebuild.main(["--owner", "ADMIN"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["action"] == "rebuilt"
    with factory() as s:
        assert s.get(VaultMember, (vault_id, admin_id)).role == "owner"
        assert s.get(Vault, vault_id).name == root.name
    assert rebuild.main([]) == 0  # a second run skips the vault already there
    assert json.loads(capsys.readouterr().out)["action"] == "skip"
