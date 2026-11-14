"""Version history, restore and deleted-note recovery (P5-06)."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import AuditEvent
from app.sync.models import Revision
from app.vaults.models import Vault

pytestmark = pytest.mark.anyio


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _note(api, headers, vault, path="H.md", content="v1\n"):
    response = await api.client.post(
        "/api/v1/notes",
        json={"vault_id": str(vault), "path": path, "content": content},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def _put(api, headers, note_id, revision, data: bytes):
    response = await api.client.put(
        f"/api/v1/notes/{note_id}/content",
        content=data,
        headers=headers | {"If-Match": f'"{revision}"', "Content-Type": "text/markdown"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_revisions_list_newest_first_with_content(api, owner):
    vault, headers = owner
    note = await _note(api, headers, vault)
    v1 = (await api.client.get(f"/api/v1/notes/{note['id']}/content", headers=headers)).content
    await _put(api, headers, note["id"], 1, b"v2\n")
    await _put(api, headers, note["id"], 2, b"v3\n")

    page = (await api.client.get(f"/api/v1/notes/{note['id']}/revisions", headers=headers)).json()
    assert [r["revision"] for r in page["items"]] == [3, 2, 1]
    assert [r["op"] for r in page["items"]] == ["update", "update", "create"]
    assert page["next_cursor"] is None

    first = await api.client.get(f"/api/v1/notes/{note['id']}/revisions?limit=2", headers=headers)
    rest = await api.client.get(
        f"/api/v1/notes/{note['id']}/revisions",
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
        headers=headers,
    )
    assert [r["revision"] for r in rest.json()["items"]] == [1]

    one = await api.client.get(f"/api/v1/notes/{note['id']}/revisions/1", headers=headers)
    assert one.json()["path"] == "H.md"
    content = await api.client.get(
        f"/api/v1/notes/{note['id']}/revisions/1/content", headers=headers
    )
    assert content.content == v1
    missing = await api.client.get(f"/api/v1/notes/{note['id']}/revisions/9", headers=headers)
    assert missing.status_code == 404


async def test_restore_brings_old_bytes_back_as_a_new_revision(api, owner):
    vault, headers = owner
    note = await _note(api, headers, vault)
    old = (await api.client.get(f"/api/v1/notes/{note['id']}/content", headers=headers)).content
    await _put(api, headers, note["id"], 1, b"changed\n")
    url = f"/api/v1/notes/{note['id']}/restore"
    body = {"from_revision": 1}
    assert (await api.client.post(url, json=body, headers=headers)).status_code == 428
    stale = await api.client.post(url, json=body, headers=headers | {"If-Match": '"1"'})
    assert stale.status_code == 412
    restored = await api.client.post(url, json=body, headers=headers | {"If-Match": '"2"'})
    assert restored.status_code == 200
    assert restored.json()["revision"] == 3
    assert restored.headers["etag"] == '"3"'
    assert (_root(api, vault) / "H.md").read_bytes() == old
    with Session(api.engine) as s:
        ops = s.scalars(select(Revision.op).order_by(Revision.seq)).all()
        assert ops == ["create", "update", "restore"]
        assert s.scalar(select(AuditEvent.action).where(AuditEvent.action == "note.restore"))


async def test_deleted_notes_are_listed_and_recoverable(api, owner):
    vault, headers = owner
    keep = await _note(api, headers, vault, "Keep.md")
    gone = await _note(api, headers, vault, "Gone.md", "precious\n")
    await _put(api, headers, gone["id"], 1, b"precious v2\n")
    response = await api.client.delete(
        f"/api/v1/notes/{gone['id']}", headers=headers | {"If-Match": '"2"'}
    )
    assert response.status_code == 204
    assert (await api.client.get(f"/api/v1/notes/{gone['id']}", headers=headers)).status_code == 404

    listed = await api.client.get(f"/api/v1/vaults/{vault}/deleted-notes", headers=headers)
    assert listed.status_code == 200
    [item] = listed.json()["items"]
    assert item["id"] == gone["id"]
    assert item["path"] == "Gone.md"
    assert item["revision"] == 3
    assert item["last_content_revision"] == 2
    assert keep["id"] not in listed.text

    revisions = await api.client.get(f"/api/v1/notes/{gone['id']}/revisions", headers=headers)
    assert revisions.json()["items"][0]["deleted"] is True
    tombstone = await api.client.get(
        f"/api/v1/notes/{gone['id']}/revisions/3/content", headers=headers
    )
    assert tombstone.status_code == 404

    restored = await api.client.post(
        f"/api/v1/notes/{gone['id']}/restore",
        json={"from_revision": 2},
        headers=headers | {"If-Match": '"3"'},
    )
    assert restored.status_code == 200, restored.text
    assert (_root(api, vault) / "Gone.md").read_bytes() == b"precious v2\n"
    after = await api.client.get(f"/api/v1/vaults/{vault}/deleted-notes", headers=headers)
    assert after.json()["items"] == []


async def test_restore_of_a_tombstone_or_a_taken_path_is_refused(api, owner):
    vault, headers = owner
    gone = await _note(api, headers, vault, "Same.md")
    await api.client.delete(f"/api/v1/notes/{gone['id']}", headers=headers | {"If-Match": '"1"'})
    url = f"/api/v1/notes/{gone['id']}/restore"
    tomb = await api.client.post(
        url, json={"from_revision": 2}, headers=headers | {"If-Match": '"2"'}
    )
    assert tomb.status_code == 422
    await _note(api, headers, vault, "Same.md")
    taken = await api.client.post(
        url, json={"from_revision": 1}, headers=headers | {"If-Match": '"2"'}
    )
    assert taken.status_code == 409
    assert taken.json()["type"].endswith("/path-taken")


async def test_history_follows_vault_roles(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    alice_h, bob_h = await api.bearer(alice), await api.bearer(bob)
    note = await _note(api, alice_h, vault)
    assert (
        await api.client.get(f"/api/v1/notes/{note['id']}/revisions", headers=bob_h)
    ).status_code == 200
    refused = await api.client.post(
        f"/api/v1/notes/{note['id']}/restore",
        json={"from_revision": 1},
        headers=bob_h | {"If-Match": '"1"'},
    )
    assert refused.status_code == 403
    carol = await api.bearer(api.user("carol"))
    hidden = await api.client.get(f"/api/v1/notes/{note['id']}/revisions", headers=carol)
    assert hidden.status_code == 404
    deleted = await api.client.get(f"/api/v1/vaults/{vault}/deleted-notes", headers=carol)
    assert deleted.status_code == 404
