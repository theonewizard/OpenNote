"""Retention (design D6, sync protocol §2.1, P5-07): prune old revisions, expired
tombstones, resolved conflicts and stored operation results, then remove history objects
no revision refers to. The vault watcher runs `prune` for every vault once a day.

Never removed: a file's current revision, and the revisions an unremoved conflict names
(its base, the revision it was raised against, and the copy's first revision)."""

import datetime as dt
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    CursorResult,
    Executable,
    Uuid,
    bindparam,
    delete,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.notes.models import File
from app.sync.commit import Committer
from app.sync.models import ClientOp, Conflict, Revision, VaultSeq

log = logging.getLogger(__name__)

# Unreferenced objects, unfinished uploads and temporary files younger than this stay:
# a blob is uploaded before the push that commits it.
GRACE = dt.timedelta(days=7)

# Revisions that are neither current nor named by a conflict, ranked newest first within
# their file and UTC day; a revision past keep-daily goes, one past keep-all goes unless
# it is the last of its day.
_PRUNE_REVISIONS = text("""
    WITH ranked AS (
        SELECT r.seq, r.file_id, r.revision, r.committed_at, r.revision < f.revision AS old,
               row_number() OVER (
                   PARTITION BY r.file_id, (r.committed_at AT TIME ZONE 'UTC')::date
                   ORDER BY r.revision DESC) AS nth
        FROM revisions r JOIN files f ON f.file_id = r.file_id
        WHERE r.vault_id = :vault
    )
    DELETE FROM revisions
    WHERE vault_id = :vault AND seq IN (
        SELECT x.seq FROM ranked x
        WHERE x.old
          AND (x.committed_at < :daily OR (x.committed_at < :all AND x.nth > 1))
          AND NOT EXISTS (
              SELECT 1 FROM conflicts c
              WHERE c.vault_id = :vault AND (
                  (c.file_id = x.file_id AND x.revision IN (c.base_revision, c.their_revision))
                  OR (c.copy_file_id = x.file_id AND x.revision = 1))))
""")


def prune(
    committer: Committer,
    *,
    keep_all_days: int,
    keep_daily_days: int,
    tombstone_days: int,
    now: dt.datetime | None = None,
) -> dict[str, int]:
    """Apply retention to the committer's vault under its lock; return what was removed."""
    now = now or dt.datetime.now(dt.UTC)
    tombstone_cut = now - dt.timedelta(days=tombstone_days)
    vault = committer.vault_id
    with committer._vault_lock():
        with committer.session_factory.begin() as s:
            # Serialize with commits, which lock this row too.
            s.execute(select(VaultSeq).where(VaultSeq.vault_id == vault).with_for_update())
            removed = {
                "conflicts": _delete(
                    s,
                    delete(Conflict).where(
                        Conflict.vault_id == vault,
                        Conflict.status != "open",
                        func.coalesce(Conflict.resolved_at, Conflict.created_at) < tombstone_cut,
                    ),
                ),
                "files": _expire_tombstones(s, committer, tombstone_cut),
                "revisions": _delete(
                    s,
                    _PRUNE_REVISIONS,
                    {
                        "vault": vault,
                        "all": now - dt.timedelta(days=keep_all_days),
                        "daily": now - dt.timedelta(days=keep_daily_days),
                    },
                ),
                "client_ops": _delete(
                    s,
                    delete(ClientOp).where(
                        ClientOp.vault_id == vault, ClientOp.created_at < tombstone_cut
                    ),
                ),
            }
        with committer.session_factory() as s:
            referenced: set[str | None] = set(
                s.scalars(
                    select(Revision.content_hash)
                    .where(Revision.vault_id == vault, Revision.content_hash.is_not(None))
                    .distinct()
                )
            )
        removed["objects"] = _collect_garbage(committer.history.root, referenced, now)
    if any(removed.values()):
        log.info("retention applied", extra={"vault_id": str(vault), **removed})
    return removed


def _delete(s: Session, statement: Executable, params: Mapping[str, Any] | None = None) -> int:
    return cast(CursorResult[Any], s.execute(statement, params or {})).rowcount


def _expire_tombstones(s: Session, committer: Committer, cut: dt.datetime) -> int:
    """Forget deleted files whose tombstone is older than `cut` and that no conflict
    names: all their revisions and the registry row. Cursors from before the newest
    such tombstone can no longer learn of it, so they expire (the horizon)."""
    vault = committer.vault_id
    named = (
        select(Conflict.file_id)
        .where(Conflict.vault_id == vault)
        .union(select(Conflict.copy_file_id).where(Conflict.vault_id == vault))
    )
    expired = s.execute(
        select(File.file_id, Revision.seq)
        .join(Revision, (Revision.file_id == File.file_id) & (Revision.revision == File.revision))
        .where(
            File.vault_id == vault,
            File.deleted,
            Revision.committed_at < cut,
            File.file_id.not_in(named),
        )
    ).all()
    if not expired:
        return 0
    ids = bindparam("ids", [file_id for file_id, _ in expired], type_=ARRAY(Uuid()))
    s.execute(delete(Revision).where(Revision.vault_id == vault, Revision.file_id == func.any(ids)))
    s.execute(delete(File).where(File.file_id == func.any(ids)))
    horizon = bindparam("horizon", max(seq for _, seq in expired), type_=BigInteger())
    s.execute(
        update(VaultSeq)
        .where(VaultSeq.vault_id == vault)
        .values(horizon_seq=func.greatest(VaultSeq.horizon_seq, horizon))
    )
    return len(expired)


def _collect_garbage(root: Path, referenced: set[str | None], now: dt.datetime) -> int:
    """Remove objects no revision refers to, unfinished uploads and temporary files, once
    they are older than GRACE."""
    cut = now.timestamp() - GRACE.total_seconds()
    removed = 0
    candidates = [*(root / "objects").glob("*/*"), *(root / "objects").glob(".*.tmp")]
    candidates += (root / "uploads").glob("*.part")
    for path in candidates:
        if not path.is_file():
            continue
        orphan = path.name.endswith((".tmp", ".part")) or (
            f"sha256:{path.parent.name}{path.name}" not in referenced
        )
        try:
            if orphan and path.stat().st_mtime < cut:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed
