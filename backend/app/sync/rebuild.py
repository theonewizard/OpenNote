"""Rebuild the database's vault rows from the history store after PostgreSQL is lost
(P8-05; architecture plan §5.2: revision metadata is derived from "history store + vault
scan"; storage contract §7; sync protocol §2.3: the log holds every revision a client
was told about).

    python -m app.sync.rebuild [--owner USERNAME] [--dry-run] [--map VAULT_ID=FOLDER ...]

Every vault in the history root (`<history_root>/<vault_id>/log/*.jsonl`) is matched to a
folder: `--map`, else the folder under the vault root whose `.opennote/config.json`
names the id, else the direct child of the vault root holding at least 90 % of the
files the log says are live. Unmatched vaults, and vaults already in the database, are
reported and skipped. Each matched vault gets, in one transaction: its `vaults` row
(name from the config, else the folder name), every revision, the per-vault sequence,
the `files` registry at each file's last revision, and the derived index built from the
history bytes of those revisions. `--owner` makes an existing user the owner of every
rebuilt vault; without it only administrators see them until members are added.

What the log does not hold is not rebuilt: users, devices, tokens and sessions,
memberships, vault settings, idempotency records (`client_ops`), conflicts and the audit
log. Restore those from a database backup when there is one (docs/deployment/backup.md);
this procedure is for when there is none, or it is older than the history store.

The vault folder stays authoritative: run the vault watcher (`python -m app.vaults`)
afterwards and its first scan commits whatever the folder holds that the log does not
(edits made while the database was down) as new revisions. Nothing here writes to a
vault folder or the history store.
"""

import argparse
import dataclasses
import itertools
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.crypto import username_key
from app.auth.models import User
from app.core.config import SettingsError, get_settings
from app.core.db import make_sync_engine
from app.notes.index import rebuild_index
from app.notes.models import File
from app.sync.history import HistoryCorrupt, HistoryStore, RevisionLogEntry
from app.sync.models import Revision, VaultSeq
from app.vaults.config import read_config
from app.vaults.fsio import open_root
from app.vaults.models import Vault, VaultMember
from app.vaults.paths import casefold_key

MATCH_SHARE = 0.9
MATCH_SAMPLE = 200


@dataclasses.dataclass(frozen=True)
class Plan:
    vault_id: uuid.UUID
    folder: Path | None
    name: str | None
    revisions: int
    live: int
    note: str  # how the folder was found, or why the vault is skipped


def history_vaults(history_root: Path) -> list[uuid.UUID]:
    """The vault ids that have a revision log in the history root."""
    ids = []
    for child in sorted(history_root.iterdir()) if history_root.is_dir() else []:
        try:
            vault_id = uuid.UUID(child.name)
        except ValueError:
            continue
        if (child / "log").is_dir():
            ids.append(vault_id)
    return ids


def read_entries(history: HistoryStore) -> list[RevisionLogEntry]:
    """The log in sequence order; HistoryCorrupt if a sequence number repeats."""
    entries = sorted(history.read_log(), key=lambda e: e.seq)
    for a, b in itertools.pairwise(entries):
        if a.seq == b.seq:
            raise HistoryCorrupt(f"sequence number {a.seq} appears twice in the log")
    return entries


def last_states(entries: list[RevisionLogEntry]) -> dict[uuid.UUID, RevisionLogEntry]:
    last: dict[uuid.UUID, RevisionLogEntry] = {}
    for entry in entries:
        last[entry.file_id] = entry
    return last


def _config(folder: Path) -> tuple[uuid.UUID, str] | None:
    try:
        root_fd = open_root(folder)
    except OSError:
        return None
    try:
        cfg = read_config(root_fd)
    except ValueError:
        return None
    finally:
        os.close(root_fd)
    return (cfg.vault_id, cfg.name) if cfg else None


def find_folder(
    vault_root: Path, vault_id: uuid.UUID, live_paths: list[str]
) -> tuple[Path | None, str | None, str]:
    """The vault's folder and name, and how they were found."""
    children = sorted(p for p in vault_root.iterdir() if p.is_dir() and not p.is_symlink())
    for folder in children:
        found = _config(folder)
        if found and found[0] == vault_id:
            return folder, found[1], "config"
    sample = sorted(live_paths)[:MATCH_SAMPLE]
    best, best_share = None, 0.0
    for folder in children if sample else []:
        share = sum((folder / p).is_file() for p in sample) / len(sample)
        if share > best_share:
            best, best_share = folder, share
    if best is not None and best_share >= MATCH_SHARE:
        return best, None, f"{best_share:.0%} of the live files"
    return None, None, "no folder holds its files; give it with --map"


