"""File identity across scans: what changed on disk since the `files` registry was last
updated, with external renames recognised as moves (storage contract §2.4).

Reads only; nothing is written to the vault or the database.
"""

import logging
import os
import posixpath
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.notes.document import parse_note
from app.notes.frontmatter import read_properties
from app.notes.models import File
from app.vaults.fsio import open_root, read_file
from app.vaults.paths import casefold_key
from app.vaults.scan import ScannedFile

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FsChange:
    kind: Literal["create", "update", "delete", "move"]
    file_id: uuid.UUID | None
    path: str  # the old path for a move
    new_path: str | None  # moves only
    content_hash: str | None  # None for a delete


def _frontmatter_id(root_fd: int, path: str) -> uuid.UUID | None:
    props, _ = read_properties(parse_note(read_file(root_fd, path)))
    try:
        return uuid.UUID(str((props or {})["id"]))
    except KeyError, ValueError:
        return None


def diff_scan(
    session: Session, vault_id: uuid.UUID, scanned: Iterable[ScannedFile], *, root: Path
) -> list[FsChange]:
    """The changes between `scanned` and the live `files` rows of the vault. A delete and
    a create with the same frontmatter `id` (first) or content hash pair into a move;
    among several candidates the same folder wins, then lexical order."""
    rows = session.scalars(select(File).where(File.vault_id == vault_id, ~File.deleted)).all()
    live = {row.path_key: row for row in rows}
    # Every id ever used in the vault, tombstones included: none may be reused.
    taken = set(session.scalars(select(File.file_id).where(File.vault_id == vault_id)))
    changes: list[FsChange] = []
    created: list[ScannedFile] = []
    seen: set[str] = set()
    groups: dict[str, list[ScannedFile]] = {}
    for f in scanned:
        groups.setdefault(casefold_key(f.path), []).append(f)
    for key, group in groups.items():
        seen.add(key)
        row = live.get(key)
        # Case-fold or NFC twins share one identity key: the registered spelling (else the
        # first) is tracked, the others stay untracked with their path warning.
        f = next((g for g in group if row and g.path == row.path), group[0])
        if len(group) > 1:
            log.warning(
                "case-fold twins in the vault; one is tracked", extra={"vault_path": f.path}
            )
        if f.content_hash is None:
            continue  # unreadable: neither edited nor deleted
        if row is None:
            created.append(f)
            continue
        if row.path != f.path:  # a case-only rename
            changes.append(FsChange("move", row.file_id, row.path, f.path, f.content_hash))
        if row.content_hash != f.content_hash:
            changes.append(FsChange("update", row.file_id, f.path, None, f.content_hash))
    deleted = sorted((r for k, r in live.items() if k not in seen), key=lambda r: r.path)
    root_fd = open_root(root)
    try:
        ids = {f.path: _frontmatter_id(root_fd, f.path) for f in created if f.kind == "note"}
    finally:
        os.close(root_fd)
    for f in sorted(created, key=lambda f: f.path):
        folder = posixpath.dirname(f.path)
        fm_id = ids.get(f.path)
        candidates = [r for r in deleted if r.file_id == fm_id] or [
            r for r in deleted if r.content_hash == f.content_hash
        ]
        if candidates:
            match = min(candidates, key=lambda r: (posixpath.dirname(r.path) != folder, r.path))
            deleted.remove(match)
            changes.append(FsChange("move", match.file_id, match.path, f.path, f.content_hash))
            continue
        if fm_id is None or fm_id in taken:
            fm_id = uuid.uuid7()  # no id, or another file owns it: a server-assigned id
        taken.add(fm_id)
        changes.append(FsChange("create", fm_id, f.path, None, f.content_hash))
    changes.extend(FsChange("delete", r.file_id, r.path, None, None) for r in deleted)
    return changes
