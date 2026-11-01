"""Watch a vault for external changes (storage contract §5).

Filesystem events only say *that* something changed. After `debounce_s` without events
the watcher rescans the vault (hashing only files whose size, mtime or inode changed)
and hands `diff_scan`'s changes to `on_changes`. A full reconciliation, which also clears
stale in-flight temp files, runs at start, every `rescan_s`, after an overflow and when
the observer dies. Changes that only repeat OpenNote's own writes are dropped (I5).
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from app.notes.identity import FsChange, diff_scan
from app.vaults.fsio import clean_stale_temps
from app.vaults.paths import classify
from app.vaults.scan import ScannedFile, scan

log = logging.getLogger(__name__)

STALE_TEMP_NS = 3600 * 10**9
_TICK_S = 0.05


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "VaultWatcher") -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed_no_write"):
            return
        self.watcher._event(event)


class VaultWatcher:
    def __init__(
        self,
        root: Path,
        vault_id: uuid.UUID,
        session_factory: sessionmaker[Session],
        on_changes: Callable[[list[FsChange]], None],
        *,
        debounce_s: float = 0.5,
        rescan_s: float = 900,
    ) -> None:
        self.root, self.vault_id = root, vault_id
        self.session_factory, self.on_changes = session_factory, on_changes
        self.debounce_s, self.rescan_s = debounce_s, rescan_s
        self._lock = threading.Lock()
        self._own: dict[str, str] = {}  # path -> hash OpenNote itself last wrote there
        self._known: dict[str, ScannedFile] = {}
        self._first_event: float | None = None
        self._last_event = 0.0
        self._full = threading.Event()
        self._stop = threading.Event()
        self._observer: BaseObserver | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start watching, then reconcile in full before returning."""
        self._observer = self._start_observer()
        self._reconcile(full=True)
        self._thread = threading.Thread(target=self._run, name="vault-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def note_own_write(self, path: str, content_hash: str) -> None:
        """OpenNote wrote `content_hash` to `path`: a change to exactly that is not news."""
        with self._lock:
            self._own[path] = content_hash

    def on_overflow(self) -> None:
        """Events may have been dropped: reconcile the whole vault."""
        self._full.set()

    def _start_observer(self) -> BaseObserver:
        observer = Observer()
        observer.schedule(_Handler(self), str(self.root), recursive=True)
        observer.start()
        return observer

    def _event(self, event: FileSystemEvent) -> None:
        paths = [p for p in (event.src_path, event.dest_path) if p]
        rels = [str(Path(str(p)).relative_to(self.root)) for p in paths]
        if all(r != "." and classify(r) in ("ignored", "temp") for r in rels):
            return
        with self._lock:
            now = time.monotonic()
            self._first_event = self._first_event or now
            self._last_event = now

    def _observer_alive(self) -> bool:
        obs = self._observer
        return obs is not None and obs.is_alive() and all(e.is_alive() for e in obs.emitters)

    def _run(self) -> None:
        last_full = time.monotonic()
        while not self._stop.wait(_TICK_S):
            if not self._observer_alive():
                log.warning("vault observer stopped; restarting and reconciling")
                self._observer = self._start_observer()
                self._full.set()
            now = time.monotonic()
            with self._lock:
                first, last = self._first_event, self._last_event
            due = first is not None and (
                now - last >= self.debounce_s or now - first >= 4 * self.debounce_s
            )
            if self._full.is_set() or now - last_full >= self.rescan_s:
                self._reconcile(full=True)
                last_full = now
            elif due:
                self._reconcile(full=False)

    def _reconcile(self, *, full: bool) -> None:
        with self._lock:
            self._first_event = None
        if full:
            self._full.clear()
        try:
            if full:
                clean_stale_temps(self.root, STALE_TEMP_NS)
            scanned = list(scan(self.root, self._known))
            self._known = {f.path: f for f in scanned}
            with self.session_factory() as session:
                changes = diff_scan(session, self.vault_id, scanned, root=self.root)
            changes = self._drop_own(changes)
            if changes:
                self.on_changes(changes)
        except Exception:
            log.exception("vault reconciliation failed; retrying on the next change")

    def _drop_own(self, changes: list[FsChange]) -> list[FsChange]:
        with self._lock:
            kept = [
                c
                for c in changes
                if c.kind == "delete" or self._own.get(c.new_path or c.path) != c.content_hash
            ]
            reported = {c.new_path or c.path for c in kept}
            changed = {c.new_path or c.path for c in changes}
            for path, own in list(self._own.items()):
                on_disk = self._known.get(path)
                caught_up = path not in changed and on_disk and on_disk.content_hash == own
                if caught_up or path in reported:  # registry has it, or the disk moved on
                    del self._own[path]
            return kept
