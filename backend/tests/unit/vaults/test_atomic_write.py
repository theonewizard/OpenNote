"""Atomic vault writes with the external-change guard (storage contract §4)."""

import errno
import hashlib
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.vaults import fsio
from app.vaults.fsio import (
    ExternalChangeError,
    PathEscapeError,
    atomic_write,
    clean_stale_temps,
    hash_path,
    move_to,
    open_root,
    rename_noreplace,
)
from app.vaults.paths import classify

OLD, NEW, EXT, EXT2 = b"old\n", b"new\n", b"external\n", b"external two\n"
BACKEND = Path(__file__).resolve().parents[3]


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    (root / "n.md").write_bytes(OLD)
    fd = open_root(root)
    yield root, fd
    os.close(fd)


@pytest.fixture
def recovery(tmp_path):
    path = tmp_path / "recovery"
    path.mkdir()
    return path


def temps(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.name.endswith(".opennote-tmp")]


def test_replace_writes_new_bytes(vault, recovery):
    root, fd = vault
    assert atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery) == sha(NEW)
    assert (root / "n.md").read_bytes() == NEW
    assert temps(root) == [] and list(recovery.iterdir()) == []


def test_replace_keeps_the_file_mode(vault, recovery):
    root, fd = vault
    (root / "n.md").chmod(0o600)
    atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    assert (root / "n.md").stat().st_mode & 0o777 == 0o600


def test_create_writes_a_new_file_and_parents(vault, recovery):
    root, fd = vault
    atomic_write(fd, "a/b/c.md", NEW, expected_hash=None, recovery_dir=recovery)
    assert (root / "a/b/c.md").read_bytes() == NEW


def test_external_edit_is_not_clobbered(vault, recovery):
    root, fd = vault
    (root / "n.md").write_bytes(EXT)
    with pytest.raises(ExternalChangeError) as err:
        atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    assert (root / "n.md").read_bytes() == EXT
    assert err.value.found_hash == sha(EXT) and err.value.preserved is None
    assert temps(root) == []


def test_create_refuses_existing_target(vault, recovery):
    root, fd = vault
    with pytest.raises(ExternalChangeError):
        atomic_write(fd, "n.md", NEW, expected_hash=None, recovery_dir=recovery)
    assert (root / "n.md").read_bytes() == OLD


def test_create_refuses_target_appearing_before_the_rename(vault, recovery, monkeypatch):
    root, fd = vault
    real = fsio._renameat2

    def appear_first(*args):
        (root / "late.md").write_bytes(EXT)
        return real(*args)

    monkeypatch.setattr(fsio, "_renameat2", appear_first)
    with pytest.raises(ExternalChangeError):
        atomic_write(fd, "late.md", NEW, expected_hash=None, recovery_dir=recovery)
    assert (root / "late.md").read_bytes() == EXT and temps(root) == []


def external_save(target: Path, data: bytes, style: str) -> None:
    if style == "rename_save":
        side = target.with_name("editor-swap")
        side.write_bytes(data)
        os.rename(side, target)
    else:
        with open(target, "r+b") as fh:
            fh.truncate(0)
            fh.write(data)


@pytest.mark.parametrize("style", ["rename_save", "in_place_write"])
def test_external_edit_racing_the_exchange_survives(vault, recovery, monkeypatch, style, caplog):
    root, fd = vault
    real, calls = fsio._renameat2, []

    def racing(*args):
        if not calls:
            external_save(root / "n.md", EXT, style)
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(fsio, "_renameat2", racing)
    with pytest.raises(ExternalChangeError) as err:
        atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    assert (root / "n.md").read_bytes() == EXT
    assert err.value.found_hash == sha(EXT) and err.value.preserved is None
    assert temps(root) == [] and "RENAME_EXCHANGE" not in caplog.text  # no fallback here


