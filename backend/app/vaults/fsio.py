"""Vault file I/O through directory file descriptors (storage contract §3.3, §4).

Every path is opened segment by segment relative to the vault root's fd with O_NOFOLLOW,
so neither a symlink in the vault nor one swapped in mid-operation can lead outside it.
"""

import ctypes
import errno
import hashlib
import logging
import os
import secrets
import shutil
import stat
import time
import unicodedata
import uuid
from pathlib import Path

from app.vaults.paths import TEMP_SUFFIX, validate

log = logging.getLogger(__name__)

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


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


def _walk(root_fd: int, parents: list[str], *, create: bool) -> int:
    """A new fd for the directory `parents` names under `root_fd`; the caller closes it."""
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
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_parent(root_fd: int, rel: str, *, create: bool = False) -> tuple[int, str]:
    """A new fd for the directory holding `rel`, and the leaf name as spelled on disk; the
    caller closes the fd. Missing directories are created when `create` is true, otherwise
    FileNotFoundError. Raises PathEscapeError for an invalid path or a symlink on the way."""
    if validate(rel, note=False):
        raise PathEscapeError("invalid vault path")
    *parents, leaf = rel.split("/")
    fd = _walk(root_fd, parents, create=create)
    try:
        return fd, _disk_name(fd, leaf)
    except BaseException:
        os.close(fd)
        raise


def read_file(root_fd: int, rel: str) -> bytes:
    """The bytes of an existing vault file. Only containment is checked, so a file whose
    name breaks the path rules (indexed with a path warning) is still readable."""
    segments = rel.split("/")
    if rel.startswith("/") or any(s in ("", ".", "..") or "\0" in s for s in segments):
        raise PathEscapeError("path leaves the vault")
    dir_fd = _walk(root_fd, segments[:-1], create=False)
    try:
        fd = os.open(_disk_name(dir_fd, segments[-1]), _FILE_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PathEscapeError("symlink in the vault path") from None
        raise
    finally:
        os.close(dir_fd)
    with os.fdopen(fd, "rb") as fh:
        return fh.read()


# Write guard (storage contract §4) --------------------------------------------------------

RENAME_NOREPLACE, RENAME_EXCHANGE = 1, 2
_libc = ctypes.CDLL(None, use_errno=True)
_warned_devices: set[int] = set()


class ExternalChangeError(Exception):
    """The file changed outside OpenNote; nothing of the external change was lost. Its
    bytes are at the target, or at `preserved` in the recovery area."""

    def __init__(self, path: str, found_hash: str | None, preserved: Path | None) -> None:
        super().__init__(f"external change at {path}")
        self.path, self.found_hash, self.preserved = path, found_hash, preserved


def hash_file(dir_fd: int, name: str) -> str:
    """`sha256:<hex>` of the file's bytes, streamed; a symlink is refused (ELOOP)."""
    fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
    with os.fdopen(fd, "rb", buffering=0) as fh:
        return "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()


def _renameat2(olddirfd: int, old: str, newdirfd: int, new: str, flags: int) -> None:
    """renameat2(2) through libc; Python has no wrapper. EINVAL where unsupported."""
    fn = getattr(_libc, "renameat2", None)
    if fn is None:
        raise OSError(errno.EINVAL, "renameat2 is not available")
    if fn(olddirfd, os.fsencode(old), newdirfd, os.fsencode(new), flags) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), new)


