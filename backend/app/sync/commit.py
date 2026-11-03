"""Committing sync operations (sync protocol §2.3, §3 and §6).

Every revision is made durable in this order: history object, PostgreSQL (the commit
point, serialized per vault by a row lock), JSONL log, vault file. `recover` repairs what a
crash between those steps leaves behind. A vault file changed by someone else is never
overwritten: its bytes are committed as an update from `server-fs` and merged.
"""

import dataclasses
import datetime as dt
import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.problems import PROBLEM_TYPE_BASE
from app.notes.index import index_file, remove_file
from app.notes.models import File, Note, NoteLink, NoteTag
from app.sync.history import HistoryStore, RevisionLogEntry
from app.sync.merge import conflict_copy_path, merge_note
from app.sync.models import ClientOp, Conflict, Revision, VaultSeq
from app.vaults.fsio import (
    ExternalChangeError,
    PathEscapeError,
    atomic_write,
    hash_path,
    move_to,
    read_file,
    rename_noreplace,
)
from app.vaults.paths import casefold_key, classify, validate
from app.vaults.scan import MAX_NOTE_BYTES

log = logging.getLogger(__name__)

SERVER_FS = "server-fs"  # the device id of changes made directly on the server's vault


@dataclass(frozen=True)
class Create:
    client_op_id: uuid.UUID
    file_id: uuid.UUID
    path: str
    kind: str
    content_hash: str


@dataclass(frozen=True)
class Update:
    client_op_id: uuid.UUID
    file_id: uuid.UUID
    base_revision: int
    content_hash: str


@dataclass(frozen=True)
class Move:
    client_op_id: uuid.UUID
    file_id: uuid.UUID
    base_revision: int
    new_path: str


@dataclass(frozen=True)
class Delete:
    client_op_id: uuid.UUID
    file_id: uuid.UUID
    base_revision: int


@dataclass(frozen=True)
class Restore:
    client_op_id: uuid.UUID
    file_id: uuid.UUID
    from_revision: int


Operation = Create | Update | Move | Delete | Restore
Status = Literal["applied", "merged", "conflict", "rejected", "duplicate"]


@dataclass(frozen=True)
class OpResult:
    """For `conflict`, the fields describe the conflict copy and `problem` names the
    original file; for `rejected`, `problem` is an RFC 9457 problem."""

    status: Status
    file_id: uuid.UUID
    revision: int | None
    seq: int | None
    content_hash: str | None
    path: str | None
    problem: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self) | {"file_id": str(self.file_id)}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> OpResult:
        return cls(**(data | {"file_id": uuid.UUID(data["file_id"])}))


@dataclass(frozen=True)
class State:
    """What a file looks like on disk: where, which bytes, or gone."""

    path: str
    content_hash: str | None
    deleted: bool


@dataclass
class _Rev:
    """A revision planned inside the transaction. `before` is what the vault is believed
    to hold for this file when the revision is materialized."""

    file_id: uuid.UUID
    revision: int
    path: str
    kind: str
    content_hash: str | None
    deleted: bool
    op: str
    size: int
    before: State | None
    seq: int = 0
    committed_at: str = ""

    @property
    def after(self) -> State:
        return State(self.path, self.content_hash, self.deleted)


class _Rejected(Exception):
    def __init__(self, status: int, slug: str, title: str) -> None:
        super().__init__(title)
        self.problem = {"type": PROBLEM_TYPE_BASE + slug, "title": title, "status": status}


