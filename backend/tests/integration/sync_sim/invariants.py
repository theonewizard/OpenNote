"""The checks run after every simulated world settles: I1 to I6 of sync protocol §1 and
the extra checks of testing strategy §4."""

from __future__ import annotations

import datetime as dt
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, select

from app.notes.models import File
from app.sync.history import HistoryCorrupt
from app.sync.models import Conflict, Revision
from app.vaults.scan import scan
from tests.integration.sync_sim.world import World, markers_in

_CONFLICT_DAY = re.compile(r" \(conflict (\S+) \d{4}-\d{2}-\d{2}\)")


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


def tree(root: Path, skip: set[str] = frozenset()) -> dict[str, str]:  # type: ignore[assignment]
    return {f.path: f.content_hash for f in scan(root) if f.path not in skip}


def _revisions(world: World) -> list[Revision]:
    with world.factory() as s:
        rows = s.scalars(
            select(Revision).where(Revision.vault_id == world.vault_id).order_by(Revision.seq)
        ).all()
        s.expunge_all()
        return list(rows)


def _files(world: World) -> list[File]:
    with world.factory() as s:
        rows = s.scalars(select(File).where(File.vault_id == world.vault_id)).all()
        s.expunge_all()
        return list(rows)


def check_invariants(world: World) -> list[Violation]:
    found: list[Violation] = []
    revisions, files = _revisions(world), _files(world)
    live = {f.path: f.content_hash for f in files if not f.deleted}
    server = tree(world.server_root)
    if server != live:
        found.append(Violation("server-vault", f"vault {server} != registry {live}"))
    by_id = {f.file_id: f for f in files}
    for c in world.clients:  # I3: convergence
        skip_local = {c.files[f].path for f in c.rejected if f in c.files}
        # Only a rejected file's own live path: a deleted one's path may hold another file.
        skip_server = {by_id[f].path for f in c.rejected if f in by_id and not by_id[f].deleted}
        local = tree(c.root, skip_local)
        expected = {p: h for p, h in server.items() if p not in skip_server}
        if local != expected:
            found.append(Violation("I3", f"{c.name} {local} != server {expected}"))
    contents: dict[str, bytes] = {}
    for r in revisions:  # history holds every committed revision
        if r.content_hash and r.content_hash not in contents:
            try:
                contents[r.content_hash] = world.history.get(r.content_hash)
            except FileNotFoundError, HistoryCorrupt:
                found.append(Violation("history", f"revision {r.seq} bytes missing"))
    logged = sorted(e.seq for e in world.history.read_log())
    seqs = [r.seq for r in revisions]
    if logged != seqs or seqs != list(range(1, len(seqs) + 1)):
        found.append(Violation("history", f"log seqs {logged} vs revisions {seqs}"))
    committed = {m for data in contents.values() for m in markers_in(data)}
    for marker in world.markers:  # I1: no acknowledged loss
        if marker not in committed | world.abandoned | world.kept_on_client:
            found.append(Violation("I1", f"{marker} is in no revision"))
    last: dict[object, Revision] = {}
    for r in revisions:  # I2: a content revision keeps what the previous one had
        prev = last.get(r.file_id)
        last[r.file_id] = r
        if prev is None or prev.deleted or r.deleted or r.kind != "note":
            continue
        if prev.content_hash in contents and r.content_hash in contents:
            lost = set(markers_in(contents[prev.content_hash])) - set(
                markers_in(contents[r.content_hash])
            )
            if lost:
                found.append(Violation("I2", f"seq {r.seq} dropped {sorted(lost)}"))
    with world.factory() as s:  # a conflict copy holds one side's content
        for conflict in s.scalars(select(Conflict).where(Conflict.vault_id == world.vault_id)):
            first = next(
                (r for r in revisions if r.file_id == conflict.copy_file_id and r.revision == 1),
                None,
            )
            if first is None or first.content_hash not in world.pushed_hashes:
                found.append(Violation("conflict-copy", f"copy {conflict.copy_file_id}"))
    return found


def check_no_loops(world: World) -> list[Violation]:
    """I5: once settled, another sync round pushes nothing and commits nothing."""
    before = world.last_seq()
    for c in world.clients:
        c.sync()
    if world.last_seq() != before or any(c.outbox for c in world.clients):
        return [Violation("I5", f"seq {before} -> {world.last_seq()} after an idle round")]
    return []


def check_idempotent(world: World) -> list[Violation]:
    """I4: replaying every request ever sent leaves the server state unchanged."""
    before = server_state(world)
    for d in list(world.deliveries):
        world._server_push(d)
    after = server_state(world)
    return [] if after == before else [Violation("I4", "replayed requests changed the state")]


def server_state(world: World) -> tuple:
    """The final server state with what the clock may change removed (I6)."""

    def norm(path: str) -> str:
        return _CONFLICT_DAY.sub(r" (conflict \1 DAY)", path)

    files = sorted(
        (norm(f.path), f.content_hash, f.revision, f.deleted, f.kind) for f in _files(world)
    )
    revisions = [
        (r.seq, norm(r.path), r.revision, r.content_hash, r.deleted, r.device_id, r.op)
        for r in _revisions(world)
    ]
    return tuple(files), tuple(revisions)


@dataclass
class SimReport:
    seed: int
    violations: list[Violation]
    actions: list[str]
    state: tuple

    def describe(self) -> str:
        lines = [f"seed={self.seed}"] + [f"  {v.code}: {v.detail}" for v in self.violations]
        return "\n".join([*lines, "actions: " + ", ".join(self.actions)])


def run_seed(
    seed: int,
    *,
    clients: int,
    steps: int,
    engine: Engine,
    tmp: Path,
    clock_skew: dt.timedelta = dt.timedelta(0),
) -> SimReport:
    """One seeded run in fresh directories with a fresh vault id."""
    with tempfile.TemporaryDirectory(dir=tmp) as run_dir:
        world = World(seed, engine, Path(run_dir), clients, clock_skew=clock_skew)
        try:
            for _ in range(steps):
                world.step()
            world.quiesce()
            violations = check_invariants(world) + check_no_loops(world)
            violations += check_idempotent(world)
            return SimReport(seed, violations, world.actions, server_state(world))
        finally:
            world.close()