def plan(
    factory: sessionmaker[Session],
    history_root: Path,
    vault_root: Path,
    mapping: dict[uuid.UUID, Path],
) -> list[Plan]:
    with factory() as s:
        known = set(s.scalars(select(Vault.id)))
        taken = set(s.scalars(select(Vault.root_path)))
    plans = []
    for vault_id in history_vaults(history_root):
        entries = read_entries(HistoryStore(history_root, vault_id))
        live = [e.path for e in last_states(entries).values() if not e.deleted]
        if vault_id in known:
            folder, name, note = None, None, "already in the database"
        elif vault_id in mapping:
            folder, name, note = mapping[vault_id], None, "--map"
            if (found := _config(folder)) and found[0] == vault_id:
                name = found[1]
        else:
            folder, name, note = find_folder(vault_root, vault_id, live)
        if folder is not None and str(folder) in taken:
            folder, note = None, f"{folder} is already another vault's folder"
        plans.append(Plan(vault_id, folder, name, len(entries), len(live), note))
    return plans


def rebuild_vault(
    session: Session,
    history: HistoryStore,
    vault_id: uuid.UUID,
    folder: Path,
    name: str,
    owner: uuid.UUID | None = None,
) -> None:
    """Write the rows of one vault from its log; the caller commits."""
    entries = read_entries(history)
    session.add(Vault(id=vault_id, name=name, root_path=str(folder)))
    session.flush()
    sizes: dict[str, int] = {}
    size_of: dict[uuid.UUID, int] = {}  # a tombstone keeps the file's last size
    content: dict[uuid.UUID, str] = {}  # and its last content hash
    rows = []
    for e in entries:
        if e.content_hash is not None:
            if e.content_hash not in sizes:
                sizes[e.content_hash] = len(history.get(e.content_hash))
            size_of[e.file_id] = sizes[e.content_hash]
            content[e.file_id] = e.content_hash
        rows.append(
            {
                "vault_id": vault_id,
                "seq": e.seq,
                "file_id": e.file_id,
                "revision": e.revision,
                "path": e.path,
                "kind": e.kind,
                "content_hash": e.content_hash,
                "size": size_of.get(e.file_id, 0),
                "deleted": e.deleted,
                "device_id": e.device_id,
                "op": e.op,
                "committed_at": e.committed_at,
            }
        )
    if rows:
        session.execute(insert(Revision), rows)
    session.add(VaultSeq(vault_id=vault_id, last_seq=entries[-1].seq if entries else 0))
    # Tombstones first: a live file may sit at a path a deleted one had (one unique index
    # over live paths).
    last = last_states(entries)
    for e in sorted(last.values(), key=lambda e: not e.deleted):
        session.add(
            File(
                file_id=e.file_id,
                vault_id=vault_id,
                path=e.path,
                path_key=casefold_key(e.path),
                kind=e.kind,
                size=size_of.get(e.file_id, 0),
                content_hash=content.get(e.file_id, ""),
                revision=e.revision,
                deleted=e.deleted,
                # The vault is taken to hold each last revision; where it holds something
                # else, the watcher's first scan commits that as an edit (never a revert).
                written_revision=e.revision,
            )
        )
        session.flush()
    if owner is not None:
        session.add(VaultMember(vault_id=vault_id, user_id=owner, role="owner"))
    hashes = {e.path: content[e.file_id] for e in last.values() if not e.deleted}
    rebuild_index(session, vault_id, folder, read=lambda path: history.get(hashes[path]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.sync.rebuild")
    parser.add_argument("--owner", help="make this existing user the owner of every vault")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument(
        "--map", action="append", default=[], metavar="VAULT_ID=FOLDER", help="a vault's folder"
    )
    args = parser.parse_args(argv)
    try:
        mapping = {uuid.UUID(k): Path(v).resolve() for k, v in (m.split("=", 1) for m in args.map)}
    except ValueError:
        parser.error("--map takes VAULT_ID=FOLDER")
    try:
        settings = get_settings()
        engine = make_sync_engine(settings)
    except SettingsError as exc:
        print(f"OpenNote cannot start: {exc}", file=sys.stderr)
        return 1
    factory = sessionmaker(engine)
    history_root, vault_root = Path(settings.history_root), Path(settings.vault_root)
    failed = False
    try:
        owner = None
        if args.owner:
            with factory() as s:
                key = username_key(args.owner)
                owner = s.scalar(select(User.id).where(User.username_key == key))
            if owner is None:
                print(f"error: no user {args.owner}; create it first", file=sys.stderr)
                return 1
        for p in plan(factory, history_root, vault_root, mapping):
            line = {k: str(v) for k, v in dataclasses.asdict(p).items() if v is not None}
            if p.folder is None or args.dry_run:
                print(json.dumps({"action": "skip" if p.folder is None else "plan", **line}))
                continue
            try:
                with factory.begin() as s:
                    history = HistoryStore(history_root, p.vault_id)
                    name = p.name or p.folder.name
                    rebuild_vault(s, history, p.vault_id, p.folder, name, owner)
                print(json.dumps({"action": "rebuilt", **line}))
            except (HistoryCorrupt, OSError) as exc:
                failed = True
                print(json.dumps({"action": "failed", "error": str(exc), **line}))
    finally:
        engine.dispose()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
