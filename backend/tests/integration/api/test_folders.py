"""Folders (P2-05): listing with empty folders, create, move as one revision per file,
delete."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.notes.models import File
from app.sync.models import Revision
from app.vaults.models import Vault

pytestmark = pytest.mark.anyio


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


async def _note(api, headers, vault, path):
    response = await api.client.post(
        "/api/v1/notes", json={"vault_id": str(vault), "path": path}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def test_list_includes_empty_and_implied_folders_with_counts(api, owner):
    vault, headers = owner
    root = _root(api, vault)
    for path in ["A/B/one.md", "A/two.md", "A/three.md"]:
        await _note(api, headers, vault, path)
    (root / "Empty/Inner").mkdir(parents=True)
    (root / ".obsidian/plugins").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "A/pic.png").write_bytes(b"png")  # on disk only: not counted until ingested
    response = await api.client.get(f"/api/v1/folders?vault_id={vault}", headers=headers)
    assert response.status_code == 200
    items = {f["path"]: f for f in response.json()["items"]}
    assert list(items) == ["A", "A/B", "Empty", "Empty/Inner"]
    assert items["A"] == {
        "path": "A",
        "name": "A",
        "parent": None,
        "note_count": 2,
        "attachment_count": 0,
    }
    assert items["A/B"]["parent"] == "A"
    assert items["A/B"]["note_count"] == 1
    assert items["Empty/Inner"]["note_count"] == 0


async def test_create_folder(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    headers = await api.bearer(alice)
    body = {"vault_id": str(vault), "path": "New/Sub"}
    response = await api.client.post("/api/v1/folders", json=body, headers=headers)
    assert response.status_code == 201
    assert response.json() == {
        "path": "New/Sub",
        "name": "Sub",
        "parent": "New",
        "note_count": 0,
        "attachment_count": 0,
    }
    assert (_root(api, vault) / "New/Sub").is_dir()
    assert (await api.client.post("/api/v1/folders", json=body, headers=headers)).status_code == 409
    upper = body | {"path": "new/sub"}
    assert (
        await api.client.post("/api/v1/folders", json=upper, headers=headers)
    ).status_code == 409
    for bad in ["../x", ".git", "a/./b", "a:b", "a//b"]:
        response = await api.client.post(
            "/api/v1/folders", json=body | {"path": bad}, headers=headers
        )
        assert response.status_code == 422, bad
    viewer = await api.bearer(bob)
    response = await api.client.post("/api/v1/folders", json=body | {"path": "V"}, headers=viewer)
    assert response.status_code == 403
    outsider = await api.bearer(api.user("carol"))
    listed = await api.client.get(f"/api/v1/folders?vault_id={vault}", headers=outsider)
    assert listed.status_code == 404


async def test_create_folder_is_idempotent(api, owner):
    vault, headers = owner
    keyed = headers | {"Idempotency-Key": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"}
    body = {"vault_id": str(vault), "path": "Once"}
    first = await api.client.post("/api/v1/folders", json=body, headers=keyed)
    second = await api.client.post("/api/v1/folders", json=body, headers=keyed)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()


async def test_move_is_one_revision_per_file(api, owner):
    vault, headers = owner
    root = _root(api, vault)
    notes = [await _note(api, headers, vault, p) for p in ["Old/b.md", "Old/a.md", "Old/S/c.md"]]
    await _note(api, headers, vault, "Elsewhere.md")
    (root / "Old/Empty").mkdir()
    body = {"vault_id": str(vault), "path": "Old", "new_path": "Arch/New"}
    response = await api.client.patch("/api/v1/folders", json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "folder": {
            "path": "Arch/New",
            "name": "New",
            "parent": "Arch",
            "note_count": 2,
            "attachment_count": 0,
        },
        "moved_files": 3,
    }
    with Session(api.engine) as s:
        moves = s.execute(
            select(Revision.path, Revision.revision)
            .where(Revision.op == "move")
            .order_by(Revision.seq)
        ).all()
    assert moves == [("Arch/New/S/c.md", 2), ("Arch/New/a.md", 2), ("Arch/New/b.md", 2)]
    assert not (root / "Old").exists()
    assert (root / "Arch/New/Empty").is_dir()
    for note, path in zip(
        notes, ["Arch/New/b.md", "Arch/New/a.md", "Arch/New/S/c.md"], strict=True
    ):
        got = await api.client.get(f"/api/v1/notes/{note['id']}", headers=headers)
        assert got.json()["path"] == path
        assert (root / path).is_file()


async def test_move_refuses_taken_target_and_moving_into_itself(api, owner):
    vault, headers = owner
    await _note(api, headers, vault, "A/x.md")
    await _note(api, headers, vault, "B/y.md")
    for new_path, status in [("b", 409), ("A/inner", 422), ("C", 200)]:
        body = {"vault_id": str(vault), "path": "A", "new_path": new_path}
        response = await api.client.patch("/api/v1/folders", json=body, headers=headers)
        assert response.status_code == status, new_path
    missing = {"vault_id": str(vault), "path": "Nope", "new_path": "Z"}
    assert (
        await api.client.patch("/api/v1/folders", json=missing, headers=headers)
    ).status_code == (404)


async def test_case_only_rename(api, owner):
    vault, headers = owner
    await _note(api, headers, vault, "notes/x.md")
    body = {"vault_id": str(vault), "path": "notes", "new_path": "Notes"}
    response = await api.client.patch("/api/v1/folders", json=body, headers=headers)
    assert response.status_code == 200
    assert (_root(api, vault) / "Notes/x.md").is_file()


async def test_delete_folder(api, owner):
    vault, headers = owner
    root = _root(api, vault)
    (root / "Empty").mkdir()
    full = [await _note(api, headers, vault, p) for p in ["Full/a.md", "Full/Sub/b.md"]]
    url = f"/api/v1/folders?vault_id={vault}"
    assert (await api.client.delete(f"{url}&path=Empty", headers=headers)).status_code == 204
    assert not (root / "Empty").exists()
    assert (await api.client.delete(f"{url}&path=Empty", headers=headers)).status_code == 404
    refused = await api.client.delete(f"{url}&path=Full", headers=headers)
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/folder-not-empty")
    done = await api.client.delete(f"{url}&path=Full&recursive=true", headers=headers)
    assert done.status_code == 204
    assert not (root / "Full").exists()
    with Session(api.engine) as s:
        assert all(s.get(File, n["id"]).deleted for n in full)
        assert s.scalars(select(AuditEvent.action)).all().count("folder.delete") == 2
    listed = await api.client.get(f"/api/v1/folders?vault_id={vault}", headers=headers)
    assert listed.json()["items"] == []


async def test_viewer_cannot_change_folders(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    await _note(api, await api.bearer(alice), vault, "A/x.md")
    viewer = await api.bearer(bob)
    move = {"vault_id": str(vault), "path": "A", "new_path": "B"}
    assert (await api.client.patch("/api/v1/folders", json=move, headers=viewer)).status_code == 403
    delete = f"/api/v1/folders?vault_id={vault}&path=A&recursive=true"
    assert (await api.client.delete(delete, headers=viewer)).status_code == 403
    listed = await api.client.get(f"/api/v1/folders?vault_id={vault}", headers=viewer)
    assert [f["path"] for f in listed.json()["items"]] == ["A"]
