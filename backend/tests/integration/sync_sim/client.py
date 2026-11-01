"""A simulated sync client: local vault directory, `files`, `outbox`, cursor and the loop
of sync protocol §9, applying pulls per the §4 table and push results per §5."""

from __future__ import annotations

import hashlib
import os
import random
import shutil
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from app.sync.commit import Create, Delete, Move, Operation, OpResult, Update
from app.sync.cursor import CursorExpired
from app.sync.service import ChangeEntry

if TYPE_CHECKING:
    from tests.integration.sync_sim.world import World

NOTE_NAMES = ["Alpha", "Beta", "Gamma", "Delta"]  # few names, so creates collide


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def rng_uuid(rng: random.Random, salt: uuid.UUID) -> uuid.UUID:
    """A seeded id, salted with the run's vault id: seeds share one database."""
    return uuid.UUID(int=rng.getrandbits(128) ^ salt.int, version=4)


@dataclass
class Rec:
    file_id: uuid.UUID
    path: str
    kind: str
    base_revision: int  # 0: never acknowledged by the server
    base_hash: str | None
    deleted: bool = False
    override_hash: str | None = None  # local bytes that a pull may replace (kept in a copy)


@dataclass
class Pending:
    op: Operation
    blob: bytes | None
    sent: bool = False


