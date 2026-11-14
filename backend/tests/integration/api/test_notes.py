"""Notes over the commit path (P2-04): preconditions, byte identity, metadata edits."""

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.models import IdempotencyKey
from app.core.audit import AuditEvent
from app.notes.models import File
from app.vaults.models import Vault
from tests.compatibility.corpus import case_ids, corpus_cases

pytestmark = pytest.mark.anyio

CASES = corpus_cases()


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


async def _create(api, headers, vault, path, content=None):
    body = {"vault_id": str(vault), "path": path}
    if content is not None:
        body["content"] = content
    response = await api.client.post("/api/v1/notes", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _content(api, headers, note_id) -> bytes:
    response = await api.client.get(f"/api/v1/notes/{note_id}/content", headers=headers)
    assert response.status_code == 200
    return response.content


async def _put(api, headers, note, data: bytes, revision=None):
    return await api.client.put(
        f"/api/v1/notes/{note['id']}/content",
        content=data,
        headers=headers
        | {"If-Match": f'"{revision or note["revision"]}"', "Content-Type": "text/markdown"},
    )


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def test_create_without_content_gets_an_id(api, owner):
    vault, headers = owner
    response = await api.client.post(
        "/api/v1/notes", json={"vault_id": str(vault), "path": "Inbox/New.md"}, headers=headers
    )
    assert response.status_code == 201
    note = response.json()
    assert response.headers["etag"] == '"1"'
    assert response.headers["location"] == f"/api/v1/notes/{note['id']}"
    expected = f"---\nid: {note['id']}\n---\n".encode()
    assert await _content(api, headers, note["id"]) == expected
    assert (_root(api, vault) / "Inbox/New.md").read_bytes() == expected
    assert note["has_id_in_file"] is True
    assert note["title"] == "New"
    assert note["revision"] == 1
    assert note["created_at"] == note["modified_at"]
    assert note["modified_by_device"] != "unknown"


async def test_create_adds_an_id_and_keeps_every_other_byte(api, owner):
    vault, headers = owner
    plain = await _create(api, headers, vault, "a.md", "# Title\r\nbody\r\n")
    assert await _content(api, headers, plain["id"]) == (
        f"---\r\nid: {plain['id']}\r\n---\r\n# Title\r\nbody\r\n".encode()
    )
    fm = await _create(api, headers, vault, "b.md", "---\ntitle: B  # kept\ntags: [x]\n---\nhi")
    assert await _content(api, headers, fm["id"]) == (
        f"---\ntitle: B  # kept\ntags: [x]\nid: {fm['id']}\n---\nhi".encode()
    )
    assert fm["title"] == "B"
    assert fm["tags"] == ["x"]
    own = "---\nid: my-own\n---\nx"
    kept = await _create(api, headers, vault, "c.md", own)
    assert await _content(api, headers, kept["id"]) == own.encode()
    broken = "---\n: [\n---\nx"
    invalid = await _create(api, headers, vault, "d.md", broken)
    assert await _content(api, headers, invalid["id"]) == broken.encode()
    assert invalid["frontmatter_error"] is True


async def test_create_rejects_bad_and_taken_paths(api, owner):
    vault, headers = owner
    await _create(api, headers, vault, "Taken.md")
    for path, status in [
        ("x.txt", 422),
        ("a#b.md", 422),
        ("../x.md", 422),
        (".hidden/x.md", 422),
        ("/abs.md", 422),
        ("taken.MD", 409),
    ]:
        response = await api.client.post(
            "/api/v1/notes", json={"vault_id": str(vault), "path": path}, headers=headers
        )
        assert response.status_code == status, path


async def test_idempotent_create_replays(api, owner):
    vault, headers = owner
    keyed = headers | {"Idempotency-Key": str(uuid.uuid4())}
    body = {"vault_id": str(vault), "path": "Once.md"}
    first = await api.client.post("/api/v1/notes", json=body, headers=keyed)
    second = await api.client.post("/api/v1/notes", json=body, headers=keyed)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert second.headers["location"] == first.headers["location"]
    other = await api.client.post("/api/v1/notes", json=body | {"path": "Twice.md"}, headers=keyed)
    assert other.status_code == 422
    listed = await api.client.get(f"/api/v1/notes?vault_id={vault}", headers=headers)
    assert [n["path"] for n in listed.json()["items"]] == ["Once.md"]
    # The response was lost before it was stored: the retry still commits nothing twice.
    with Session(api.engine) as s, s.begin():
        s.execute(delete(IdempotencyKey))
    retry = await api.client.post("/api/v1/notes", json=body, headers=keyed)
    assert retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]


