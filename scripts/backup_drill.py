"""Restore drill helper (docs/deployment/backup.md, "Restore drill"): writes revisions through
OpenNote's commit path, and checks a restored server against what was written.

Runs where the backend runs, with OpenNote's settings in the environment (the api image:
`docker compose exec -T api python - <command> < scripts/backup_drill.py`; a working copy:
`.venv/bin/python scripts/backup_drill.py <command>` with backend/ on PYTHONPATH).

    seed             register the vault "drill" and commit creates, updates, moves and deletes
    churn SECONDS    keep committing to "drill" for SECONDS (run during a backup)
    fingerprint      print every vault's revisions, revision log and live files as JSON
    verify           run recovery on every vault and check the invariants below

The invariants after recovery, per vault: the revision log holds exactly the database's
revisions; every revision's bytes are in the history store and match its hash; every live
file in the database is in the vault with the database's hash. Exits 0 when all hold.
"""

import hashlib
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.db import make_sync_engine
from app.notes.models import File
from app.sync.commit import Committer, Create, Delete, Move, Update
from app.sync.history import HistoryCorrupt, HistoryStore
from app.sync.models import Revision
from app.vaults.fsio import hash_path, open_root
from app.vaults.models import Vault
from app.vaults.registry import register_vault
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

DEVICE = "backup-drill"


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def committer(factory: sessionmaker[Session], vault: Vault) -> Committer:
    history = HistoryStore(Path(get_settings().history_root), vault.id)
    return Committer(factory, history, open_root(Path(vault.root_path)), vault.id)


def vaults(factory: sessionmaker[Session]) -> list[Vault]:
    with factory() as s:
        rows = list(s.scalars(select(Vault).order_by(Vault.root_path)))
        s.expunge_all()
    return rows


def ok(result: Any) -> Any:
    if result.status not in ("applied", "duplicate"):
        raise SystemExit(f"commit failed: {result}")
    return result


def seed(factory: sessionmaker[Session]) -> None:
    root = Path(get_settings().vault_root) / "drill"
    root.mkdir()
    with factory.begin() as s:
        register_vault(s, root, "drill")
    (vault,) = [v for v in vaults(factory) if v.root_path == str(root)]
    c = committer(factory, vault)
    files = {}
    for i in range(20):
        data = f"# Note {i}\n\nfirst version\n".encode()
        file_id = uuid.uuid7()
        files[file_id] = ok(
            c.commit(
                Create(uuid.uuid7(), file_id, f"notes/n{i:02}.md", "note", sha(data)), DEVICE, data
            )
        )
    for round_ in range(3):
        for file_id, result in list(files.items()):
            data = f"# Note\n\nversion {round_ + 2} of {file_id}\n".encode()
            files[file_id] = ok(
                c.commit(Update(uuid.uuid7(), file_id, result.revision, sha(data)), DEVICE, data)
            )
    ids = list(files)
    for file_id in ids[:2]:
        files[file_id] = ok(
            c.commit(
                Move(uuid.uuid7(), file_id, files[file_id].revision, f"moved/{file_id}.md"),
                DEVICE,
                None,
            )
        )
    for file_id in ids[2:4]:
        ok(c.commit(Delete(uuid.uuid7(), file_id, files[file_id].revision), DEVICE, None))
    image = bytes(range(256)) * 64  # an attachment
    ok(
        c.commit(
            Create(uuid.uuid7(), uuid.uuid7(), "attachments/blob.bin", "attachment", sha(image)),
            DEVICE,
            image,
        )
    )
    print(f"seeded vault {vault.id}")


def churn(factory: sessionmaker[Session], seconds: float) -> None:
    (vault,) = [v for v in vaults(factory) if v.root_path.endswith("/drill")]
    c = committer(factory, vault)
    rng = random.Random(0)  # noqa: S311 - a reproducible workload, not a secret
    live: dict[uuid.UUID, int] = {}
    deadline, n = time.monotonic() + seconds, 0
    while time.monotonic() < deadline:
        n += 1
        data = f"churn {n}\n".encode()
        if live and rng.random() < 0.7:
            file_id = rng.choice(list(live))
            live[file_id] = ok(
                c.commit(Update(uuid.uuid7(), file_id, live[file_id], sha(data)), DEVICE, data)
            ).revision
        else:
            file_id = uuid.uuid7()
            live[file_id] = ok(
                c.commit(
                    Create(uuid.uuid7(), file_id, f"churn/c{n}.md", "note", sha(data)), DEVICE, data
                )
            ).revision
    print(f"churned {n} commits")


def fingerprint(factory: sessionmaker[Session]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for vault in vaults(factory):
        with factory() as s:
            revisions = [
                [r.seq, str(r.file_id), r.revision, r.path, r.content_hash, r.deleted]
                for r in s.scalars(
                    select(Revision).where(Revision.vault_id == vault.id).order_by(Revision.seq)
                )
            ]
            live = {
                f.path: f.content_hash
                for f in s.scalars(
                    select(File).where(File.vault_id == vault.id, File.deleted.is_(False))
                )
            }
        history = HistoryStore(Path(get_settings().history_root), vault.id)
        root = Path(vault.root_path)
        on_disk = {
            str(p.relative_to(root)): sha(p.read_bytes())
            for p in sorted(root.rglob("*"))
            if p.is_file() and ".opennote" not in p.relative_to(root).parts
        }
        out[str(vault.id)] = {
            "root": vault.root_path,
            "revisions": revisions,
            "log": [e.seq for e in history.read_log()],
            "live": live,
            "vault": on_disk,
        }
    return out


def verify(factory: sessionmaker[Session]) -> None:
    failures = []
    for vault in vaults(factory):
        c = committer(factory, vault)
        c.recover()
        with factory() as s:
            revisions = list(s.scalars(select(Revision).where(Revision.vault_id == vault.id)))
            live = list(
                s.scalars(select(File).where(File.vault_id == vault.id, File.deleted.is_(False)))
            )
        logged = sorted(e.seq for e in c.history.read_log())
        if logged != sorted(r.seq for r in revisions):
            failures.append(f"{vault.id}: the revision log differs from the database")
        for r in revisions:
            try:
                good = not r.content_hash or sha(c.history.get(r.content_hash)) == r.content_hash
            except OSError, HistoryCorrupt:
                good = False
            if not good:
                failures.append(f"{vault.id}: history object of seq {r.seq} does not match")
        for f in live:
            if hash_path(c.root_fd, f.path) != f.content_hash:
                failures.append(f"{vault.id}: {f.path} in the vault differs from the database")
        os.close(c.root_fd)
        print(f"vault {vault.id}: {len(revisions)} revisions, {len(live)} live files checked")
    if not vaults(factory):
        failures.append("no vault was restored")
    if failures:
        raise SystemExit("\n".join(failures))
    print("restore verified")


def main() -> None:
    factory = sessionmaker(make_sync_engine(get_settings()))
    command, args = sys.argv[1], sys.argv[2:]
    if command == "seed":
        seed(factory)
    elif command == "churn":
        churn(factory, float(args[0]))
    elif command == "fingerprint":
        print(json.dumps(fingerprint(factory), sort_keys=True))
    elif command == "verify":
        verify(factory)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
