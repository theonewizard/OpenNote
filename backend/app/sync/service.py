"""Push, pull and snapshot over the Committer, and ingestion of changes made directly
on the server's vault (sync protocol §4, §5, §7)."""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.notes.identity import FsChange
from app.notes.models import File
from app.sync.commit import SERVER_FS, Committer, Create, Delete, Move, Operation, OpResult, Update
from app.sync.cursor import RETENTION_SEQ_WINDOW, CursorExpired, decode_cursor, encode_cursor
from app.sync.models import Revision
from app.vaults.fsio import hash_path
from app.vaults.paths import classify
from app.vaults.scan import MAX_NOTE_BYTES

MAX_PUSH_OPS = 100


@dataclass(frozen=True)
class ChangeEntry:
    seq: int
    file_id: uuid.UUID
    revision: int
    path: str
    kind: str
    content_hash: str | None
    size: int
    deleted: bool
    device_id: str
    op: str


@dataclass(frozen=True)
class ChangesPage:
    entries: list[ChangeEntry]
    next_cursor: str
    has_more: bool


def _entry(r: Revision) -> ChangeEntry:
    return ChangeEntry(
        r.seq,
        r.file_id,
        r.revision,
        r.path,
        r.kind,
        r.content_hash,
        r.size,
        r.deleted,
        r.device_id,
        r.op,
    )


def push(
    committer: Committer, device_id: str, ops: Sequence[Operation], blobs: Mapping[str, bytes]
) -> list[OpResult]:
    """Commit each operation in order, independently; one result per operation."""
    if len(ops) > MAX_PUSH_OPS:
        raise ValueError(f"at most {MAX_PUSH_OPS} operations per push")
    return [
        committer.commit(op, device_id, blobs.get(getattr(op, "content_hash", None) or ""))
        for op in ops
    ]


def changes(
    session: Session, vault_id: uuid.UUID, cursor: str | None, limit: int = 500
) -> ChangesPage:
    """Revisions after `cursor`, in seq order. CursorExpired beyond the retention window."""
    after = decode_cursor(cursor, vault_id) if cursor else 0
    last = session.scalar(select(func.max(Revision.seq)).where(Revision.vault_id == vault_id))
    if cursor and last is not None and after < last - RETENTION_SEQ_WINDOW:
        raise CursorExpired("cursor is older than the retention window")
    rows = session.scalars(
        select(Revision)
        .where(Revision.vault_id == vault_id, Revision.seq > after)
        .order_by(Revision.seq)
        .limit(limit + 1)
    ).all()
    page = [_entry(r) for r in rows[:limit]]
    next_seq = page[-1].seq if page else after
    return ChangesPage(page, encode_cursor(vault_id, next_seq), len(rows) > limit)


def snapshot(
    session: Session, vault_id: uuid.UUID, after: str | None = None, limit: int | None = None
) -> list[ChangeEntry]:
    """The current revision of every live file, for a full reconcile, ordered by path
    (bytewise): the page after path `after`, of at most `limit` files."""
    path = Revision.path.collate("C")
    query = (
        select(Revision)
        .join(File, (File.file_id == Revision.file_id) & (File.revision == Revision.revision))
        .where(Revision.vault_id == vault_id, ~File.deleted)
        .order_by(path)
        .limit(limit)
    )
    if after is not None:
        query = query.where(path > after)
    return [_entry(r) for r in session.scalars(query).all()]


def last_seq(session: Session, vault_id: uuid.UUID) -> int:
    seq = session.scalar(select(func.max(Revision.seq)).where(Revision.vault_id == vault_id))
    return seq or 0


def ingest_fs_changes(committer: Committer, fs_changes: list[FsChange]) -> list[OpResult]:
    """Commit changes found on the server's vault as `server-fs` operations, each based
    on the file's last known revision (sync §7).

    Disk and registry are read under the vault lock, after recovering the changed files
    whose last revision is not on disk yet (written_revision behind revision):
    a write another process has committed but not yet put on disk is finished, not read
    back as an edit that would undo it."""
    with committer._vault_lock():
        changed = {c.file_id for c in fs_changes if c.file_id is not None}
        with committer.session_factory() as s:
            unwritten = s.scalars(
                select(File.file_id).where(
                    File.file_id.in_(changed),
                    func.coalesce(File.written_revision, 0) < File.revision,
                )
            )
            pending = set(committer.unsettled) | set(unwritten)
        if pending:
            committer.recover(pending)
        results = []
        for change in fs_changes:
            if change.file_id in committer.unsettled:
                continue  # disk and registry differ because our write failed, not an edit
            for op, blob in _ops_for(committer, change):
                results.append(committer.commit(op, SERVER_FS, blob))
        return results


def _ops_for(committer: Committer, change: FsChange) -> list[tuple[Operation, bytes | None]]:
    if change.file_id is None:
        return []
    file_id, path = change.file_id, change.new_path or change.path
    with committer.session_factory() as s:
        row = s.get(File, file_id)
        revision, known_hash = (row.revision, row.content_hash) if row else (0, None)
    if change.kind == "delete":
        if row is None or hash_path(committer.root_fd, path) is not None:
            return []  # back since the scan (a recovered write, or a re-save)
        return [(Delete(uuid.uuid7(), file_id, revision), None)]
    try:  # streamed into the history store: the commit reads it there (P5-02)
        content = committer._store_vault_file(path)
    except FileNotFoundError:
        return []  # gone again; the next scan reports it
    if change.kind == "create":
        kind = classify(path)
        if kind == "note" and committer.history.size(content) > MAX_NOTE_BYTES:
            kind = "attachment"  # opaque, as the scan classifies it
        return [(Create(uuid.uuid7(), file_id, path, kind, content), None)]
    if row is None:
        return []
    ops: list[tuple[Operation, bytes | None]] = []
    if change.kind == "move":
        ops.append((Move(uuid.uuid7(), file_id, revision, path), None))
        revision += 1
    if content != known_hash:
        ops.append((Update(uuid.uuid7(), file_id, revision, content), None))
    return ops