async def test_authorization_matrix(api):
    alice, bob, carol = api.user("alice"), api.user("bob"), api.user("carol")
    vault = api.vault(alice, bob="viewer")
    other = api.vault(carol, "Other")
    note = await _create(api, await api.bearer(alice), vault, "n.md")
    url = f"/api/v1/notes/{note['id']}"
    write = {"If-Match": '"1"'}

    async def statuses(headers):
        return [
            (await api.client.get(f"/api/v1/notes?vault_id={vault}", headers=headers)).status_code,
            (await api.client.get(url, headers=headers)).status_code,
            (await api.client.get(f"{url}/content", headers=headers)).status_code,
            (await api.client.get(f"{url}/links", headers=headers)).status_code,
            (
                await api.client.post(
                    "/api/v1/notes", json={"vault_id": str(vault), "path": "x.md"}, headers=headers
                )
            ).status_code,
            (
                await api.client.put(f"{url}/content", content=b"x", headers=headers | write)
            ).status_code,
            (
                await api.client.patch(url, json={"tags": ["t"]}, headers=headers | write)
            ).status_code,
            (await api.client.delete(url, headers=headers | write)).status_code,
        ]

    assert await statuses(await api.bearer(bob)) == [200, 200, 200, 200, 403, 403, 403, 403]
    assert await statuses(await api.bearer(carol)) == [404] * 8
    assert await statuses(await api.cookie(bob)) == [200, 200, 200, 200, 403, 403, 403, 403]
    assert await statuses(api.api_key(alice, [vault], "read")) == [200] * 4 + [403] * 4
    assert await statuses(api.api_key(alice, [other], "write")) == [404] * 8
    assert await statuses({}) == [401] * 8


async def test_write_token_can_edit(api):
    alice = api.user("alice")
    vault = api.vault(alice)
    note = await _create(api, await api.bearer(alice), vault, "n.md")
    key = api.api_key(alice, [vault], "write")
    response = await _put(api, key, note, b"by token")
    assert response.status_code == 200
    assert response.json()["modified_by_device"].startswith("pat:")


async def test_stale_and_missing_if_match(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "n.md")
    url = f"/api/v1/notes/{note['id']}/content"
    missing = await api.client.put(url, content=b"x", headers=headers)
    assert missing.status_code == 428
    assert (await _put(api, headers, note, b"v2")).status_code == 200
    stale = await _put(api, headers, note, b"v3", revision=1)
    assert stale.status_code == 412
    assert stale.json()["current"]["revision"] == 2
    assert stale.headers["etag"] == '"2"'
    assert await _content(api, headers, note["id"]) == b"v2"
    for call in (
        api.client.patch(f"/api/v1/notes/{note['id']}", json={"path": "m.md"}, headers=headers),
        api.client.delete(f"/api/v1/notes/{note['id']}", headers=headers),
    ):
        assert (await call).status_code == 428
    gone = await api.client.delete(
        f"/api/v1/notes/{note['id']}", headers=headers | {"If-Match": '"1"'}
    )
    assert gone.status_code == 412
    assert gone.json()["current"]["revision"] == 2


@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
async def test_put_get_byte_identity(api, owner, case):
    vault, headers = owner
    note = await _create(api, headers, vault, f"{case.name}.md")
    data = case.note_bytes()
    response = await _put(api, headers, note, data)
    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    got = await api.client.get(f"/api/v1/notes/{note['id']}/content", headers=headers)
    assert got.content == data
    assert got.headers["content-type"] == "text/markdown; charset=utf-8"
    assert got.headers["etag"] == '"2"'
    assert (_root(api, vault) / f"{case.name}.md").read_bytes() == data
    meta = response.json()
    assert meta["size"] == len(data)
    assert meta["read_only"] is (case.name == "enc-windows-1252")
    assert meta["has_id_in_file"] is ("id" in (case.expected.get("frontmatter") or {}))