def test_second_external_save_after_the_exchange_preserves_both(vault, recovery, monkeypatch):
    root, fd = vault
    real, calls = fsio._renameat2, []

    def racing(*args):
        if not calls:
            external_save(root / "n.md", EXT, "rename_save")
        calls.append(args)
        result = real(*args)
        if len(calls) == 1:
            external_save(root / "n.md", EXT2, "rename_save")
        return result

    monkeypatch.setattr(fsio, "_renameat2", racing)
    with pytest.raises(ExternalChangeError) as err:
        atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    assert (root / "n.md").read_bytes() == EXT2
    assert err.value.preserved is not None and err.value.preserved.read_bytes() == EXT
    assert err.value.preserved.parent == recovery
    assert temps(root) == []


def test_einval_falls_back_and_warns(vault, recovery, monkeypatch, caplog):
    root, fd = vault

    def no_exchange(*args):
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(fsio, "_renameat2", no_exchange)
    monkeypatch.setattr(fsio, "_warned_devices", set())
    atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    atomic_write(fd, "new.md", OLD, expected_hash=None, recovery_dir=recovery)
    assert (root / "n.md").read_bytes() == NEW and (root / "new.md").read_bytes() == OLD
    assert caplog.text.count("RENAME_EXCHANGE") == 1
    (root / "n.md").write_bytes(EXT)
    with pytest.raises(ExternalChangeError):
        atomic_write(fd, "n.md", OLD, expected_hash=sha(NEW), recovery_dir=recovery)
    with pytest.raises(ExternalChangeError):
        atomic_write(fd, "new.md", NEW, expected_hash=None, recovery_dir=recovery)
    assert temps(root) == []


def test_enospc_leaves_old_bytes_and_no_temp(vault, recovery, monkeypatch):
    root, fd = vault

    def full(fd, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", full)
    with pytest.raises(OSError) as err:
        atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    monkeypatch.undo()
    assert err.value.errno == errno.ENOSPC
    assert (root / "n.md").read_bytes() == OLD and temps(root) == []


def test_atomic_write_refuses_symlinked_directory(vault, recovery, tmp_path):
    root, fd = vault
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "d").symlink_to(outside)
    with pytest.raises(PathEscapeError):
        atomic_write(fd, "d/x.md", NEW, expected_hash=None, recovery_dir=recovery)
    assert list(outside.iterdir()) == []


