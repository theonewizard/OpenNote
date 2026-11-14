"""`python -m app.vaults`: watch every registered vault and commit what changes on disk
outside OpenNote (storage contract §5, sync §7).

One instance runs per deployment: it holds a PostgreSQL advisory lock, so a second copy
waits until the first is gone. Every `POLL_S` it starts a watcher for each new vault (the
watcher's first full scan imports the notes already in the folder) and stops the watchers
of deleted vaults. Once a day, starting at startup, it applies retention to every vault
(P5-07). SIGTERM or SIGINT stops it.
"""

import functools
import logging
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from types import FrameType

from sqlalchemy import select, text

from app.api.deps import Committers
from app.core.config import SettingsError, get_settings
from app.core.logging import configure_logging
from app.sync.retention import prune
from app.sync.service import ingest_fs_changes
from app.vaults.models import Vault
from app.vaults.watch import VaultWatcher

log = logging.getLogger(__name__)

POLL_S = 5.0
RETENTION_EVERY_S = 24 * 3600
_INSTANCE_LOCK = "opennote-vault-watcher"


def sync_watchers(committers: Committers, watchers: dict[uuid.UUID, VaultWatcher]) -> None:
    """Start a watcher for every live vault that has none; stop those of deleted vaults."""
    with committers.factory() as s:
        rows = s.execute(select(Vault.id, Vault.root_path).where(Vault.deleted_at.is_(None)))
        live = {vault_id: root for vault_id, root in rows}
    for vault_id in watchers.keys() - live.keys():
        watchers.pop(vault_id).stop()
    for vault_id, root in live.items():
        if vault_id in watchers:
            continue
        try:
            committer = committers.get(vault_id, root)
            watcher = VaultWatcher(
                Path(root),
                vault_id,
                committers.factory,
                functools.partial(ingest_fs_changes, committer),
            )
            watcher.start()
        except Exception:
            log.exception("cannot watch vault; retrying", extra={"vault_id": str(vault_id)})
            continue
        watchers[vault_id] = watcher
        log.info("watching vault", extra={"vault_id": str(vault_id)})


def apply_retention(committers: Committers) -> None:
    """Prune every live vault; one vault's failure does not stop the others."""
    settings = committers.settings
    with committers.factory() as s:
        rows = s.execute(select(Vault.id, Vault.root_path).where(Vault.deleted_at.is_(None)))
        live = {vault_id: root for vault_id, root in rows}
    for vault_id, root in live.items():
        try:
            prune(
                committers.get(vault_id, root),
                keep_all_days=settings.history_keep_all_days,
                keep_daily_days=settings.history_keep_daily_days,
                tombstone_days=settings.tombstone_retention_days,
            )
        except Exception:
            log.exception("retention failed; next run retries", extra={"vault_id": str(vault_id)})


def run(committers: Committers, stop: threading.Event) -> None:
    watchers: dict[uuid.UUID, VaultWatcher] = {}
    with committers.engine.connect() as conn:
        # Session-level: unlocked below, or by PostgreSQL when the process dies.
        lock = text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))")
        while not conn.execute(lock, {"k": _INSTANCE_LOCK}).scalar():
            conn.commit()
            if stop.wait(POLL_S):
                return
        conn.commit()
        log.info("vault watcher active")
        next_retention = time.monotonic()
        try:
            while not stop.is_set():
                try:
                    sync_watchers(committers, watchers)
                except Exception:
                    log.exception("cannot list vaults; retrying")
                if time.monotonic() >= next_retention and not stop.is_set():
                    next_retention = time.monotonic() + RETENTION_EVERY_S
                    apply_retention(committers)
                stop.wait(POLL_S)
        finally:
            for watcher in watchers.values():
                watcher.stop()
            unlock = text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))")
            conn.execute(unlock, {"k": _INSTANCE_LOCK})
            conn.commit()


def main() -> None:
    try:
        settings = get_settings()
    except SettingsError as exc:
        sys.exit(f"OpenNote vault watcher cannot start: {exc}")
    configure_logging(settings.log_level)
    stop = threading.Event()

    def _stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    committers = Committers(settings)
    try:
        run(committers, stop)
    finally:
        committers.close()


if __name__ == "__main__":
    main()
