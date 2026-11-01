"""Vault file I/O through directory file descriptors (storage contract §3.3, §4).

Every path is opened segment by segment relative to the vault root's fd with O_NOFOLLOW,
so neither a symlink in the vault nor one swapped in mid-operation can lead outside it.
"""

import errno
import os
import unicodedata
from pathlib import Path

from app.vaults.paths import validate

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class PathEscapeError(Exception):
    """The path is invalid or would leave the vault (a symlink on the way)."""


def open_root(root: Path) -> int:
    """A directory fd for the vault root; the caller closes it. A symlinked root is refused."""
    try:
        return os.open(root, _DIR_FLAGS)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathEscapeError("vault root is not a plain directory") from None
        raise


def _disk_name(dir_fd: int, name: str) -> str:
    """`name` as it is spelled on disk: itself, or the one entry with the same NFC form
    (a vault copied from a Mac holds NFD names)."""
    nfc = unicodedata.normalize("NFC", name)
    try:
        os.stat(nfc, dir_fd=dir_fd, follow_symlinks=False)
        return nfc
    except FileNotFoundError:
        pass
    matches = [e for e in os.listdir(dir_fd) if unicodedata.normalize("NFC", e) == nfc]
    return matches[0] if len(matches) == 1 else nfc


def open_parent(root_fd: int, rel: str, *, create: bool = False) -> tuple[int, str]:
    """A new fd for the directory holding `rel`, and the leaf name as spelled on disk; the
    caller closes the fd. Missing directories are created when `create` is true, otherwise
    FileNotFoundError. Raises PathEscapeError for an invalid path or a symlink on the way."""
    if validate(rel, note=False):
        raise PathEscapeError("invalid vault path")
    *parents, leaf = rel.split("/")
    fd = os.dup(root_fd)
    try:
        for segment in parents:
            name = _disk_name(fd, segment)
            try:
                next_fd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(name, 0o777, dir_fd=fd)
                next_fd = os.open(name, _DIR_FLAGS, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise PathEscapeError("symlink or file in the vault path") from None
                raise
            os.close(fd)
            fd = next_fd
        return fd, _disk_name(fd, leaf)
    except BaseException:
        os.close(fd)
        raise
