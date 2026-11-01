"""File identity across external renames (storage contract §2.4)."""

import os
import uuid

import pytest

from app.notes.identity import FsChange, diff_scan
from app.vaults.registry import open_vault
from app.vaults.scan import scan
from tests.conftest import tree_digest
from tests.integration.test_index_rebuild import add_files


@pytest.fixture
def vault(obsidian_vault, session):
    vault_id = open_vault(session, obsidian_vault)
    ids = add_files(session, vault_id, obsidian_vault)
    return obsidian_vault, vault_id, ids


def diff(session, vault_id, root):
    return diff_scan(session, vault_id, scan(root), root=root)


def test_unchanged_vault_has_no_changes(vault, session):
    root, vault_id, _ = vault
    assert diff(session, vault_id, root) == []


def test_create_update_delete(vault, session):
    root, vault_id, ids = vault
    (root / "New.md").write_text("fresh\n")
    (root / "Welcome.md").write_text("edited\n")
    (root / "Projects" / "Board.canvas").unlink()
    changes = {c.kind: c for c in diff(session, vault_id, root)}
    assert set(changes) == {"create", "update", "delete"}
    assert changes["update"].file_id == ids["Welcome.md"] and changes["update"].path == "Welcome.md"
    assert changes["delete"] == FsChange(
        "delete", ids["Projects/Board.canvas"], "Projects/Board.canvas", None, None
    )
    assert changes["create"].path == "New.md" and isinstance(changes["create"].file_id, uuid.UUID)
    assert changes["create"].file_id not in ids.values()


def test_external_rename_keeps_identity(vault, session):
    root, vault_id, ids = vault
    os.rename(root / "Projects" / "Plan.md", root / "Projects" / "Roadmap.md")
    [change] = diff(session, vault_id, root)
    assert change.kind == "move" and change.file_id == ids["Projects/Plan.md"]
    assert (change.path, change.new_path) == ("Projects/Plan.md", "Projects/Roadmap.md")


def test_rename_with_edit_in_same_batch_is_delete_plus_create(vault, session):
    # Documented limit: no id and a changed hash leave nothing to pair on.
    root, vault_id, _ = vault
    os.rename(root / "Welcome.md", root / "Hello.md")
    (root / "Hello.md").write_text("changed while renamed\n")
    kinds = sorted(c.kind for c in diff(session, vault_id, root))
    assert kinds == ["create", "delete"]


def test_frontmatter_id_wins_over_hash(obsidian_vault, session):
    # B.md is an edited copy of A.md (same id, so B got its own file id). Both disappear
    # and N.md appears with B's exact bytes: the hash says B, the id says A; the id wins.
    note_id = uuid.uuid7()
    (obsidian_vault / "A.md").write_text(f"---\nid: {note_id}\n---\na\n")
    (obsidian_vault / "B.md").write_text(f"---\nid: {note_id}\n---\nb\n")
    vault_id = open_vault(session, obsidian_vault)
    ids = add_files(session, vault_id, obsidian_vault)
    from app.notes.models import File

    session.get(File, ids["A.md"]).file_id = note_id  # as ingest adopts the id
    session.flush()
    os.rename(obsidian_vault / "B.md", obsidian_vault / "N.md")
    (obsidian_vault / "A.md").unlink()
    changes = sorted(diff(session, vault_id, obsidian_vault), key=lambda c: c.kind)
    assert [(c.kind, c.file_id, c.new_path) for c in changes] == [
        ("delete", ids["B.md"], None),
        ("move", note_id, "N.md"),
    ]


def test_several_candidates_prefer_the_same_folder(vault, session):
    root, vault_id, ids = vault
    (root / "X").mkdir()
    (root / "X" / "Copy.md").write_bytes((root / "Welcome.md").read_bytes())
    more = add_files(session, vault_id, root, ids)
    os.rename(root / "X" / "Copy.md", root / "X" / "Zed.md")
    os.rename(root / "Welcome.md", root / "Zed.md")
    # Lexical order alone would hand Welcome.md to X/Zed.md.
    moves = {c.new_path: c.file_id for c in diff(session, vault_id, root) if c.kind == "move"}
    assert moves == {"X/Zed.md": more["X/Copy.md"], "Zed.md": ids["Welcome.md"]}


def test_copied_file_with_duplicate_id_gets_new_identity(vault, session):
    root, vault_id, ids = vault
    from app.notes.models import File

    note_id = uuid.uuid7()
    (root / "Welcome.md").write_text(f"---\nid: {note_id}\n---\nhi\n")
    session.get(File, ids["Welcome.md"]).file_id = note_id
    session.flush()
    (root / "Welcome copy.md").write_bytes((root / "Welcome.md").read_bytes())
    changes = diff(session, vault_id, root)
    [create] = [c for c in changes if c.kind == "create"]
    assert create.path == "Welcome copy.md" and create.file_id != note_id
    assert sorted(c.kind for c in changes) == ["create", "update"]


def test_new_note_with_unused_frontmatter_id_adopts_it(vault, session):
    root, vault_id, _ = vault
    note_id = uuid.uuid7()
    (root / "Imported.md").write_text(f"---\nid: {note_id}\n---\n")
    [change] = diff(session, vault_id, root)
    assert change.kind == "create" and change.file_id == note_id


def test_no_id_written_on_open(vault, session):
    root, vault_id, _ = vault
    (root / "New.md").write_text("no id here\n")
    before = tree_digest(root)
    diff(session, vault_id, root)
    assert tree_digest(root) == before


def test_an_unreadable_file_is_neither_edited_nor_deleted(vault, session, monkeypatch):
    from app.vaults import scan as scan_module

    root, vault_id, _ = vault
    real = scan_module.hash_file

    def denied(dir_fd, name):
        if name == "Welcome.md":
            raise PermissionError(13, "Permission denied")
        return real(dir_fd, name)

    monkeypatch.setattr(scan_module, "hash_file", denied)
    (root / "Welcome.md").write_text("changed, but we cannot read it\n")
    assert diff(session, vault_id, root) == []


def test_a_case_fold_twin_does_not_flip_the_registry(vault, session):
    root, vault_id, _ = vault
    (root / "welcome.md").write_text("a twin only Linux can hold\n")
    assert diff(session, vault_id, root) == []  # the registered spelling keeps its row
