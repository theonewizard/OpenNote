"""The vault scanner (storage contract §1.1, §3, §6)."""

import hashlib
import json
import os
import tracemalloc
import unicodedata

import pytest

from app.vaults import scan as scan_module
from app.vaults.scan import MAX_NOTE_BYTES, hash_file, scan
from tests.compatibility.corpus import vault_cases
from tests.conftest import tree_digest


def by_path(root):
    return {f.path: f for f in scan(root)}


@pytest.mark.parametrize("case", vault_cases(), ids=lambda p: p.name)
def test_corpus_vault_trees(case):
    expected = json.loads((case / "expected.json").read_text())["files"]
    got = [
        {"path": f.path, "kind": f.kind, "path_warning": f.path_warning}
        for f in scan(case / "vault")
    ]
    assert got == expected


def test_obsidian_dir_and_trash_are_ignored(obsidian_vault):
    paths = by_path(obsidian_vault)
    assert not [p for p in paths if p.startswith((".obsidian/", ".trash/"))]
    assert "Thumbs.db" not in paths
    assert "Welcome.md" in paths


def test_scan_does_not_modify_the_vault(obsidian_vault):
    before = tree_digest(obsidian_vault)
    list(scan(obsidian_vault))
    assert tree_digest(obsidian_vault) == before


def test_scan_reports_nfc_paths_for_nfd_names(tmp_path):
    nfd_dir = unicodedata.normalize("NFD", "Café")
    nfd_note = unicodedata.normalize("NFD", "Résumé.md")
    (tmp_path / nfd_dir).mkdir()
    (tmp_path / nfd_dir / nfd_note).write_text("x")
    [f] = scan(tmp_path)
    assert f.path == "Café/Résumé.md"
    assert f.disk_name == nfd_note


def test_scanned_file_metadata(tmp_path):
    (tmp_path / "a.md").write_bytes(b"hello")
    [f] = scan(tmp_path)
    st = (tmp_path / "a.md").stat()
    assert (f.size, f.mtime_ns, f.inode) == (5, st.st_mtime_ns, st.st_ino)
    assert f.content_hash == "sha256:" + hashlib.sha256(b"hello").hexdigest()
    assert f.kind == "note" and not f.path_warning


def test_symlinks_and_special_files_are_skipped(tmp_path, caplog):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.md").write_text("s")
    (tmp_path / "linkdir").symlink_to(outside)
    (tmp_path / "link.md").symlink_to(outside / "secret.md")
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "real.md").write_text("r")
    assert list(by_path(tmp_path)) == ["real.md"]
    assert caplog.text.count("unsupported vault entry") == 3


def test_case_fold_collision_flags_both(tmp_path):
    (tmp_path / "Note.md").write_text("a")
    (tmp_path / "note.md").write_text("b")
    assert all(f.path_warning for f in scan(tmp_path))


def test_invalid_names_are_scanned_with_a_warning(tmp_path):
    (tmp_path / "CON.md").write_text("a")
    (tmp_path / "trailing.").write_text("b")
    paths = by_path(tmp_path)
    assert paths["CON.md"].path_warning and paths["trailing."].path_warning


def test_temp_files_are_skipped(tmp_path):
    (tmp_path / ".a.md.x1.opennote-tmp").write_text("t")
    (tmp_path / "b.opennote-tmp").write_text("t")
    assert list(scan(tmp_path)) == []


def test_oversized_note_is_opaque(tmp_path):
    with open(tmp_path / "huge.md", "wb") as fh:
        fh.truncate(MAX_NOTE_BYTES + 1)
    [f] = scan(tmp_path)
    assert f.kind == "attachment"


def test_hashing_streams_large_file(tmp_path):
    with open(tmp_path / "big.bin", "wb") as fh:
        fh.truncate(64 * 1024**2)  # sparse, 8x the memory bound: a whole-file read fails
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    tracemalloc.start()
    try:
        digest = hash_file(fd, "big.bin")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        os.close(fd)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert peak < 8 * 1024**2


def test_hash_file_refuses_symlink(tmp_path):
    (tmp_path / "t").write_text("x")
    (tmp_path / "l").symlink_to(tmp_path / "t")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError):
            hash_file(fd, "l")
    finally:
        os.close(fd)


def test_known_files_with_unchanged_stat_are_not_rehashed(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.md").write_text("b")
    known = {f.path: f for f in scan(tmp_path)}
    (tmp_path / "b.md").write_text("changed")
    hashed = []
    real = scan_module.hash_file
    monkeypatch.setattr(
        scan_module, "hash_file", lambda fd, name: hashed.append(name) or real(fd, name)
    )
    again = {f.path: f for f in scan(tmp_path, known=known)}
    assert hashed == ["b.md"]
    assert (
        again["a.md"] == known["a.md"] and again["b.md"].content_hash != known["b.md"].content_hash
    )