def _entry(rev: _Rev | Revision, device_id: str, committed_at: str) -> RevisionLogEntry:
    return RevisionLogEntry(
        seq=rev.seq,
        file_id=rev.file_id,
        revision=rev.revision,
        path=rev.path,
        kind=rev.kind,
        content_hash=rev.content_hash,
        deleted=rev.deleted,
        device_id=device_id,
        op=rev.op,
        committed_at=committed_at,
    )


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Committer:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        history: HistoryStore,
        vault_root_fd: int,
        vault_id: uuid.UUID,
        *,
        crash: Callable[[str], None] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.session_factory, self.history = session_factory, history
        self.root_fd, self.vault_id = vault_root_fd, vault_id
        self.crash = crash or (lambda step: None)
        # Informational only (I6): committed_at and the day in conflict-copy names.
        self.clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self.recovery_dir = history.root / "recovery"  # outside the vault
        self.recovery_dir.mkdir(parents=True, exist_ok=True)
        # Files whose step 4 failed after the commit; recover() retries them before the
        # watcher's changes are ingested, so a missing write is never read as an edit.
        self.unsettled: set[uuid.UUID] = set()

    # The five steps --------------------------------------------------------------------

    def commit(self, op: Operation, device_id: str, blob: bytes | None) -> OpResult:
        with self.session_factory() as session:
            if prior := session.get(ClientOp, (self.vault_id, op.client_op_id)):
                return dataclasses.replace(OpResult.from_json(prior.result), status="duplicate")
        if isinstance(op, Create | Update):
            if blob is None or _sha(blob) != op.content_hash:
                problem = _Rejected(422, "blob-missing", "Blob missing or not matching").problem
                return OpResult("rejected", op.file_id, None, None, None, None, problem)
            self.history.put(blob)  # step 1
        self.crash("history")
        result, revs = self._commit_db(op, device_id, blob)  # step 2
        if not revs:
            return result
        self.crash("db")
        for rev in revs:  # step 3
            self.history.append_log(_entry(rev, device_id, rev.committed_at))
        self.crash("log")
        for rev in revs:  # step 4
            self._apply(rev.file_id, rev.revision, rev.before, rev.after)
        self.crash("vault")
        if result.status == "conflict" and device_id == SERVER_FS:
            self._restore_after_fs_conflict(op, result)
        self._index(revs)  # step 5 (the caller responds and publishes)
        return result

    def _restore_after_fs_conflict(self, op: Operation, result: OpResult) -> None:
        """The external bytes now live in the conflict copy: put the committed revision
        back at the file's path, where the external save had replaced it."""
        if isinstance(op, Create):  # the copy is the external file; ours is the original
            file_id = uuid.UUID((result.problem or {}).get("original_file_id", str(op.file_id)))
        elif isinstance(op, Update):
            file_id = op.file_id
        else:
            return
        with self.session_factory() as session:
            row = session.get(File, file_id)
            if row is None or row.deleted:
                return
            path, current, revision = row.path, row.content_hash, row.revision
        on_disk = State(path, op.content_hash, False)
        self._apply(file_id, revision, on_disk, State(path, current, False))

    def _commit_db(
        self, op: Operation, device_id: str, blob: bytes | None
    ) -> tuple[OpResult, list[_Rev]]:
        with self.session_factory.begin() as s:
            s.execute(
                pg_insert(VaultSeq)
                .values(vault_id=self.vault_id, last_seq=0)
                .on_conflict_do_nothing()
            )
            seq = s.scalars(
                select(VaultSeq).where(VaultSeq.vault_id == self.vault_id).with_for_update()
            ).one()
            if prior := s.get(ClientOp, (self.vault_id, op.client_op_id)):
                return dataclasses.replace(OpResult.from_json(prior.result), status="duplicate"), []
            now = self.clock()
            try:
                result, revs = self._plan(s, op, device_id, blob, now.date().isoformat())
            except _Rejected as rejected:
                result = OpResult("rejected", op.file_id, None, None, None, None, rejected.problem)
                revs = []
            for rev in revs:
                seq.last_seq += 1
                rev.seq, rev.committed_at = seq.last_seq, now.isoformat()
                s.add(
                    Revision(
                        vault_id=self.vault_id,
                        seq=rev.seq,
                        file_id=rev.file_id,
                        revision=rev.revision,
                        path=rev.path,
                        kind=rev.kind,
                        content_hash=rev.content_hash,
                        size=rev.size,
                        deleted=rev.deleted,
                        device_id=device_id,
                        op=rev.op,
                        committed_at=now,
                    )
                )
                self._update_file(s, rev)
            if revs and result.seq is None:
                result = dataclasses.replace(result, seq=revs[-1].seq)
            s.add(
                ClientOp(
                    vault_id=self.vault_id,
                    client_op_id=op.client_op_id,
                    result=result.to_json(),
                    seq=result.seq,
                )
            )
            return result, revs

    def _update_file(self, s: Session, rev: _Rev) -> None:
        row = s.get(File, rev.file_id)
        if row is None:
            row = File(file_id=rev.file_id, vault_id=self.vault_id, content_hash="")
            s.add(row)
        row.path, row.path_key, row.kind = rev.path, casefold_key(rev.path), rev.kind
        row.revision, row.deleted, row.size = rev.revision, rev.deleted, rev.size
        if rev.content_hash is not None:  # a tombstone keeps the last content hash
            row.content_hash = rev.content_hash
        s.flush()  # the partial unique index sees each path change in order

    # Preconditions and §6 rules --------------------------------------------------------

    def _live_at(self, s: Session, path: str) -> File | None:
        return s.scalars(
            select(File).where(
                File.vault_id == self.vault_id,
                File.path_key == casefold_key(path),
                ~File.deleted,
            )
        ).first()

    def _file(self, s: Session, file_id: uuid.UUID) -> File:
        row = s.get(File, file_id)
        if row is None or row.vault_id != self.vault_id:
            raise _Rejected(404, "file-not-found", "File not found")
        return row

    def _check_base(self, row: File, base: int) -> None:
        if not 1 <= base <= row.revision:
            raise _Rejected(409, "invalid-base-revision", "Base revision does not exist")

    def _check_path(self, path: str, kind: str) -> None:
        # A `.md` may also travel as an attachment: an oversized note is opaque (scan).
        expected = {classify(path)} | ({"attachment"} if classify(path) == "note" else set())
        if validate(path, note=kind == "note") or kind not in expected:
            raise _Rejected(422, "invalid-path", "Path is not valid for this file")

    def _revision(self, s: Session, file_id: uuid.UUID, revision: int) -> Revision | None:
        return s.scalars(
            select(Revision).where(Revision.file_id == file_id, Revision.revision == revision)
        ).first()

    def _plan(
        self, s: Session, op: Operation, device_id: str, blob: bytes | None, day: str
    ) -> tuple[OpResult, list[_Rev]]:
        server_fs = device_id == SERVER_FS
        match op:
            case Create():
                return self._plan_create(s, op, blob or b"", device_id, day, server_fs)
            case Update():
                return self._plan_update(s, op, blob or b"", device_id, day, server_fs)
            case Move():
                row = self._file(s, op.file_id)
                self._check_base(row, op.base_revision)
                if row.deleted:
                    raise _Rejected(409, "file-deleted", "File is deleted")
                self._check_path(op.new_path, row.kind)
                if op.new_path == row.path:
                    return self._unchanged(row), []
                if (other := self._live_at(s, op.new_path)) and other.file_id != row.file_id:
                    raise _Rejected(409, "path-taken", "Path is taken")
                before = State(row.path, row.content_hash, False)
                if server_fs:
                    before = State(op.new_path, row.content_hash, False)
                rev = self._next(row, "move", path=op.new_path, before=before)
                status: Status = "applied" if op.base_revision == row.revision else "merged"
                return self._result(status, rev), [rev]
            case Delete():
                row = self._file(s, op.file_id)
                self._check_base(row, op.base_revision)
                if row.deleted:
                    return self._unchanged(row), []
                base = self._revision(s, row.file_id, op.base_revision)
                if base is not None and base.content_hash not in (None, row.content_hash):
                    # Edit wins: the file changed since the deleting client saw it.
                    problem = _Rejected(409, "delete-superseded", "Delete superseded by an edit")
                    return dataclasses.replace(
                        self._unchanged(row), status="merged", problem=problem.problem
                    ), []
                shown = None if server_fs else State(row.path, row.content_hash, False)
                rev = self._next(row, "delete", deleted=True, content_hash=None, before=shown)
                return self._result("applied", rev), [rev]
            case Restore():
                row = self._file(s, op.file_id)
                old = self._revision(s, row.file_id, op.from_revision)
                if old is None or old.content_hash is None:
                    raise _Rejected(404, "revision-not-found", "Revision not found")
                if not row.deleted and row.content_hash == old.content_hash:
                    return self._unchanged(row), []
                path = row.path
                if row.deleted and self._live_at(s, path):
                    raise _Rejected(409, "path-taken", "Path is taken")
                before = State(row.path, row.content_hash, row.deleted)
                size = len(self.history.get(old.content_hash))
                rev = self._next(
                    row, "restore", content_hash=old.content_hash, size=size, before=before
                )
                return self._result("applied", rev), [rev]
        raise _Rejected(422, "unknown-operation", "Unknown operation")

    def _plan_create(
        self, s: Session, op: Create, blob: bytes, device_id: str, day: str, server_fs: bool
    ) -> tuple[OpResult, list[_Rev]]:
        self._check_path(op.path, op.kind)
        if s.get(File, op.file_id) is not None:
            raise _Rejected(409, "file-exists", "File id already exists")
        path, problem = op.path, None
        status: Status = "applied"
        if taken := self._live_at(s, op.path):  # create vs create: the second is a copy
            path = conflict_copy_path(op.path, device_id, day, lambda p: bool(self._live_at(s, p)))
            status = "conflict"
            problem = self._conflict(s, taken, op.file_id, 0)
        before = State(path, op.content_hash, False) if server_fs and path == op.path else None
        rev = _Rev(
            op.file_id, 1, path, op.kind, op.content_hash, False, "create", len(blob), before
        )
        return self._result(status, rev, problem), [rev]

    def _plan_update(
        self, s: Session, op: Update, blob: bytes, device_id: str, day: str, server_fs: bool
    ) -> tuple[OpResult, list[_Rev]]:
        row = self._file(s, op.file_id)
        self._check_base(row, op.base_revision)
        on_disk = State(row.path, op.content_hash, False) if server_fs else None
        if row.deleted:  # update vs delete: edit wins, the file comes back
            if self._live_at(s, row.path):
                return self._conflict_copy(s, row, op, blob, device_id, day)
            before = on_disk or State(row.path, row.content_hash, True)
            rev = self._next(
                row, "update", content_hash=op.content_hash, size=len(blob), before=before
            )
            return self._result("applied", rev), [rev]
        data = blob
        status: Status = "applied"
        if op.base_revision < row.revision:
            base = self._revision(s, row.file_id, op.base_revision)
            theirs = self.history.get(row.content_hash)
            opaque = max(len(blob), len(theirs)) > MAX_NOTE_BYTES
            if row.kind != "note" or opaque or base is None or base.content_hash is None:
                if blob != theirs:
                    return self._conflict_copy(s, row, op, blob, device_id, day)
            else:
                merged = merge_note(self.history.get(base.content_hash), theirs, blob)
                if not merged.clean or merged.data is None:
                    return self._conflict_copy(s, row, op, blob, device_id, day)
                data = merged.data
                if data != blob:
                    self.history.put(data)  # step 1 for the merged bytes, before the commit
                    status = "merged"
        if _sha(data) == row.content_hash:
            return self._unchanged(row), []
        before = on_disk or State(row.path, row.content_hash, False)
        rev = self._next(row, "update", content_hash=_sha(data), size=len(data), before=before)
        return self._result(status, rev), [rev]

    def _conflict_copy(
        self, s: Session, row: File, op: Update, blob: bytes, device_id: str, day: str
    ) -> tuple[OpResult, list[_Rev]]:
        path = conflict_copy_path(row.path, device_id, day, lambda p: bool(self._live_at(s, p)))
        copy_id = uuid.uuid7()
        problem = self._conflict(s, row, copy_id, op.base_revision)
        rev = _Rev(copy_id, 1, path, row.kind, op.content_hash, False, "create", len(blob), None)
        return self._result("conflict", rev, problem), [rev]

    def _conflict(self, s: Session, row: File, copy_id: uuid.UUID, base: int) -> dict[str, Any]:
        s.add(
            Conflict(
                id=uuid.uuid7(),
                vault_id=self.vault_id,
                file_id=row.file_id,
                copy_file_id=copy_id,
                base_revision=base,
                their_revision=row.revision,
            )
        )
        problem = _Rejected(409, "conflict", "Edit kept as a conflict copy").problem
        return problem | {"original_file_id": str(row.file_id)}

    def _next(self, row: File, op: str, *, before: State | None, **changes: Any) -> _Rev:
        rev = _Rev(
            row.file_id,
            row.revision + 1,
            row.path,
            row.kind,
            row.content_hash,
            False,
            op,
            row.size,
            before,
        )
        return dataclasses.replace(rev, **changes)

    def _result(self, status: Status, rev: _Rev, problem: dict[str, Any] | None = None) -> OpResult:
        return OpResult(
            status, rev.file_id, rev.revision, None, rev.content_hash, rev.path, problem
        )

    def _unchanged(self, row: File) -> OpResult:
        content = None if row.deleted else row.content_hash
        return OpResult("applied", row.file_id, row.revision, None, content, row.path)

    # Vault materialization and recovery -------------------------------------------------

    def _apply(self, file_id: uuid.UUID, revision: int, before: State | None, after: State) -> None:
        """Bring the vault from `before` to `after`, never overwriting external bytes."""
        try:
            if after.deleted:
                if before is None or before.deleted:
                    return
                found = hash_path(self.root_fd, before.path)
                if found is None:
                    return
                if found != before.content_hash:
                    raise ExternalChangeError(before.path, found, None)
                move_to(self.root_fd, before.path, self.recovery_dir)
                return
            if after.content_hash is None:
                return
            data = self.history.get(after.content_hash)
            if before is None or before.deleted:
                atomic_write(
                    self.root_fd,
                    after.path,
                    data,
                    expected_hash=None,
                    recovery_dir=self.recovery_dir,
                )
                return
            if before.path != after.path:
                found = hash_path(self.root_fd, before.path)
                try:
                    if found is None:
                        raise ExternalChangeError(before.path, None, None)
                    # Move whatever is there: an external edit travels with the file.
                    rename_noreplace(self.root_fd, before.path, after.path, expected_hash=found)
                except ExternalChangeError:
                    log.warning(
                        "vault move skipped (source gone or target taken); reconciled later"
                    )
                    return
                if found != before.content_hash:
                    raise ExternalChangeError(after.path, found, None)
            if before.content_hash != after.content_hash:
                atomic_write(
                    self.root_fd,
                    after.path,
                    data,
                    expected_hash=before.content_hash,
                    recovery_dir=self.recovery_dir,
                )
        except ExternalChangeError as err:
            if not after.deleted and err.found_hash == after.content_hash:
                return  # the disk already holds this revision
            self._absorb(file_id, revision, err, new_file=before is None or before.deleted)
        except OSError, PathEscapeError:
            log.exception("vault write failed after the commit; recovery retries it")
            self.unsettled.add(file_id)

    def _absorb(
        self, file_id: uuid.UUID, revision: int, err: ExternalChangeError, *, new_file: bool
    ) -> None:
        """Commit external bytes found in the way: as an update on the previous revision,
        or, where the commit created the file, as an unrelated new file at that path."""
        try:
            data = (
                err.preserved.read_bytes() if err.preserved else read_file(self.root_fd, err.path)
            )
        except FileNotFoundError:
            log.warning("vault file removed during a commit; the watcher reconciles")
            return
        follow: Operation
        if new_file:
            follow = Create(uuid.uuid7(), uuid.uuid7(), err.path, classify(err.path), _sha(data))
        else:
            follow = Update(uuid.uuid7(), file_id, max(revision - 1, 1), _sha(data))
        self.commit(follow, SERVER_FS, data)

    def _index(self, revs: list[_Rev]) -> None:
        try:
            with self.session_factory.begin() as s:
                for rev in revs:
                    if rev.deleted:
                        remove_file(s, rev.file_id)
                    elif rev.kind == "note" and rev.content_hash and rev.size > MAX_NOTE_BYTES:
                        for model in (NoteLink, NoteTag, Note):  # grown opaque: not parsed
                            s.execute(delete(model).where(model.file_id == rev.file_id))
                    elif rev.kind == "note" and rev.content_hash:
                        data = self.history.get(rev.content_hash)
                        index_file(s, self.vault_id, rev.file_id, data, rev.path)
        except Exception:
            log.exception("indexing after a commit failed; a rebuild repairs it")

    def recover(self, file_ids: set[uuid.UUID] | None = None) -> None:
        """Repair what a crash between the commit steps left (sync §2.3 crash table): the
        whole vault at startup, or only `file_ids` (the unsettled files) before an ingest."""
        with self.session_factory() as s:
            revs = select(Revision).where(Revision.vault_id == self.vault_id)
            rows = select(File).where(File.vault_id == self.vault_id)
            if file_ids is not None:
                revs = revs.where(Revision.file_id.in_(file_ids))
                rows = rows.where(File.file_id.in_(file_ids))
            revisions = s.scalars(revs.order_by(Revision.seq)).all()
            files = s.scalars(rows).all()
            s.expunge_all()
        if file_ids is None:
            logged = {e.seq for e in self.history.read_log()}
            for r in revisions:
                if r.seq not in logged:
                    self.history.append_log(_entry(r, r.device_id, r.committed_at.isoformat()))
        by_key = {(r.file_id, r.revision): r for r in revisions}
        for row in files:
            prev = by_key.get((row.file_id, row.revision - 1))
            prev_state = State(prev.path, prev.content_hash, prev.deleted) if prev else None
            after = State(row.path, None if row.deleted else row.content_hash, row.deleted)
            self.unsettled.discard(row.file_id)
            try:  # one bad file must not stop the recovery of the others
                self._settle(row.file_id, row.revision, prev_state, after)
            except OSError, PathEscapeError:
                log.exception("recovery of a vault file failed; retried on the next run")
                self.unsettled.add(row.file_id)

    def _settle(
        self, file_id: uuid.UUID, revision: int, before: State | None, after: State
    ) -> None:
        actual = hash_path(self.root_fd, after.path)
        if after.deleted and (before is None or before.deleted or actual is None):
            return
        if not after.deleted and actual == after.content_hash:
            return
        if before is None or before.deleted:
            at_before = actual is None
        else:
            at_before = hash_path(self.root_fd, before.path) == before.content_hash and (
                before.path == after.path or actual is None
            )
        if at_before:
            self._apply(file_id, revision, before, after)
        elif actual is not None:
            data = read_file(self.root_fd, after.path)
            self.commit(
                Update(uuid.uuid7(), file_id, max(revision - 1, 1), _sha(data)), SERVER_FS, data
            )
