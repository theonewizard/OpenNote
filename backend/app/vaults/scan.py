"""Walk a vault and describe every note and attachment (storage contract §1.1, §3, §6).

The scan reads only: no symlink is followed, nothing in a dot-folder is opened, and every
open goes through a directory fd with O_NOFOLLOW.
"""

import logging
import os
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from app.vaults.fsio import hash_file, open_root
from app.vaults.paths import FileKind, casefold_key, classify, normalize, validate

log = logging.getLogger(__name__)

MAX_NOTE_BYTES = 16 * 1024 * 1024  # a larger .md is indexed as an opaque attachment
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class ScannedFile:
    path: str  # vault-relative, NFC
    disk_name: str  # the leaf name exactly as spelled on disk
    kind: FileKind
    size: int
    mtime_ns: int
    inode: int
    content_hash: str | None  # None: the file could not be read; treat it as unchanged
    path_warning: bool


def scan(root: Path, known: Mapping[str, ScannedFile] | None = None) -> Iterator[ScannedFile]:
    """Every note and attachment under `root`, sorted by path within each folder. A file
    whose (size, mtime_ns, inode) match its entry in `known` keeps that entry's hash."""
    root_fd = open_root(root)
    try:
        yield from _scan_dir(root_fd, "", known or {})
    finally:
        os.close(root_fd)


def _scan_dir(dir_fd: int, prefix: str, known: Mapping[str, ScannedFile]) -> Iterator[ScannedFile]:
    with os.scandir(dir_fd) as it:
        entries = sorted(it, key=lambda e: normalize(e.name))
    keys = [casefold_key(e.name) for e in entries]
    for entry, key in zip(entries, keys, strict=True):
        path = prefix + normalize(entry.name)
        kind = classify(path)
        if kind not in ("note", "attachment"):
            continue  # dot-folders, config, OS cruft, in-flight writes: never read
        try:
            st = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue  # removed during the scan
        if stat.S_ISDIR(st.st_mode):
            sub_fd = os.open(entry.name, _DIR_FLAGS, dir_fd=dir_fd)
            try:
                yield from _scan_dir(sub_fd, path + "/", known)
            finally:
                os.close(sub_fd)
        elif stat.S_ISREG(st.st_mode):
            if kind == "note" and st.st_size > MAX_NOTE_BYTES:
                kind = "attachment"
            warning = bool(validate(path, note=kind == "note")) or keys.count(key) > 1
            old = known.get(path)
            same = old and (old.size, old.mtime_ns, old.inode) == (
                st.st_size,
                st.st_mtime_ns,
                st.st_ino,
            )
            content_hash: str | None = old.content_hash if old and same else None
            if content_hash is None:
                try:
                    content_hash = hash_file(dir_fd, entry.name)
                except FileNotFoundError:
                    continue  # removed during the scan: the next one reports the delete
                except OSError:  # unreadable (permissions, a swapped-in symlink)
                    log.warning("unreadable vault file kept as is", extra={"vault_path": path})
            yield ScannedFile(
                path=path,
                disk_name=entry.name,
                kind=kind,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                inode=st.st_ino,
                content_hash=content_hash,
                path_warning=warning,
            )
        else:
            log.warning("unsupported vault entry skipped", extra={"vault_path": path})
