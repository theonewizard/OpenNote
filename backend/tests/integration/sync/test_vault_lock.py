"""Commits to one vault are serialized through the vault write, not only through the
database step (Phase 2 plan, Task 2, R-P2-009). Without that, a second commit that runs
while the first sits between its database and vault steps can leave the vault holding
an older revision than the database."""

import threading
import uuid

from sqlalchemy import select

from app.notes.models import File
from app.sync.commit import Update
from tests.integration.sync.conftest import create, sha

V2 = b"one\ntwo\nthree\nfour\nfive\nsix\n"
V3 = b"zero\none\ntwo\nthree\nfour\nfive\nsix\n"


def test_second_commit_waits_for_the_first_vault_write(world):
    root, factory, _history, _vault_id, make = world
    op, data = create()
    make().commit(op, "dev-a", data)
    file_id = op.file_id

    paused, resume = threading.Event(), threading.Event()

    def hold_after_db(step: str) -> None:
        if step == "db" and not paused.is_set():
            paused.set()
            resume.wait(10)

    first = threading.Thread(
        target=lambda: make(crash=hold_after_db).commit(
            Update(uuid.uuid7(), file_id, 1, sha(V2)), "dev-a", V2
        )
    )
    first.start()
    assert paused.wait(10)
    second_done = threading.Event()

    def second_commit() -> None:
        make().commit(Update(uuid.uuid7(), file_id, 2, sha(V3)), "dev-b", V3)
        second_done.set()

    second = threading.Thread(target=second_commit)
    second.start()
    # The second commit must not finish while the first still holds the vault.
    assert not second_done.wait(1.0)
    resume.set()
    first.join(10)
    second.join(10)
    assert second_done.is_set()

    assert (root / "n.md").read_bytes() == V3
    with factory() as s:
        row = s.scalars(select(File).where(File.file_id == file_id)).one()
        assert (row.revision, row.written_revision, row.content_hash) == (3, 3, sha(V3))