@dataclass
class Client:
    world: World
    name: str
    root: Path
    recovery: Path
    rng: random.Random
    files: dict[uuid.UUID, Rec] = field(default_factory=dict)
    outbox: list[Pending] = field(default_factory=list)
    remote: dict[uuid.UUID, ChangeEntry] = field(default_factory=dict)
    rejected: set[uuid.UUID] = field(default_factory=set)
    cursor: str | None = None
    cursor_expired: bool = False
    online: bool = True

    # Local helpers ---------------------------------------------------------------------

    def local_hash(self, path: str) -> str | None:
        p = self.root / path
        return sha(p.read_bytes()) if p.is_file() else None

    def write(self, path: str, data: bytes) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def to_recovery(self, path: str) -> None:
        p = self.root / path
        if p.is_file():
            shutil.move(p, self.recovery / f"{rng_uuid(self.rng, self.world.vault_id)}-{p.name}")

    def live(self) -> list[Rec]:
        return [
            r
            for r in self.files.values()
            if not r.deleted and r.file_id not in self.rejected and (self.root / r.path).is_file()
        ]

    def pending_for(self, file_id: uuid.UUID) -> list[Pending]:
        return [p for p in self.outbox if p.op.file_id == file_id]

    def enqueue(self, op: Operation, blob: bytes | None) -> None:
        self.outbox.append(Pending(op, blob))

    def op_id(self) -> uuid.UUID:
        return rng_uuid(self.rng, self.world.vault_id)

    # Local edits (never wait for the network) -------------------------------------------

    def create(self, attachment: bool) -> None:
        name = self.rng.choice(NOTE_NAMES)
        path = f"{name}.png" if attachment else f"{name}.md"
        if (self.root / path).exists():
            return
        marker = self.world.new_marker(self.name)
        data = marker.encode() + b"\n" if attachment else f"# {name}\n{marker}\n".encode()
        self.write(path, data)
        file_id = rng_uuid(self.rng, self.world.vault_id)
        kind = "attachment" if attachment else "note"
        self.files[file_id] = Rec(file_id, path, kind, 0, None)
        self.enqueue(Create(self.op_id(), file_id, path, kind, sha(data)), data)

    def edit(self) -> None:
        if not (recs := self.live()):
            return
        rec = self.rng.choice(recs)
        data = self.world.edited(self.name, (self.root / rec.path).read_bytes(), rec.kind)
        self.write(rec.path, data)
        self.enqueue_content(rec, data)

    def enqueue_content(self, rec: Rec, data: bytes) -> None:
        last = self.pending_for(rec.file_id)[-1:] or [None]
        pending = last[0]
        if pending and not pending.sent and isinstance(pending.op, Create | Update):
            pending.op, pending.blob = replace(pending.op, content_hash=sha(data)), data
            return
        base = max(rec.base_revision, 1)
        self.enqueue(Update(self.op_id(), rec.file_id, base, sha(data)), data)

    def move(self) -> None:
        if not (recs := self.live()):
            return
        rec = self.rng.choice(recs)
        stem, ext = os.path.splitext(rec.path.rsplit("/", 1)[-1])
        new_path = f"{self.rng.choice(['', 'Folder/'])}{stem} m{self.rng.randrange(1000)}{ext}"
        if (self.root / new_path).exists():
            return
        (self.root / new_path).parent.mkdir(parents=True, exist_ok=True)
        os.rename(self.root / rec.path, self.root / new_path)
        rec.path = new_path
        self.enqueue(Move(self.op_id(), rec.file_id, max(rec.base_revision, 1), new_path), None)

    def delete(self) -> None:
        if not (recs := self.live()):
            return
        rec = self.rng.choice(recs)
        self.world.abandon((self.root / rec.path).read_bytes())
        (self.root / rec.path).unlink()
        rec.deleted = True
        pending = self.pending_for(rec.file_id)
        if rec.base_revision == 0 and pending and not pending[0].sent:
            for p in pending:
                self.outbox.remove(p)
            del self.files[rec.file_id]
            return
        self.enqueue(Delete(self.op_id(), rec.file_id, max(rec.base_revision, 1)), None)

    # The sync loop (§9) ---------------------------------------------------------------

    def sync(self) -> None:
        if not self.online:
            return
        self.push()
        self.pull()
        self.scan()

    def push(self) -> None:
        batch = self.outbox[:100]
        if not batch:
            return
        for p in batch:
            p.sent = True
        results = self.world.deliver_push(self, [p.op for p in batch], [p.blob for p in batch])
        if results is None:
            return  # request or response lost: the ops stay and are retried
        for pending, result in zip(batch, results, strict=True):
            self.outbox.remove(pending)
            self.on_result(pending, result)

    def on_result(self, pending: Pending, r: OpResult) -> None:
        op = pending.op
        problem = (r.problem or {}).get("type", "")
        if problem.endswith("/conflict"):
            status = "conflict"
        elif problem.endswith("/delete-superseded"):
            status = "superseded"
        elif r.status == "rejected" or (r.status == "duplicate" and r.seq is None and problem):
            status = "rejected"
        else:
            status = "ok"
        rec = self.files.get(op.file_id)
        if rec is None:
            return
        if status == "rejected":
            self.rejected.add(op.file_id)
            self.world.rejected_content(self, rec)
            return
        self.rejected.discard(op.file_id)  # a later op (an edit that won) brought it back
        if isinstance(op, Create) and status == "conflict":  # our file is the copy
            self.relocate(rec, r.path)
        if isinstance(op, Update) and status == "conflict":  # copy is a new file
            known = r.file_id in self.files  # a pull may have brought the copy already
            if r.path and not known and not (self.root / r.path).exists() and pending.blob:
                self.write(r.path, pending.blob)
                self.files[r.file_id] = Rec(r.file_id, r.path, rec.kind, 1, r.content_hash)
            rec.override_hash = op.content_hash
            return
        if status == "superseded":  # edit won: the file is back
            if (self.root / (r.path or rec.path)).exists():
                # Another local file holds the path; a later pull revives this one.
                rec.base_revision = min(rec.base_revision, (r.revision or 1) - 1)
                return
            rec.deleted = False
            rec.base_revision, rec.base_hash, rec.path = (
                r.revision or 0,
                r.content_hash,
                r.path or rec.path,
            )
            if r.content_hash:
                self.write(rec.path, self.world.blob(r.content_hash))
            return
        if isinstance(op, Delete):
            rec.deleted, rec.base_revision = True, r.revision or rec.base_revision
            rec.override_hash = None  # nothing local is left for a pull to replace
            return
        # Advance the base only when the local file holds the server's bytes afterwards;
        # a dirty file keeps its old base, so its next push merges instead of replacing.
        sent = op.content_hash if isinstance(op, Create | Update) else rec.base_hash
        if r.content_hash == sent or self.local_hash(rec.path) == sent:
            if r.content_hash and r.content_hash != sent:
                self.write(rec.path, self.world.blob(r.content_hash))
            rec.base_revision, rec.base_hash = r.revision or rec.base_revision, r.content_hash
        self.relocate(rec, r.path)

    def relocate(self, rec: Rec, path: str | None) -> None:
        """Follow the server's path for a file, when the local file and target allow."""
        if not path or path == rec.path or rec.deleted or (self.root / path).exists():
            return
        if self.pending_for(rec.file_id) or not (self.root / rec.path).is_file():
            return  # a pending move or delete decides
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        os.rename(self.root / rec.path, self.root / path)
        rec.path = path

    def pull(self) -> None:
        if self.cursor_expired:
            self.full_reconcile()
            return
        while True:
            try:
                page = self.world.changes(self.cursor)
            except CursorExpired:
                self.full_reconcile()
                return
            for entry in page.entries:
                self.remote[entry.file_id] = entry
            self.cursor = page.next_cursor
            if not page.has_more:
                break
        for file_id in list(self.remote):
            self.adopt(file_id)

    def clean(self, rec: Rec) -> bool:
        if self.pending_for(rec.file_id) or rec.file_id in self.rejected:
            return False
        if rec.deleted:
            return True
        return self.local_hash(rec.path) in (rec.base_hash, rec.override_hash)

    def adopt(self, file_id: uuid.UUID) -> None:
        """Apply the newest known server state of a file if the local copy is clean."""
        e = self.remote[file_id]
        rec = self.files.get(file_id)
        if rec is None:
            if e.deleted:
                self.files[file_id] = Rec(file_id, e.path, e.kind, e.revision, None, True)
            elif not (self.root / e.path).exists():
                self.write(e.path, self.world.blob(e.content_hash or ""))
                self.files[file_id] = Rec(file_id, e.path, e.kind, e.revision, e.content_hash)
            return
        if (rec.base_revision >= e.revision and rec.override_hash is None) or not self.clean(rec):
            return
        if e.deleted:
            if not rec.deleted:
                self.to_recovery(rec.path)
            rec.deleted, rec.base_revision, rec.override_hash = True, e.revision, None
            return
        if (rec.deleted or e.path != rec.path) and (self.root / e.path).exists():
            return  # another local file holds the target; retried after the next push
        if not rec.deleted and e.path != rec.path:
            (self.root / rec.path).unlink(missing_ok=True)
        self.write(e.path, self.world.blob(e.content_hash or ""))
        rec.path, rec.deleted, rec.override_hash = e.path, False, None
        rec.base_revision, rec.base_hash = e.revision, e.content_hash

    def scan(self) -> None:
        """Turn external edits of the local vault into operations (§9, last step)."""
        tracked = set()
        for rec in list(self.files.values()):
            if rec.deleted or rec.file_id in self.rejected:
                continue
            tracked.add(rec.path)
            if self.pending_for(rec.file_id):
                continue
            h = self.local_hash(rec.path)
            if h is None:
                rec.deleted = True
                self.enqueue(Delete(self.op_id(), rec.file_id, max(rec.base_revision, 1)), None)
            elif h not in (rec.base_hash, rec.override_hash):
                self.enqueue_content(rec, (self.root / rec.path).read_bytes())
        rejected_paths = {self.files[f].path for f in self.rejected if f in self.files}
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root).as_posix()
            if not p.is_file() or rel in tracked or rel in rejected_paths or p.name.startswith("."):
                continue
            data = p.read_bytes()
            kind = "note" if rel.endswith(".md") else "attachment"
            file_id = rng_uuid(self.rng, self.world.vault_id)
            self.files[file_id] = Rec(file_id, rel, kind, 0, None)
            self.enqueue(Create(self.op_id(), file_id, rel, kind, sha(data)), data)

    def full_reconcile(self) -> None:
        """After 410 Gone: compare with the snapshot (§4 full reconcile table)."""
        entries, cursor = self.world.snapshot()
        by_id = {e.file_id: e for e in entries}
        for rec in list(self.files.values()):
            if rec.file_id in self.rejected or self.pending_for(rec.file_id) or rec.deleted:
                continue
            if rec.file_id in by_id or rec.base_revision == 0:
                continue
            if self.clean(rec):  # deleted on the server, tombstone expired
                self.to_recovery(rec.path)
                rec.deleted = True
            else:  # edit wins: restore as a new file
                data = (self.root / rec.path).read_bytes()
                del self.files[rec.file_id]
                new_id = rng_uuid(self.rng, self.world.vault_id)
                self.files[new_id] = Rec(new_id, rec.path, rec.kind, 0, None)
                self.enqueue(Create(self.op_id(), new_id, rec.path, rec.kind, sha(data)), data)
        self.remote.update(by_id)
        for file_id in by_id:
            self.adopt(file_id)
        self.cursor, self.cursor_expired = cursor, False
