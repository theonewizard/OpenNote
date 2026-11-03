"""The vault watcher: debounced detection, loop suppression, reconciliation (storage §5)."""

import hashlib
import os
import threading
import time

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.notes.identity import FsChange
from app.notes.models import File
from app.vaults.paths import casefold_key, classify
from app.vaults.registry import open_vault
from app.vaults.watch import VaultWatcher


class Recorder:
    """on_changes for the tests: records every change and applies it to `files`, as
    ingest (Task 14) will, so later scans compare against the new state."""

    def __init__(self, factory: sessionmaker[Session], vault_id) -> None:
        self.factory, self.vault_id = factory, vault_id
        self.changes: list[FsChange] = []
        self.cond = threading.Condition()

    def __call__(self, changes: list[FsChange]) -> None:
        with self.factory.begin() as s:
            for c in changes:
                if c.kind == "create":
                    s.add(
                        File(
                            file_id=c.file_id,
                            vault_id=self.vault_id,
                            path=c.path,
                            path_key=casefold_key(c.path),
                            kind=classify(c.path),
                            size=0,
                            content_hash=c.content_hash,
                        )
                    )
                elif c.kind == "update":
                    s.get(File, c.file_id).content_hash = c.content_hash
                elif c.kind == "move":
                    row = s.get(File, c.file_id)
                    row.path, row.path_key = c.new_path, casefold_key(c.new_path)
                    row.content_hash = c.content_hash
                else:
                    s.get(File, c.file_id).deleted = True
        with self.cond:
            self.changes.extend(changes)
            self.cond.notify_all()

    def wait_for(self, kind: str, path: str, timeout: float = 2.0) -> FsChange:
        def find():
            for c in self.changes:
                if c.kind == kind and path in (c.path, c.new_path):
                    return c
            return None

        with self.cond:
            assert self.cond.wait_for(find, timeout), f"no {kind} {path} in {self.changes}"
            return find()

    def clear(self) -> None:
        with self.cond:
            self.changes.clear()


@pytest.fixture
def watched(obsidian_vault, engine):
    factory = sessionmaker(engine)
    with factory.begin() as s:
        vault_id = open_vault(s, obsidian_vault)
    recorder = Recorder(factory, vault_id)
    watcher = VaultWatcher(obsidian_vault, vault_id, factory, recorder, debounce_s=0.5)
    watcher.start()  # the initial reconciliation registers every existing file
    recorder.wait_for("create", "Welcome.md")
    recorder.clear()
    yield obsidian_vault, watcher, recorder
    watcher.stop()


def test_external_create_edit_move_delete_detected_within_2s(watched):
    root, _, recorder = watched
    (root / "New.md").write_text("one\n")
    created = recorder.wait_for("create", "New.md")
    (root / "New.md").write_text("two\n")
    assert recorder.wait_for("update", "New.md").file_id == created.file_id
    os.rename(root / "New.md", root / "Projects" / "Moved.md")
    moved = recorder.wait_for("move", "Projects/Moved.md")
    assert (moved.file_id, moved.path) == (created.file_id, "New.md")
    (root / "Projects" / "Moved.md").unlink()
    assert recorder.wait_for("delete", "Projects/Moved.md").file_id == created.file_id


def test_own_write_is_suppressed(watched):
    root, watcher, recorder = watched
    data = b"written by OpenNote\n"
    watcher.note_own_write("Welcome.md", "sha256:" + hashlib.sha256(data).hexdigest())
    (root / "Welcome.md").write_bytes(data)
    (root / "Marker.md").write_text("m\n")  # a later external change shows the scan ran
    recorder.wait_for("create", "Marker.md")
    assert not [c for c in recorder.changes if c.path == "Welcome.md"]
    (root / "Welcome.md").write_bytes(b"external after own write\n")
    recorder.wait_for("update", "Welcome.md")


def test_overflow_triggers_reconcile(watched):
    root, watcher, recorder = watched
    watcher._observer.unschedule_all()  # events are now dropped, as after an overflow
    (root / "Missed.md").write_text("missed\n")
    time.sleep(0.7)
    assert recorder.changes == []
    watcher.on_overflow()  # the observer reported an overflow: reconcile in full
    recorder.wait_for("create", "Missed.md")


def test_dead_observer_triggers_reconcile_and_restart(watched):
    root, watcher, recorder = watched
    watcher._observer.stop()  # the observer died (watchdog's emitter raised)
    watcher._observer.join()
    (root / "WhileDead.md").write_text("x\n")
    recorder.wait_for("create", "WhileDead.md", timeout=3.0)
    (root / "AfterRestart.md").write_text("y\n")
    recorder.wait_for("create", "AfterRestart.md")


def test_stale_temp_removed(obsidian_vault, engine):
    stale = obsidian_vault / "Projects" / ".Plan.md.abc.opennote-tmp"
    stale.write_bytes(b"left by a crash")
    old = time.time_ns() - 2 * 3600 * 10**9
    os.utime(stale, ns=(old, old))
    factory = sessionmaker(engine)
    with factory.begin() as s:
        vault_id = open_vault(s, obsidian_vault)
    watcher = VaultWatcher(obsidian_vault, vault_id, factory, lambda changes: None)
    watcher.start()
    try:
        assert not stale.exists()
    finally:
        watcher.stop()


def test_own_write_recorded_before_the_file_lands_is_still_suppressed(watched):
    root, watcher, recorder = watched
    data = b"announced first\n"
    watcher.note_own_write("Welcome.md", "sha256:" + hashlib.sha256(data).hexdigest())
    (root / "Other.md").write_text("o\n")  # a scan runs before OpenNote's write lands
    recorder.wait_for("create", "Other.md")
    (root / "Welcome.md").write_bytes(data)
    (root / "Marker.md").write_text("m\n")
    recorder.wait_for("create", "Marker.md")
    assert not [c for c in recorder.changes if c.path == "Welcome.md"]