def _current_hash(dir_fd: int, name: str) -> str | None:
    try:
        return hash_file(dir_fd, name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise PathEscapeError("symlink in the vault path") from None
        raise


def _warn_no_exchange(dir_fd: int) -> None:
    device = os.fstat(dir_fd).st_dev
    if device not in _warned_devices:
        _warned_devices.add(device)
        log.warning(
            "vault filesystem lacks RENAME_EXCHANGE; external saves racing a write can be "
            "lost (docs/deployment/kubernetes.md)"
        )


def _write_temp(dir_fd: int, name: str, data: bytes, mode: int) -> str:
    tmp = f".{name}.{secrets.token_hex(6)}{TEMP_SUFFIX}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(tmp, flags, mode, dir_fd=dir_fd)
    try:
        os.fchmod(fd, mode)  # the umask must not narrow the target's mode
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(tmp, dir_fd=dir_fd)
        raise
    os.close(fd)
    return tmp


def _move_out(dir_fd: int, name: str, dest_dir: Path, label: str) -> Path:
    """Move `name` (in `dir_fd`) to a new file in `dest_dir`, outside the vault."""
    dest = dest_dir / f"{uuid.uuid7()}-{label}"
    try:
        os.rename(name, dest, src_dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        src = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
        with os.fdopen(src, "rb") as fin, open(dest, "xb") as fout:
            shutil.copyfileobj(fin, fout)
            fout.flush()
            os.fsync(fout.fileno())
        os.unlink(name, dir_fd=dir_fd)
    return dest


def _settle(dir_fd: int, tmp: str, ours: str, recovery_dir: Path, label: str) -> Path | None:
    """Unlink `tmp` if it holds our bytes, otherwise move it to the recovery area."""
    if _current_hash(dir_fd, tmp) == ours:
        os.unlink(tmp, dir_fd=dir_fd)
        return None
    return _move_out(dir_fd, tmp, recovery_dir, label)


def atomic_write(
    root_fd: int, rel: str, data: bytes, *, expected_hash: str | None, recovery_dir: Path
) -> str:
    """Replace (or, with `expected_hash=None`, create) `rel` with `data` and return the new
    hash. ExternalChangeError when the file is not what the caller expected, before or
    during the write; external bytes are never unlinked unverified."""
    dir_fd, name = open_parent(root_fd, rel, create=True)
    try:
        found = _current_hash(dir_fd, name)
        if found != expected_hash:
            raise ExternalChangeError(rel, found, None)
        mode = 0o644
        if expected_hash is not None:
            mode = stat.S_IMODE(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
        new_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        tmp = _write_temp(dir_fd, name, data, mode)  # points temp_written, temp_synced
        if expected_hash is None:
            _create(dir_fd, tmp, name, rel)
        else:
            _replace(dir_fd, tmp, name, rel, expected_hash, new_hash, recovery_dir)
        os.fsync(dir_fd)  # point dir_synced
        return new_hash
    finally:
        os.close(dir_fd)


def _create(dir_fd: int, tmp: str, name: str, rel: str) -> None:
    try:
        _renameat2(dir_fd, tmp, dir_fd, name, RENAME_NOREPLACE)
        return
    except FileExistsError:
        pass
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOSYS):
            os.unlink(tmp, dir_fd=dir_fd)
            raise
        _warn_no_exchange(dir_fd)
        try:
            os.link(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
            os.unlink(tmp, dir_fd=dir_fd)
            return
        except FileExistsError:
            pass
    os.unlink(tmp, dir_fd=dir_fd)  # tmp still holds only our bytes
    raise ExternalChangeError(rel, _current_hash(dir_fd, name), None)


def _replace(
    dir_fd: int,
    tmp: str,
    name: str,
    rel: str,
    expected: str,
    ours: str,
    recovery_dir: Path,
) -> None:
    try:
        _renameat2(dir_fd, tmp, dir_fd, name, RENAME_EXCHANGE)  # point exchanged
    except FileNotFoundError:
        os.unlink(tmp, dir_fd=dir_fd)  # the target vanished: an external delete
        raise ExternalChangeError(rel, None, None) from None
    except OSError as exc:
        if exc.errno not in (errno.EINVAL, errno.ENOSYS):
            os.unlink(tmp, dir_fd=dir_fd)
            raise
        _warn_no_exchange(dir_fd)
        if (found := _current_hash(dir_fd, name)) != expected:
            os.unlink(tmp, dir_fd=dir_fd)
            raise ExternalChangeError(rel, found, None) from None
        os.rename(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)  # the documented window
        return
    displaced = _current_hash(dir_fd, tmp)  # the old target, now at the temp name
    if displaced == expected:
        os.unlink(tmp, dir_fd=dir_fd)  # point displaced_checked
        return
    preserved = None
    if _current_hash(dir_fd, name) == ours:
        _renameat2(dir_fd, tmp, dir_fd, name, RENAME_EXCHANGE)  # external bytes back
        preserved = _settle(dir_fd, tmp, ours, recovery_dir, name)
    else:  # the target changed again: keep the displaced external bytes aside
        preserved = _move_out(dir_fd, tmp, recovery_dir, name)
    os.fsync(dir_fd)
    raise ExternalChangeError(rel, displaced, preserved)


def move_to(root_fd: int, rel: str, dest_dir: Path) -> Path:
    """Move a vault file to a new file in `dest_dir` (the recovery area, outside the
    vault) and return its path; the vault directory is synced."""
    dir_fd, name = open_parent(root_fd, rel)
    try:
        moved = _move_out(dir_fd, name, dest_dir, name)
        os.fsync(dir_fd)
        return moved
    finally:
        os.close(dir_fd)


def clean_stale_temps(root: Path, older_than_ns: int) -> int:
    """Remove in-flight write files older than `older_than_ns`; returns how many."""
    cutoff, removed = time.time_ns() - older_than_ns, 0
    stack = [open_root(root)]
    while stack:
        dir_fd = stack.pop()
        try:
            with os.scandir(dir_fd) as it:
                for entry in it:
                    st = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(os.open(entry.name, _DIR_FLAGS, dir_fd=dir_fd))
                    elif (
                        stat.S_ISREG(st.st_mode)
                        and entry.name.endswith(TEMP_SUFFIX)
                        and st.st_mtime_ns < cutoff
                    ):
                        os.unlink(entry.name, dir_fd=dir_fd)
                        removed += 1
        finally:
            os.close(dir_fd)
    return removed