def test_atomic_write_refuses_a_symlink_target(vault, recovery, tmp_path):
    root, fd = vault
    (tmp_path / "secret").write_bytes(OLD)
    (root / "l.md").symlink_to(tmp_path / "secret")
    with pytest.raises((PathEscapeError, ExternalChangeError)):
        atomic_write(fd, "l.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    assert (tmp_path / "secret").read_bytes() == OLD


def test_temp_name_is_hidden_and_ignored_by_classify(vault, recovery, monkeypatch):
    _, fd = vault
    seen = []
    real = fsio._renameat2

    def spy(olddirfd, old, newdirfd, new, flags):
        seen.append(old)
        return real(olddirfd, old, newdirfd, new, flags)

    monkeypatch.setattr(fsio, "_renameat2", spy)
    atomic_write(fd, "n.md", NEW, expected_hash=sha(OLD), recovery_dir=recovery)
    [name] = seen
    assert name.startswith(".n.md.") and classify(name) == "temp"


CRASH_SCRIPT = textwrap.dedent(
    """
    import hashlib, os, sys
    from pathlib import Path
    from app.vaults import fsio

    root, recovery, point = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    fsyncs, renames = [], []
    real_fsync, real_rename = os.fsync, fsio._renameat2

    def fsync(fd):
        fsyncs.append(fd)
        if point == "temp_written" and len(fsyncs) == 1:
            os._exit(1)
        if point == "displaced_checked" and len(fsyncs) == 2:
            os._exit(1)
        real_fsync(fd)
        if point == "dir_synced" and len(fsyncs) == 2:
            os._exit(1)

    def rename(*args):
        if point == "temp_synced":
            os._exit(1)
        real_rename(*args)
        if point == "exchanged":
            os._exit(1)

    os.fsync, fsio._renameat2 = fsync, rename
    old = "sha256:" + hashlib.sha256(b"old\\n").hexdigest()
    fd = fsio.open_root(root)
    fsio.atomic_write(fd, "n.md", b"new\\n", expected_hash=old, recovery_dir=recovery)
    os._exit(0)
    """
)


@pytest.mark.parametrize(
    "point", ["temp_written", "temp_synced", "exchanged", "displaced_checked", "dir_synced"]
)
def test_crash_at_each_point_leaves_old_or_new_bytes(vault, recovery, point):
    root, _ = vault
    result = subprocess.run(  # noqa: S603 - fixed script, test paths
        [sys.executable, "-c", CRASH_SCRIPT, str(root), str(recovery), point],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert (root / "n.md").read_bytes() in (OLD, NEW)
    leftovers = [p.read_bytes() for p in temps(root)]
    assert all(data in (OLD, NEW) for data in leftovers)  # a temp never holds foreign bytes


def test_move_to_moves_out_of_the_vault(vault, tmp_path):
    root, fd = vault
    dest = tmp_path / "trash"
    dest.mkdir()
    moved = move_to(fd, "n.md", dest)
    assert moved.parent == dest and moved.read_bytes() == OLD
    assert not (root / "n.md").exists()


def test_move_to_copies_across_filesystems(vault, tmp_path, monkeypatch):
    root, fd = vault
    dest = tmp_path / "trash"
    dest.mkdir()
    real = os.rename

    def cross_device(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
        if src_dir_fd is not None and Path(dst).is_absolute():
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

    monkeypatch.setattr(os, "rename", cross_device)
    moved = move_to(fd, "n.md", dest)
    assert moved.read_bytes() == OLD and not (root / "n.md").exists()


def test_clean_stale_temps(vault):
    root, _ = vault
    (root / "sub").mkdir()
    stale, fresh = root / "sub" / ".x.md.ab.opennote-tmp", root / ".y.md.cd.opennote-tmp"
    stale.write_bytes(b"s")
    fresh.write_bytes(b"f")
    hour_ago = time.time_ns() - 2 * 3600 * 10**9
    os.utime(stale, ns=(hour_ago, hour_ago))
    assert clean_stale_temps(root, older_than_ns=3600 * 10**9) == 1
    assert not stale.exists() and fresh.exists() and (root / "n.md").exists()


def test_hash_path(vault):
    _root, fd = vault
    assert hash_path(fd, "n.md") == sha(OLD)
    assert hash_path(fd, "missing.md") is None


def test_rename_noreplace_moves_when_source_is_expected(vault):
    root, fd = vault
    rename_noreplace(fd, "n.md", "sub/m.md", expected_hash=sha(OLD))
    assert (root / "sub/m.md").read_bytes() == OLD and not (root / "n.md").exists()


def test_rename_noreplace_refuses_changed_source_or_taken_target(vault):
    root, fd = vault
    with pytest.raises(ExternalChangeError):
        rename_noreplace(fd, "n.md", "m.md", expected_hash=sha(NEW))
    (root / "m.md").write_bytes(EXT)
    with pytest.raises(ExternalChangeError):
        rename_noreplace(fd, "n.md", "m.md", expected_hash=sha(OLD))
    assert (root / "n.md").read_bytes() == OLD and (root / "m.md").read_bytes() == EXT


def test_rename_noreplace_falls_back_without_renameat2(vault, monkeypatch):
    root, fd = vault

    def no_flags(*args):
        raise OSError(errno.EINVAL, "Invalid argument")

    monkeypatch.setattr(fsio, "_renameat2", no_flags)
    rename_noreplace(fd, "n.md", "m.md", expected_hash=sha(OLD))
    assert (root / "m.md").read_bytes() == OLD and not (root / "n.md").exists()


def test_rename_noreplace_reports_a_missing_source_folder(vault):
    _, fd = vault
    with pytest.raises(ExternalChangeError) as err:
        rename_noreplace(fd, "gone/n.md", "m.md", expected_hash=sha(OLD))
    assert err.value.found_hash is None