async def test_put_over_16_mib_is_413(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "big.md")
    response = await _put(api, headers, note, b"x" * (16 * 1024 * 1024 + 1))
    assert response.status_code == 413


async def test_concurrent_puts_one_wins(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "race.md")
    first, second = await asyncio.gather(
        _put(api, headers, note, b"first\n"), _put(api, headers, note, b"second\n")
    )
    assert sorted([first.status_code, second.status_code]) == [200, 412]
    winner = first if first.status_code == 200 else second
    data = b"first\n" if winner is first else b"second\n"
    assert await _content(api, headers, note["id"]) == data
    assert (_root(api, vault) / "race.md").read_bytes() == data
    assert winner.json()["revision"] == 2
    with Session(api.engine) as s:  # no conflict copy was made
        assert s.scalar(select(File.path).where(File.path != "race.md")) is None


async def test_metadata_edit_keeps_every_other_byte(api, owner):
    vault, headers = owner
    original = (
        "---\r\n"
        "# a comment\r\n"
        "title:   'Spaced'   # trailing\r\n"
        "tags: [a, b]\r\n"
        "opennote:\r\n"
        "  favorite: true\r\n"
        "  status: draft\r\n"
        "cssclasses: wide\r\n"
        "---\r\n"
        "Body  with  spaces\r\n"
    )
    note = await _create(api, headers, vault, "meta.md", original)
    url = f"/api/v1/notes/{note['id']}"
    edit = {"tags": ["a", "c"], "aliases": ["Alias"], "opennote": {"favorite": False}}
    response = await api.client.patch(url, json=edit, headers=headers | {"If-Match": '"1"'})
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"2"'
    after = (await _content(api, headers, note["id"])).decode()
    assert after == (
        "---\r\n"
        "# a comment\r\n"
        "title:   'Spaced'   # trailing\r\n"
        "tags: [a, c]\r\n"
        "opennote:\r\n"
        "  favorite: false\r\n"
        "cssclasses: wide\r\n"
        f"id: {note['id']}\r\n"
        "aliases:\r\n"
        "- Alias\r\n"
        "---\r\n"
        "Body  with  spaces\r\n"
    )
    meta = response.json()
    assert meta["tags"] == ["a", "c"]
    assert meta["aliases"] == ["Alias"]
    assert meta["properties"]["opennote"] == {"favorite": False}


async def test_metadata_edit_refused_for_read_only_and_invalid_frontmatter(api, owner):
    vault, headers = owner
    cp1252 = next(c for c in CASES if c.name == "enc-windows-1252").note_bytes()
    note = await _create(api, headers, vault, "cp.md")
    assert (await _put(api, headers, note, cp1252)).status_code == 200
    response = await api.client.patch(
        f"/api/v1/notes/{note['id']}", json={"tags": ["x"]}, headers=headers | {"If-Match": '"2"'}
    )
    assert response.status_code == 409
    broken = await _create(api, headers, vault, "broken.md", "---\n: [\n---\nx")
    response = await api.client.patch(
        f"/api/v1/notes/{broken['id']}", json={"tags": ["x"]}, headers=headers | {"If-Match": '"1"'}
    )
    assert response.status_code == 409
    both = await api.client.patch(
        f"/api/v1/notes/{broken['id']}",
        json={"tags": ["x"], "path": "y.md"},
        headers=headers | {"If-Match": '"1"'},
    )
    assert both.status_code == 422


