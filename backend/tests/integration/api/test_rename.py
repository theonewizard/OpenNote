"""Rename with link updates (P6-09) over the v1 API."""

import pytest

import app.api.notes as notes_api
from tests.integration.api.test_notes import _content, _create, _put

pytestmark = pytest.mark.anyio


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _rename(api, headers, note, path, revision=None, **extra):
    return await api.client.post(
        f"/api/v1/notes/{note['id']}/rename",
        json={"path": path, **extra},
        headers=headers | {"If-Match": f'"{revision or note["revision"]}"'},
    )


async def test_rename_rewrites_links_in_other_notes(api, owner):
    vault, headers = owner
    target = await _create(api, headers, vault, "Old.md", "self [[Old]]")
    a = await _create(api, headers, vault, "A.md", "[[Old|alias]] and ![[Old#H]]\r\n")
    b = await _create(api, headers, vault, "Sub/B.md", "[b](../Old.md) [[Other]]")
    c = await _create(api, headers, vault, "C.md", "no links")
    response = await _rename(api, headers, target, "Archive/New.md")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["note"]["path"] == "Archive/New.md"
    assert response.headers["etag"] == f'"{body["note"]["revision"]}"'
    assert sorted(
        (u["note"]["path"], u["previous_revision"], u["revision"]) for u in body["updated"]
    ) == [
        ("A.md", 1, 2),
        ("Sub/B.md", 1, 2),
    ]
    assert body["skipped"] == []
    assert (await _content(api, headers, a["id"])).endswith(b"[[New|alias]] and ![[New#H]]\r\n")
    assert (await _content(api, headers, b["id"])).endswith(b"[b](../Archive/New.md) [[Other]]")
    assert (await _content(api, headers, c["id"])).endswith(b"no links")
    links = await api.client.get(f"/api/v1/notes/{target['id']}/links", headers=headers)
    assert sorted(i["path"] for i in links.json()["incoming"]) == ["A.md", "Sub/B.md"]


async def test_rename_without_link_updates(api, owner):
    vault, headers = owner
    target = await _create(api, headers, vault, "Old.md")
    a = await _create(api, headers, vault, "A.md", "[[Old]]")
    response = await _rename(api, headers, target, "New.md", update_links=False)
    assert response.status_code == 200
    assert response.json()["updated"] == []
    assert (await _content(api, headers, a["id"])).endswith(b"[[Old]]")


async def test_a_linking_note_that_changed_is_skipped_not_merged(api, owner, monkeypatch):
    vault, headers = owner
    target = await _create(api, headers, vault, "Old.md")
    a = await _create(api, headers, vault, "A.md", "[[Old]]")
    original_commit = notes_api.commit
    calls = []

    async def commit(request, vault_, op, device, blob, **kw):
        if kw.get("expected_revision") is not None and str(op.file_id) == a["id"]:
            calls.append(op.file_id)
            if len(calls) == 1:  # someone edits A first
                await _put(api, headers, a, b"[[Old]] edited")
        return await original_commit(request, vault_, op, device, blob, **kw)

    monkeypatch.setattr(notes_api, "commit", commit)
    response = await _rename(api, headers, target, "New.md")
    assert response.status_code == 200, response.text
    assert [s["path"] for s in response.json()["skipped"]] == ["A.md"]
    assert (await _content(api, headers, a["id"])).endswith(b"[[Old]] edited")


async def test_rename_preconditions(api, owner):
    vault, headers = owner
    target = await _create(api, headers, vault, "Old.md")
    await _create(api, headers, vault, "Taken.md")
    missing = await api.client.post(
        f"/api/v1/notes/{target['id']}/rename", json={"path": "N.md"}, headers=headers
    )
    assert missing.status_code == 428
    assert (await _rename(api, headers, target, "N.md", revision=9)).status_code == 412
    assert (await _rename(api, headers, target, "taken.md")).status_code == 409
    assert (await _rename(api, headers, target, "../x.md")).status_code == 422
    same = await _rename(api, headers, target, "Old.md")
    assert same.status_code == 200 and same.json()["note"]["revision"] == 1
