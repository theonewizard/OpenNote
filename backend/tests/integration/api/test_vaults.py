"""Vaults and vault membership (P2-03)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.vaults.models import Vault

pytestmark = pytest.mark.anyio


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


def _vault_root(api) -> Path:
    return Path(api.settings.vault_root).resolve()


def _actions(api) -> list[str]:
    with Session(api.engine) as s:
        return list(s.scalars(select(AuditEvent.action).order_by(AuditEvent.at)))


async def test_admin_creates_an_empty_vault_and_owns_it(api):
    admin = api.user("root", admin=True)
    headers = await api.bearer(admin)
    response = await api.client.post("/api/v1/vaults", json={"name": "My Work"}, headers=headers)
    assert response.status_code == 201
    vault = response.json()
    assert vault["role"] == "owner"
    assert vault["revision"] == 1
    assert vault["settings"] == {"sync_obsidian_config": False, "ai_enabled": False}
    assert response.headers["etag"] == '"1"'
    assert response.headers["location"] == f"/api/v1/vaults/{vault['id']}"
    root = _root(api, vault["id"])
    assert root.parent == _vault_root(api)
    assert root.name.startswith("my-work-")
    assert list(root.iterdir()) == []  # nothing written into the vault
    assert "vault.create" in _actions(api)
    listed = await api.client.get("/api/v1/vaults", headers=headers)
    assert [v["id"] for v in listed.json()["items"]] == [vault["id"]]


async def test_only_admins_create_vaults(api):
    alice = api.user("alice")
    response = await api.client.post(
        "/api/v1/vaults", json={"name": "x"}, headers=await api.bearer(alice)
    )
    assert response.status_code == 403


async def test_registering_an_existing_directory_writes_nothing_into_it(api):
    admin = api.user("root", admin=True)
    folder = Path(api.settings.vault_root) / "Existing"
    (folder / ".obsidian").mkdir(parents=True)
    (folder / "Note.md").write_bytes(b"# hi\r\n")
    before = sorted(p.relative_to(folder) for p in folder.rglob("*"))
    headers = await api.bearer(admin)
    response = await api.client.post(
        "/api/v1/vaults", json={"name": "Existing", "directory": "Existing"}, headers=headers
    )
    assert response.status_code == 201
    assert _root(api, response.json()["id"]) == folder.resolve()
    assert sorted(p.relative_to(folder) for p in folder.rglob("*")) == before
    again = await api.client.post(
        "/api/v1/vaults", json={"name": "Again", "directory": "Existing"}, headers=headers
    )
    assert again.status_code == 409


async def test_directory_must_stay_inside_the_vault_root(api, tmp_path):
    admin = api.user("root", admin=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, Path(api.settings.vault_root) / "link")
    (Path(api.settings.vault_root) / "file").write_text("x")
    headers = await api.bearer(admin)
    for directory in ["../outside", "/etc", "link", "missing", "file", "a/../..", "."]:
        response = await api.client.post(
            "/api/v1/vaults", json={"name": "x", "directory": directory}, headers=headers
        )
        assert response.status_code == 422, directory
        assert response.json()["type"].endswith("/invalid-directory")


async def test_idempotent_vault_create(api):
    admin = api.user("root", admin=True)
    headers = await api.bearer(admin) | {"Idempotency-Key": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"}
    first = await api.client.post("/api/v1/vaults", json={"name": "A"}, headers=headers)
    second = await api.client.post("/api/v1/vaults", json={"name": "A"}, headers=headers)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert second.headers["etag"] == '"1"'
    other = await api.client.post("/api/v1/vaults", json={"name": "B"}, headers=headers)
    assert other.status_code == 422


async def test_list_get_and_access_matrix(api):
    alice, bob, carol = api.user("alice"), api.user("bob"), api.user("carol")
    vaults = [api.vault(alice, f"V{i}", bob="viewer") for i in range(3)]
    other = api.vault(carol, "Carol")
    bob_headers = await api.bearer(bob)
    page = await api.client.get("/api/v1/vaults?limit=2", headers=bob_headers)
    assert page.status_code == 200
    first = page.json()
    assert len(first["items"]) == 2
    rest = await api.client.get(
        f"/api/v1/vaults?limit=2&cursor={first['next_cursor']}", headers=bob_headers
    )
    assert rest.json()["next_cursor"] is None
    ids = [v["id"] for v in first["items"] + rest.json()["items"]]
    assert ids == sorted(str(v) for v in vaults)
    assert {v["role"] for v in first["items"]} == {"viewer"}

    got = await api.client.get(f"/api/v1/vaults/{vaults[0]}", headers=bob_headers)
    assert got.status_code == 200
    assert got.headers["etag"] == '"1"'
    assert (await api.client.get(f"/api/v1/vaults/{other}", headers=bob_headers)).status_code == (
        404
    )
    # A token reaches only its vaults, with its scope as the role cap.
    key = api.api_key(alice, [vaults[1]], "write")
    listed = await api.client.get("/api/v1/vaults", headers=key)
    assert [(v["id"], v["role"]) for v in listed.json()["items"]] == [(str(vaults[1]), "editor")]
    assert (await api.client.get(f"/api/v1/vaults/{vaults[0]}", headers=key)).status_code == 404


async def test_patch_needs_owner_and_if_match(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="editor")
    owner = await api.bearer(alice)
    url = f"/api/v1/vaults/{vault}"
    body = {"name": "Renamed", "settings": {"ai_enabled": True}}
    assert (await api.client.patch(url, json=body, headers=owner)).status_code == 428
    stale = await api.client.patch(url, json=body, headers=owner | {"If-Match": '"7"'})
    assert stale.status_code == 412
    assert stale.json()["current"]["revision"] == 1
    editor = await api.bearer(bob) | {"If-Match": '"1"'}
    assert (await api.client.patch(url, json=body, headers=editor)).status_code == 403
    pat = api.api_key(alice, [vault], "write") | {"If-Match": '"1"'}
    assert (await api.client.patch(url, json=body, headers=pat)).status_code == 401
    done = await api.client.patch(url, json=body, headers=owner | {"If-Match": '"1"'})
    assert done.status_code == 200
    assert done.headers["etag"] == '"2"'
    assert done.json()["name"] == "Renamed"
    assert done.json()["settings"] == {"sync_obsidian_config": False, "ai_enabled": True}
    more = {"settings": {"sync_obsidian_config": True}}
    merged = await api.client.patch(url, json=more, headers=owner | {"If-Match": '"2"'})
    assert merged.json()["settings"] == {"sync_obsidian_config": True, "ai_enabled": True}


async def test_soft_delete(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="editor")
    url = f"/api/v1/vaults/{vault}"
    owner = await api.bearer(alice)
    assert (await api.client.delete(url, headers=await api.bearer(bob))).status_code == 403
    assert (await api.client.delete(url, headers=owner)).status_code == 428
    assert (await api.client.delete(url, headers=owner | {"If-Match": '"1"'})).status_code == 204
    assert (await api.client.get(url, headers=owner)).status_code == 404
    assert (await api.client.get("/api/v1/vaults", headers=owner)).json()["items"] == []
    assert _root(api, vault).is_dir()  # the files stay
    assert "vault.delete" in _actions(api)


async def test_members_and_the_last_owner(api):
    alice, bob, carol = api.user("alice"), api.user("bob"), api.user("carol")
    vault = api.vault(alice, bob="viewer")
    owner = await api.bearer(alice)
    url = f"/api/v1/vaults/{vault}/members"
    listed = await api.client.get(url, headers=owner)
    assert listed.status_code == 200
    assert {(m["username"], m["role"]) for m in listed.json()["items"]} == {
        ("alice", "owner"),
        ("bob", "viewer"),
    }
    assert (await api.client.get(url, headers=await api.bearer(bob))).status_code == 403
    assert (await api.client.get(url, headers=await api.bearer(carol))).status_code == 404

    put = await api.client.put(f"{url}/{carol.id}", json={"role": "editor"}, headers=owner)
    assert put.status_code == 200
    assert put.json()["role"] == "editor"
    carol_headers = await api.bearer(carol)
    seen = await api.client.get(f"/api/v1/vaults/{vault}", headers=carol_headers)
    assert seen.json()["role"] == "editor"

    demote = await api.client.put(f"{url}/{alice.id}", json={"role": "editor"}, headers=owner)
    assert demote.status_code == 409
    assert demote.json()["type"].endswith("/last-owner")
    assert (await api.client.delete(f"{url}/{alice.id}", headers=owner)).status_code == 409
    missing = await api.client.put(
        f"{url}/0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c", json={"role": "viewer"}, headers=owner
    )
    assert missing.status_code == 404

    await api.client.put(f"{url}/{bob.id}", json={"role": "owner"}, headers=owner)
    assert (await api.client.delete(f"{url}/{alice.id}", headers=owner)).status_code == 204
    assert (await api.client.get(f"/api/v1/vaults/{vault}", headers=owner)).status_code == 404
    assert (await api.client.delete(f"{url}/{carol.id}", headers=owner)).status_code == 404
    actions = _actions(api)
    assert actions.count("vault.member_put") == 2
    assert actions.count("vault.member_remove") == 1