async def test_move(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "a.md", "keep")
    await _create(api, headers, vault, "Taken.md")
    url = f"/api/v1/notes/{note['id']}"
    taken = await api.client.patch(
        url, json={"path": "taken.md"}, headers=headers | {"If-Match": '"1"'}
    )
    assert taken.status_code == 409
    bad = await api.client.patch(url, json={"path": "x.png"}, headers=headers | {"If-Match": '"1"'})
    assert bad.status_code == 422
    moved = await api.client.patch(
        url, json={"path": "Sub/b.md"}, headers=headers | {"If-Match": '"1"'}
    )
    assert moved.status_code == 200
    assert moved.json()["path"] == "Sub/b.md"
    assert moved.json()["revision"] == 2
    root = _root(api, vault)
    assert not (root / "a.md").exists()
    assert (root / "Sub/b.md").read_bytes() == (await _content(api, headers, note["id"]))


async def test_delete(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "gone.md")
    url = f"/api/v1/notes/{note['id']}"
    assert (await api.client.delete(url, headers=headers | {"If-Match": '"1"'})).status_code == 204
    assert (await api.client.get(url, headers=headers)).status_code == 404
    assert not (_root(api, vault) / "gone.md").exists()
    with Session(api.engine) as s:
        assert s.get(File, uuid.UUID(note["id"])).deleted
        assert "note.delete" in s.scalars(select(AuditEvent.action)).all()
    again = await _create(api, headers, vault, "gone.md")  # the path is free again
    assert again["id"] != note["id"]


async def test_list_filters_sort_and_pages(api, owner):
    vault, headers = owner
    paths = [f"Notes/n{i}.md" for i in range(7)]
    for i, path in enumerate(paths):
        tags = ["Project/Alpha"] if i % 2 else ["other"]
        await _create(api, headers, vault, path, f"---\ntags: {tags}\n---\n")
    await _create(api, headers, vault, "Notes/Deep/x.md")
    await _create(api, headers, vault, "root.md")

    async def collect(query, limit=3):
        items, cursor = [], None
        while True:
            url = f"/api/v1/notes?vault_id={vault}&limit={limit}{query}"
            response = await api.client.get(
                url + (f"&cursor={cursor}" if cursor else ""), headers=headers
            )
            assert response.status_code == 200, response.text
            items += response.json()["items"]
            if not (cursor := response.json()["next_cursor"]):
                return [n["path"] for n in items]

    assert await collect("&folder=Notes") == paths
    assert await collect("&folder=notes/") == paths  # case-insensitive, trailing slash
    assert await collect("&folder=") == ["root.md"]
    assert await collect("&tag=project") == [p for i, p in enumerate(paths) if i % 2]
    assert await collect("&tag=%23PROJECT/alpha") == [p for i, p in enumerate(paths) if i % 2]
    assert await collect("&tag=proj") == []
    everything = await collect("")
    assert everything == sorted(everything) and len(everything) == 9
    assert await collect("&sort=-path", limit=2) == sorted(everything, reverse=True)
    newest = await collect("&sort=-modified_at", limit=4)
    assert newest == list(reversed(await collect("&sort=created_at", limit=4)))
    assert newest[0] == "root.md"
    titles = await collect("&sort=title&folder=Notes")
    assert titles == paths
    bad = await api.client.get(f"/api/v1/notes?vault_id={vault}&cursor=xx", headers=headers)
    assert bad.status_code == 400


async def test_links(api, owner):
    vault, headers = owner
    a = await _create(api, headers, vault, "A.md", "[[B]] and [[Missing|m]] and ![[B#Head]]")
    b = await _create(api, headers, vault, "B.md", "---\ntitle: Bee\n---\nback to [[A]]")
    links = await api.client.get(f"/api/v1/notes/{a['id']}/links", headers=headers)
    assert links.status_code == 200
    body = links.json()
    assert [(o["target"], o["resolved"] and o["resolved"]["id"]) for o in body["outgoing"]] == [
        ("B", b["id"]),
        ("Missing", None),
        ("B", b["id"]),
    ]
    assert body["outgoing"][0]["resolved"]["title"] == "Bee"
    assert body["outgoing"][1]["alias"] == "m"
    assert body["outgoing"][2]["embed"] is True
    assert body["outgoing"][2]["heading"] == "Head"
    assert body["unresolved"] == ["Missing"]
    assert body["incoming"] == [{"id": b["id"], "path": "B.md", "title": "Bee"}]
