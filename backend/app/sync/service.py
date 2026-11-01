"""Push, pull and snapshot over the Committer, and ingestion of changes made directly
on the server's vault (sync protocol §4, §5, §7)."""

import hashlib
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
from app.vaults.fsio import read_file
from app.vaults.paths import classify

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


def snapshot(session: Session, vault_id: uuid.UUID) -> list[ChangeEntry]:
    """The current revision of every live file, for a full reconcile."""
    rows = session.scalars(
        select(Revision)
        .join(File, (File.file_id == Revision.file_id) & (File.revision == Revision.revision))
        .where(Revision.vault_id == vault_id, ~File.deleted)
        .order_by(Revision.path)
    ).all()
    return [_entry(r) for r in rows]


def ingest_fs_changes(committer: Committer, fs_changes: list[FsChange]) -> list[OpResult]:
    """Commit changes found on the server's vault as `server-fs` operations, each based
    on the file's last known revision (sync §7)."""
    results = []
    for change in fs_changes:
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
        return [(Delete(uuid.uuid7(), file_id, revision), None)] if row else []
    try:
        blob = read_file(committer.root_fd, path)
    except FileNotFoundError:
        return []  # gone again; the next scan reports it
    content = "sha256:" + hashlib.sha256(blob).hexdigest()
    if change.kind == "create":
        return [(Create(uuid.uuid7(), file_id, path, classify(path), content), blob)]
    if row is None:
        return []
    ops: list[tuple[Operation, bytes | None]] = []
    if change.kind == "move":
        ops.append((Move(uuid.uuid7(), file_id, revision, path), None))
        revision += 1
    if content != known_hash:
        ops.append((Update(uuid.uuid7(), file_id, revision, content), blob))
    return ops
