"""Containment (storage contract §3.3): every vault path resolves inside the vault, through
directory fds and O_NOFOLLOW, never through a symlink."""

import os
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.vaults.fsio import PathEscapeError, open_parent, open_root
from app.vaults.paths import validate


def _fd_path(fd: int) -> Path:
    return Path(os.readlink(f"/proc/self/fd/{fd}"))


@settings(max_examples=300, deadline=None)
@given(path=st.text(alphabet=st.characters(codec="utf-8"), max_size=60))
def test_validated_paths_never_escape(tmp_path_factory, path):
    if validate(path, note=False):
        return
    root = tmp_path_factory.mktemp("v")
    root_fd = open_root(root)
    try:
        fd, leaf = open_parent(root_fd, path, create=True)
        try:
            assert _fd_path(fd).is_relative_to(root)
            assert "/" not in leaf
        finally:
            os.close(fd)
    finally:
        os.close(root_fd)


def test_parent_dirs_resolved_and_created(tmp_path):
    root_fd = open_root(tmp_path)
    fd, leaf = open_parent(root_fd, "a/b/c.md", create=True)
    assert _fd_path(fd) == tmp_path / "a" / "b" and leaf == "c.md"


def test_missing_parent_without_create_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_parent(open_root(tmp_path), "nope/c.md")


def test_symlinked_parent_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a").symlink_to(outside)
    with pytest.raises(PathEscapeError):
        open_parent(open_root(vault), "a/x.md")


def test_symlinked_root_is_refused(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(PathEscapeError):
        open_root(tmp_path / "link")


def test_invalid_path_is_refused(tmp_path):
    with pytest.raises(PathEscapeError):
        open_parent(open_root(tmp_path), "../x.md")


def test_nfd_name_on_disk_resolves(tmp_path):
    (tmp_path / "Café").mkdir()
    fd, leaf = open_parent(open_root(tmp_path), "Café/x.md")
    assert _fd_path(fd).name == "Café" and leaf == "x.md"
