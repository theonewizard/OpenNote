"""Tasks (P6-01, P6-02), note-from-template (P6-05) and the graph route (P6-08) over the
v1 API."""

import pytest

from tests.integration.api.test_notes import _content, _create, _put

pytestmark = pytest.mark.anyio


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _tasks(api, headers, vault, **params):
    response = await api.client.get(
        "/api/v1/tasks", params={"vault_id": str(vault), **params}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_tasks_are_indexed_and_listed_by_due_date(api, owner):
    vault, headers = owner
    a = await _create(
        api, headers, vault, "A.md", "- [ ] undated\n- [ ] later 📅 2026-12-01 ⏫\n- [x] done\n"
    )
    await _create(api, headers, vault, "B.md", "- [ ] soon 📅 2026-11-20\n  - [ ] sub\n")
    page = await _tasks(api, headers, vault)
    assert [t["text"] for t in page["items"]] == [
        "soon 📅 2026-11-20",
        "later 📅 2026-12-01 ⏫",
        "undated",
        "sub",
    ]
    later = page["items"][1]
    assert later["note"] == {"id": a["id"], "path": "A.md", "title": "A"}
    assert (later["due"], later["priority"], later["ordinal"], later["revision"]) == (
        "2026-12-01",
        "high",
        1,
        1,
    )
    assert page["items"][3]["parent"] == 0
    done = await _tasks(api, headers, vault, status="done")
    assert [t["text"] for t in done["items"]] == ["done"]
    assert len((await _tasks(api, headers, vault, status="any"))["items"]) == 5
    assert len((await _tasks(api, headers, vault, note_id=a["id"]))["items"]) == 2
    due = await _tasks(api, headers, vault, due_before="2026-11-30")
    assert [t["text"] for t in due["items"]] == ["soon 📅 2026-11-20"]


async def test_task_pages(api, owner):
    vault, headers = owner
    await _create(api, headers, vault, "A.md", "".join(f"- [ ] t{i}\n" for i in range(5)))
    await _create(api, headers, vault, "B.md", "- [ ] b 📅 2026-01-01\n")
    seen, cursor = [], None
    while True:
        params = {"limit": "2"} | ({"cursor": cursor} if cursor else {})
        page = await _tasks(api, headers, vault, **params)
        seen += [t["text"] for t in page["items"]]
        if not (cursor := page["next_cursor"]):
            break
    assert seen == ["b 📅 2026-01-01", "t0", "t1", "t2", "t3", "t4"]
    bad = await api.client.get(
        "/api/v1/tasks", params={"vault_id": str(vault), "cursor": "eyJ4Ijox"}, headers=headers
    )
    assert bad.status_code == 400


async def test_task_index_follows_edits(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "A.md", "- [ ] one\n")
    response = await _put(api, headers, note, b"- [ ] one\n- [ ] two\n")
    assert response.status_code == 200
    assert [t["text"] for t in (await _tasks(api, headers, vault))["items"]] == ["one", "two"]


async def _toggle(api, headers, note_id, ordinal, revision, **body):
    return await api.client.patch(
        f"/api/v1/notes/{note_id}/tasks/{ordinal}",
        json=body,
        headers=headers | {"If-Match": f'"{revision}"'},
    )


async def test_toggle_changes_one_character(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "A.md", "- [ ] one\r\n- [ ] two\r\n")
    before = await _content(api, headers, note["id"])
    response = await _toggle(api, headers, note["id"], 1, 1, done=True)
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"2"'
    after = await _content(api, headers, note["id"])
    assert after == before.replace(b"- [ ] two", b"- [x] two")
    again = await _toggle(api, headers, note["id"], 1, 2, done=True)  # already done: no write
    assert again.json()["revision"] == 2
    done = await _tasks(api, headers, vault, status="done")
    assert [t["text"] for t in done["items"]] == ["two"]


async def test_toggle_completes_a_recurring_task(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "A.md", "- [ ] water 🔁 every week 📅 2026-11-10\n")
    response = await _toggle(api, headers, note["id"], 0, 1, done=True, today="2026-11-14")
    assert response.status_code == 200, response.text
    body = (await _content(api, headers, note["id"])).decode()
    assert body.endswith(
        "- [ ] water 🔁 every week 📅 2026-11-17\n"
        "- [x] water 🔁 every week 📅 2026-11-10 ✅ 2026-11-14\n"
    )
    [open_task] = (await _tasks(api, headers, vault))["items"]
    assert (open_task["due"], open_task["recurrence"]) == ("2026-11-17", "every week")


async def test_toggle_preconditions(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "A.md", "- [ ] one\n")
    url = f"/api/v1/notes/{note['id']}/tasks/0"
    missing = await api.client.patch(url, json={"done": True}, headers=headers)
    assert missing.status_code == 428
    stale = await _toggle(api, headers, note["id"], 0, 7, done=True)
    assert stale.status_code == 412
    gone = await _toggle(api, headers, note["id"], 3, 1, done=True)
    assert gone.status_code == 404
    loose = await _toggle(api, headers, note["id"], 0, 1, done="yes")
    assert loose.status_code == 422


async def test_tasks_need_access(api, owner):
    vault, headers = owner
    note = await _create(api, headers, vault, "A.md", "- [ ] one\n")
    bob = api.user("bob")
    other = await api.bearer(bob)
    listed = await api.client.get("/api/v1/tasks", params={"vault_id": str(vault)}, headers=other)
    assert listed.status_code == 404
    toggled = await _toggle(api, other, note["id"], 0, 1, done=True)
    assert toggled.status_code == 404


async def test_viewers_cannot_toggle(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    note = await _create(api, await api.bearer(alice), vault, "A.md", "- [ ] one\n")
    response = await _toggle(api, await api.bearer(bob), note["id"], 0, 1, done=True)
    assert response.status_code == 403


async def test_create_from_template(api, owner):
    vault, headers = owner
    template = await _create(
        api,
        headers,
        vault,
        "Templates/Daily.md",
        "---\ntags: [daily]\n---\n# {{title}}\n{{date:dddd, MMMM Do YYYY}} at {{time}} {{other}}\n",
    )
    response = await api.client.post(
        "/api/v1/notes",
        json={
            "vault_id": str(vault),
            "path": "Journal/2026-11-14.md",
            "template_id": template["id"],
            "local_time": "2026-11-14T08:05:00+01:00",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    note = response.json()
    assert (
        await _content(api, headers, note["id"])
        == (
            f"---\ntags: [daily]\nid: {note['id']}\n---\n# 2026-11-14\n"
            "Saturday, November 14th 2026 at 08:05 {{other}}\n"
        ).encode()
    )


async def test_a_templates_id_is_replaced(api, owner):
    vault, headers = owner
    template = await _create(api, headers, vault, "T.md", "body")  # gets its own id
    response = await api.client.post(
        "/api/v1/notes",
        json={"vault_id": str(vault), "path": "N.md", "template_id": template["id"]},
        headers=headers,
    )
    note = response.json()
    assert await _content(api, headers, note["id"]) == f"---\nid: {note['id']}\n---\nbody".encode()


async def test_template_refusals(api, owner):
    vault, headers = owner
    template = await _create(api, headers, vault, "T.md", "x")
    bob = api.user("bob")
    bobs = await api.bearer(bob)
    elsewhere = await _create(api, bobs, api.vault(bob, name="Other"), "T.md", "secret")
    cases = [
        {"template_id": template["id"], "content": "x"},
        {"template_id": "0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"},
        {"template_id": elsewhere["id"]},  # another vault's note: not a template here
        {"template_id": template["id"], "local_time": "2026-11-14T08:05:00"},
    ]
    for extra in cases:
        response = await api.client.post(
            "/api/v1/notes",
            json={"vault_id": str(vault), "path": "N.md"} | extra,
            headers=headers,
        )
        assert response.status_code == 422, extra


async def test_graph_route(api, owner):
    vault, headers = owner
    a = await _create(api, headers, vault, "A.md", "[[B]] [[B]] [[Gone]] ![[pic.png]]")
    b = await _create(api, headers, vault, "B.md", "[[A]]")
    c = await _create(api, headers, vault, "C.md", "alone")
    response = await api.client.get(
        "/api/v1/graph", params={"vault_id": str(vault)}, headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {n["id"] for n in body["nodes"]} == {a["id"], b["id"], c["id"]}
    assert sorted((e["source"], e["target"], e["count"]) for e in body["edges"]) == sorted(
        [(a["id"], b["id"], 2), (b["id"], a["id"], 1)]
    )
    full = await api.client.get(
        "/api/v1/graph",
        params={"vault_id": str(vault), "unresolved": "true", "center": c["id"]},
        headers=headers,
    )
    assert [n["id"] for n in full.json()["nodes"]] == [c["id"]]
    unresolved = await api.client.get(
        "/api/v1/graph", params={"vault_id": str(vault), "unresolved": "true"}, headers=headers
    )
    assert {"unresolved:gone", "unresolved:pic.png"} <= {
        n["id"] for n in unresolved.json()["nodes"]
    }
    other = await api.bearer(api.user("bob"))
    refused = await api.client.get("/api/v1/graph", params={"vault_id": str(vault)}, headers=other)
    assert refused.status_code == 404
