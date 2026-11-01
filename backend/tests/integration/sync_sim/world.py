"""The simulated world: one server (Committer on a real PostgreSQL and a temporary vault),
N clients, external editors and a faulty network, all driven by one seeded RNG."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import sessionmaker

from app.notes.identity import diff_scan
from app.sync.commit import Committer, Operation, OpResult
from app.sync.cursor import encode_cursor
from app.sync.history import HistoryStore
from app.sync.models import Revision
from app.sync.service import ChangeEntry, ChangesPage, changes, ingest_fs_changes, push, snapshot
from app.vaults.fsio import open_root
from app.vaults.registry import open_vault
from app.vaults.scan import scan
from tests.integration.sync_sim.client import Client, sha

CRASH_POINTS = ("history", "db", "log", "vault")
EPOCH = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)


class SimCrash(Exception):
    """The server process died at a commit step."""


@dataclass
class Delivery:
    device: str
    ops: list[Operation]
    blobs: dict[str, bytes]


@dataclass
class World:
    seed: int
    engine: Engine
    tmp: Path
    n_clients: int
    clock_skew: dt.timedelta = dt.timedelta(0)
    faults: bool = True
    actions: list[str] = field(default_factory=list)
    markers: dict[str, str] = field(default_factory=dict)  # marker -> writer
    abandoned: set[str] = field(default_factory=set)
    kept_on_client: set[str] = field(default_factory=set)  # markers in rejected files
    pushed_hashes: set[str] = field(default_factory=set)
    deliveries: list[Delivery] = field(default_factory=list)
    delayed: list[Delivery] = field(default_factory=list)
    crash_next: str | None = None
    ticks: int = 0

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.server_root = self.tmp / "server"
        self.server_root.mkdir()
        self.factory = sessionmaker(self.engine)
        with self.factory.begin() as s:
            self.vault_id = open_vault(s, self.server_root)
        self.history = HistoryStore(self.tmp / "history", self.vault_id)
        self.root_fd = open_root(self.server_root)
        self.committer = Committer(
            self.factory,
            self.history,
            self.root_fd,
            self.vault_id,
            crash=self._crash,
            clock=lambda: EPOCH + self.clock_skew + dt.timedelta(minutes=self.ticks),
        )
        self.clients = []
        for i in range(self.n_clients):
            root, recovery = self.tmp / f"client{i}", self.tmp / f"client{i}-recovery"
            root.mkdir()
            recovery.mkdir()
            rng = random.Random(self.rng.getrandbits(64))
            self.clients.append(Client(self, f"c{i}", root, recovery, rng))

    def close(self) -> None:
        os.close(self.root_fd)

    # Content with traceable markers ----------------------------------------------------

    def new_marker(self, writer: str) -> str:
        marker = f"m{len(self.markers)}-{writer}"
        self.markers[marker] = writer
        return marker

    def edited(self, writer: str, data: bytes, kind: str) -> bytes:
        marker = self.new_marker(writer)
        if kind != "note":
            self.abandon(data)  # an attachment is replaced whole, by the user's choice
            return marker.encode() + b"\n"
        lines = data.splitlines(keepends=True)
        at = self.rng.randrange(1, len(lines) + 1) if lines else 0
        return b"".join([*lines[:at], marker.encode() + b"\n", *lines[at:]])

    def abandon(self, data: bytes) -> None:
        """A user deleted content: its markers may legitimately disappear."""
        self.abandoned |= set(markers_in(data))

    def rejected_content(self, client: Client, rec) -> None:
        p = client.root / rec.path
        if p.is_file():
            self.kept_on_client |= set(markers_in(p.read_bytes()))

    def blob(self, content_hash: str) -> bytes:
        return self.history.get(content_hash)

    # The server, reached through a faulty network ----------------------------------------

    def _crash(self, step: str) -> None:
        if self.crash_next == step:
            self.crash_next = None
            raise SimCrash(step)

    def _server_push(self, d: Delivery) -> list[OpResult] | None:
        try:
            return push(self.committer, d.device, d.ops, d.blobs)
        except SimCrash:
            self.committer.recover()  # the restarted server repairs before serving
            return None

    def deliver_push(
        self, client: Client, ops: list[Operation], blobs: list[bytes | None]
    ) -> list[OpResult] | None:
        d = Delivery(client.name, ops, {sha(b): b for b in blobs if b is not None})
        self.pushed_hashes |= set(d.blobs)
        self.deliveries.append(d)
        fate = self.rng.random() if self.faults else 1.0
        if fate < 0.05:
            return None  # request lost
        if fate < 0.10:
            self.delayed.append(d)  # arrives later, out of order; the client hears nothing
            return None
        results = self._server_push(d)
        if fate < 0.15:
            self._server_push(d)  # delivered twice
        if fate < 0.20:
            return None  # response lost
        return results

    def deliver_delayed(self) -> None:
        if self.delayed:
            self._server_push(self.delayed.pop(self.rng.randrange(len(self.delayed))))

    def changes(self, cursor: str | None) -> ChangesPage:
        with self.factory() as s:
            return changes(s, self.vault_id, cursor, limit=50)

    def snapshot(self) -> tuple[list[ChangeEntry], str]:
        with self.factory() as s:
            last = s.scalar(
                select(func.max(Revision.seq)).where(Revision.vault_id == self.vault_id)
            )
            return snapshot(s, self.vault_id), encode_cursor(self.vault_id, last or 0)

    def server_scan(self) -> None:
        """The server watcher's reconciliation: external edits become server-fs ops."""
        with self.factory() as s:
            found = diff_scan(s, self.vault_id, scan(self.server_root), root=self.server_root)
        for f in scan(self.server_root):
            self.pushed_hashes.add(f.content_hash)
        try:
            ingest_fs_changes(self.committer, found)
        except SimCrash:
            self.committer.recover()

    # External editors -------------------------------------------------------------------

    def external_edit(self, root: Path) -> None:
        files = sorted(p for p in root.rglob("*.md") if p.is_file())
        if files and self.rng.random() < 0.8:
            p = self.rng.choice(files)
            data = self.edited("ext", p.read_bytes(), "note")
        else:
            p = root / f"Ext{self.rng.randrange(100)}.md"
            if p.exists():
                return
            data = f"# ext\n{self.new_marker('ext')}\n".encode()
        p.write_bytes(data)
        if root == self.server_root:
            # An edit on the server's disk is one side's content even if a commit absorbs it
            # before the next server_scan sees it.
            self.pushed_hashes.add("sha256:" + hashlib.sha256(data).hexdigest())

    # One random step ----------------------------------------------------------------------

    def step(self) -> None:
        self.ticks += 1
        client = self.rng.choice(self.clients)
        roll = self.rng.random()
        actions = [
            (0.18, "edit", client.edit),
            (0.08, "create_note", lambda: client.create(attachment=False)),
            (0.03, "create_attachment", lambda: client.create(attachment=True)),
            (0.05, "move", client.move),
            (0.04, "delete", client.delete),
            (0.30, "sync", client.sync),
            (0.05, "toggle_online", lambda: setattr(client, "online", not client.online)),
            (0.04, "external_client", lambda: self.external_edit(client.root)),
            (0.04, "external_server", lambda: self.external_edit(self.server_root)),
            (0.05, "server_scan", self.server_scan),
            (0.04, "arm_crash", lambda: setattr(self, "crash_next", self.rng.choice(CRASH_POINTS))),
            (0.04, "deliver_delayed", self.deliver_delayed),
            (0.02, "expire_cursor", lambda: setattr(client, "cursor_expired", True)),
        ]
        for weight, name, action in actions:
            if roll < weight:
                self.actions.append(f"{client.name}:{name}")
                action()
                return
            roll -= weight
        self.actions.append(f"{client.name}:sync")
        client.sync()

    def quiesce(self, rounds: int = 8) -> None:
        """Heal the network, bring everyone online and sync until nothing changes."""
        self.faults, self.crash_next = False, None
        while self.delayed:
            self.deliver_delayed()
        for c in self.clients:
            c.online = True
        for _ in range(rounds):
            before = self.last_seq()
            self.server_scan()
            for c in self.clients:
                c.sync()
            if self.last_seq() == before and not any(c.outbox for c in self.clients):
                return

    def last_seq(self) -> int:
        with self.factory() as s:
            return (
                s.scalar(select(func.max(Revision.seq)).where(Revision.vault_id == self.vault_id))
                or 0
            )


def markers_in(data: bytes) -> list[str]:
    import re

    return re.findall(r"m\d+-(?:c\d+|ext)", data.decode("utf-8", "replace"))
