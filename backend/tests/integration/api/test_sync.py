"""Sync endpoints (P5-01): blobs, pull, snapshot, push, conflicts and change hints."""

import asyncio
import contextlib
import hashlib
import json
import socket
import uuid
from pathlib import Path

import httpx2
import pytest
import uvicorn
from sqlalchemy.orm import Session

from app.sync import service
from app.vaults.models import Vault

pytestmark = pytest.mark.anyio


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _put_blob(api, headers, vault, data: bytes):
    return await api.client.put(
        f"/api/v1/blobs/{_hash(data)[7:]}",
        params={"vault_id": str(vault)},
        content=data,
        headers=headers | {"Content-Type": "application/octet-stream"},
    )


async def _push(api, headers, vault, *ops, key=None):
    extra = {"Idempotency-Key": str(key)} if key else {}
    response = await api.client.post(
        f"/api/v1/sync/{vault}/push", json={"operations": list(ops)}, headers=headers | extra
    )
    assert response.status_code == 200, response.text
    return response.json()["results"]


def _create(path: str, data: bytes, file_id=None) -> dict:
    return {
        "op": "create",
        "client_op_id": str(uuid.uuid7()),
        "file_id": str(file_id or uuid.uuid7()),
        "path": path,
        "kind": "note" if path.endswith(".md") else "attachment",
        "content_hash": _hash(data),
    }


def _update(file_id, base: int, data: bytes) -> dict:
    return {
        "op": "update",
        "client_op_id": str(uuid.uuid7()),
        "file_id": str(file_id),
        "base_revision": base,
        "content_hash": _hash(data),
    }


async def _create_file(api, headers, vault, path, data: bytes) -> dict:
    assert (await _put_blob(api, headers, vault, data)).status_code == 204
    [result] = await _push(api, headers, vault, _create(path, data))
    assert result["status"] == "applied", result
    return result


# Blobs ------------------------------------------------------------------------------------


async def test_blob_upload_head_and_download(api, owner):
    vault, headers = owner
    data = b"\x00binary\xff" * 1000
    url, params = f"/api/v1/blobs/{_hash(data)[7:]}", {"vault_id": str(vault)}
    assert (await api.client.head(url, params=params, headers=headers)).status_code == 404
    assert (await _put_blob(api, headers, vault, data)).status_code == 204
    assert (await _put_blob(api, headers, vault, data)).status_code == 204  # no-op
    assert (await api.client.head(url, params=params, headers=headers)).status_code == 200
    got = await api.client.get(url, params=params, headers=headers)
    assert got.status_code == 200
    assert got.content == data
    assert got.headers["content-type"] == "application/octet-stream"


async def test_blob_with_wrong_hash_is_refused_and_not_stored(api, owner):
    vault, headers = owner
    wrong = "0" * 64
    response = await api.client.put(
        f"/api/v1/blobs/{wrong}", params={"vault_id": str(vault)}, content=b"x", headers=headers
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/blob-hash-mismatch")
    objects = Path(api.settings.history_root) / str(vault) / "objects"
    assert not [p for p in objects.rglob("*") if p.is_file()]  # temp file removed too


async def test_blob_over_the_limit_is_413(api, owner, make_settings):
    vault, headers = owner
    api.app.state.settings = make_settings(max_blob_bytes=10)
    response = await _put_blob(api, headers, vault, b"x" * 11)
    assert response.status_code == 413
    assert response.json()["type"].endswith("/blob-too-large")


async def test_blob_routes_follow_vault_roles(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    bob_headers = await api.bearer(bob)
    assert (await _put_blob(api, bob_headers, vault, b"x")).status_code == 403
    carol = await api.bearer(api.user("carol"))
    assert (await _put_blob(api, carol, vault, b"x")).status_code == 404
    response = await api.client.put(
        f"/api/v1/blobs/{_hash(b'x')[7:]}", params={"vault_id": str(vault)}, content=b"x"
    )
    assert response.status_code == 401


async def test_blob_path_must_be_a_lowercase_sha256(api, owner):
    vault, headers = owner
    response = await api.client.head(
        "/api/v1/blobs/ABC", params={"vault_id": str(vault)}, headers=headers
    )
    assert response.status_code == 422


# Push and pull ----------------------------------------------------------------------------


async def test_push_then_pull_returns_the_change_and_writes_the_vault(api, owner):
    vault, headers = owner
    data = b"# Hello\n"
    created = await _create_file(api, headers, vault, "Hello.md", data)
    assert (_root(api, vault) / "Hello.md").read_bytes() == data

    pull = await api.client.get(f"/api/v1/sync/{vault}/changes", headers=headers)
    assert pull.status_code == 200
    page = pull.json()
    assert page["has_more"] is False
    [entry] = page["entries"]
    assert entry["file_id"] == created["file_id"]
    assert entry["revision"] == 1
    assert entry["content_hash"] == _hash(data)
    assert entry["op"] == "create"
    assert entry["seq"] == created["seq"]

    again = await api.client.get(
        f"/api/v1/sync/{vault}/changes",
        params={"cursor": page["next_cursor"]},
        headers=headers,
    )
    assert again.json()["entries"] == []


async def test_pull_pages_with_has_more(api, owner):
    vault, headers = owner
    for i in range(3):
        await _create_file(api, headers, vault, f"N{i}.md", f"{i}\n".encode())
    first = (await api.client.get(f"/api/v1/sync/{vault}/changes?limit=2", headers=headers)).json()
    assert [e["path"] for e in first["entries"]] == ["N0.md", "N1.md"]
    assert first["has_more"] is True
    rest = (
        await api.client.get(
            f"/api/v1/sync/{vault}/changes",
            params={"cursor": first["next_cursor"], "limit": 2},
            headers=headers,
        )
    ).json()
    assert [e["path"] for e in rest["entries"]] == ["N2.md"]
    assert rest["has_more"] is False


async def test_bad_and_foreign_cursors_are_400(api, owner):
    vault, headers = owner
    other = api.vault(None, "Other")
    foreign = service.encode_cursor(other, 0)
    for cursor in ("not-a-cursor", foreign):
        response = await api.client.get(
            f"/api/v1/sync/{vault}/changes", params={"cursor": cursor}, headers=headers
        )
        assert response.status_code == 400
        assert response.json()["type"].endswith("/invalid-cursor")


async def test_expired_cursor_is_410(api, owner, monkeypatch):
    vault, headers = owner
    await _create_file(api, headers, vault, "A.md", b"a\n")
    old = service.encode_cursor(vault, 0)
    await _create_file(api, headers, vault, "B.md", b"b\n")
    await _create_file(api, headers, vault, "C.md", b"c\n")
    monkeypatch.setattr(service, "RETENTION_SEQ_WINDOW", 1)
    response = await api.client.get(
        f"/api/v1/sync/{vault}/changes", params={"cursor": old}, headers=headers
    )
    assert response.status_code == 410
    assert response.json()["type"].endswith("/cursor-expired")


async def test_stale_update_is_merged_on_the_server(api, owner):
    vault, headers = owner
    base = b"one\ntwo\nthree\n"
    created = await _create_file(api, headers, vault, "M.md", base)
    file_id = created["file_id"]
    theirs = b"ONE\ntwo\nthree\n"
    await _put_blob(api, headers, vault, theirs)
    [first] = await _push(api, headers, vault, _update(file_id, 1, theirs))
    assert first["status"] == "applied"
    ours = b"one\ntwo\nTHREE\n"
    await _put_blob(api, headers, vault, ours)
    [merged] = await _push(api, headers, vault, _update(file_id, 1, ours))
    assert merged["status"] == "merged"
    assert merged["revision"] == 3
    assert (_root(api, vault) / "M.md").read_bytes() == b"ONE\ntwo\nTHREE\n"
    download = await api.client.get(
        f"/api/v1/blobs/{merged['content_hash'][7:]}",
        params={"vault_id": str(vault)},
        headers=headers,
    )
    assert download.content == b"ONE\ntwo\nTHREE\n"


async def test_conflict_copy_is_named_after_the_device_and_listed(api, owner):
    vault, headers = owner
    created = await _create_file(api, headers, vault, "C.md", b"line\n")
    a, b = b"alpha\n", b"beta\n"
    await _put_blob(api, headers, vault, a)
    await _put_blob(api, headers, vault, b)
    await _push(api, headers, vault, _update(created["file_id"], 1, a))
    [result] = await _push(api, headers, vault, _update(created["file_id"], 1, b))
    assert result["status"] == "conflict"
    assert result["path"].startswith("C (conflict test device ")
    assert result["problem"]["original_file_id"] == created["file_id"]
    assert (_root(api, vault) / result["path"]).read_bytes() == b

    listed = await api.client.get(
        "/api/v1/conflicts", params={"vault_id": str(vault)}, headers=headers
    )
    [conflict] = listed.json()["items"]
    assert conflict["file_id"] == created["file_id"]
    assert conflict["copy_file_id"] == result["file_id"]
    assert conflict["status"] == "open"
    assert conflict["revision"] == 1

    url = f"/api/v1/conflicts/{conflict['id']}"
    body = {"status": "resolved"}
    assert (await api.client.patch(url, json=body, headers=headers)).status_code == 428
    stale = await api.client.patch(url, json=body, headers=headers | {"If-Match": '"9"'})
    assert stale.status_code == 412
    done = await api.client.patch(url, json=body, headers=headers | {"If-Match": '"1"'})
    assert done.status_code == 200
    assert done.headers["etag"] == '"2"'
    assert done.json()["status"] == "resolved"
    assert done.json()["resolved_at"] is not None
    still_open = await api.client.get(
        "/api/v1/conflicts", params={"vault_id": str(vault)}, headers=headers
    )
    assert still_open.json()["items"] == []
    resolved = await api.client.get(
        "/api/v1/conflicts",
        params={"vault_id": str(vault), "status": "resolved"},
        headers=headers,
    )
    assert [c["id"] for c in resolved.json()["items"]] == [conflict["id"]]


async def test_missing_blob_rejects_only_that_operation(api, owner):
    vault, headers = owner
    data = b"present\n"
    await _put_blob(api, headers, vault, data)
    results = await _push(
        api, headers, vault, _create("Missing.md", b"never uploaded\n"), _create("Ok.md", data)
    )
    assert [r["status"] for r in results] == ["rejected", "applied"]
    assert results[0]["problem"]["type"].endswith("/blob-missing")


async def test_retried_operation_is_a_duplicate_and_batches_replay(api, owner):
    vault, headers = owner
    data = b"x\n"
    await _put_blob(api, headers, vault, data)
    op = _create("D.md", data)
    [first] = await _push(api, headers, vault, op)
    [again] = await _push(api, headers, vault, op)
    assert again["status"] == "duplicate"
    assert {k: v for k, v in again.items() if k != "status"} == {
        k: v for k, v in first.items() if k != "status"
    }

    key = uuid.uuid4()
    op2 = _create("E.md", data)
    batch = await _push(api, headers, vault, op2, key=key)
    replayed = await _push(api, headers, vault, op2, key=key)
    assert replayed == batch  # the stored response, not a `duplicate`
    reused = await api.client.post(
        f"/api/v1/sync/{vault}/push",
        json={"operations": [_create("F.md", data)]},
        headers=headers | {"Idempotency-Key": str(key)},
    )
    assert reused.status_code == 422


async def test_push_validates_operations(api, owner):
    vault, headers = owner
    url = f"/api/v1/sync/{vault}/push"
    too_many = [_create(f"{i}.md", b"x") for i in range(101)]
    for body in (
        {"operations": []},
        {"operations": too_many},
        {"operations": [{"op": "explode", "client_op_id": str(uuid.uuid7())}]},
        {"operations": [_create("A.md", b"x") | {"content_hash": "md5:abc"}]},
    ):
        response = await api.client.post(url, json=body, headers=headers)
        assert response.status_code == 422, body


async def test_invalid_path_is_rejected_not_written(api, owner):
    vault, headers = owner
    data = b"x\n"
    await _put_blob(api, headers, vault, data)
    [result] = await _push(api, headers, vault, _create("../escape.md", data))
    assert result["status"] == "rejected"
    assert result["problem"]["type"].endswith("/invalid-path")


async def test_move_delete_and_restore_over_push(api, owner):
    vault, headers = owner
    created = await _create_file(api, headers, vault, "Old.md", b"body\n")
    fid = created["file_id"]
    [moved] = await _push(
        api,
        headers,
        vault,
        {
            "op": "move",
            "client_op_id": str(uuid.uuid7()),
            "file_id": fid,
            "base_revision": 1,
            "new_path": "New.md",
        },
    )
    assert moved["status"] == "applied"
    assert (_root(api, vault) / "New.md").exists()
    [deleted] = await _push(
        api,
        headers,
        vault,
        {"op": "delete", "client_op_id": str(uuid.uuid7()), "file_id": fid, "base_revision": 2},
    )
    assert deleted["status"] == "applied"
    assert not (_root(api, vault) / "New.md").exists()
    [restored] = await _push(
        api,
        headers,
        vault,
        {"op": "restore", "client_op_id": str(uuid.uuid7()), "file_id": fid, "from_revision": 1},
    )
    assert restored["status"] == "applied"
    assert (_root(api, vault) / "New.md").read_bytes() == b"body\n"


async def test_viewers_and_read_tokens_pull_but_do_not_push(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    bob_headers = await api.bearer(bob)
    token = api.api_key(alice, [vault], scope="read")
    for headers in (bob_headers, token):
        pull = await api.client.get(f"/api/v1/sync/{vault}/changes", headers=headers)
        assert pull.status_code == 200
        push = await api.client.post(
            f"/api/v1/sync/{vault}/push",
            json={"operations": [_create("X.md", b"x")]},
            headers=headers,
        )
        assert push.status_code == 403


async def test_web_session_push_needs_csrf(api):
    alice = api.user("alice")
    vault = api.vault(alice)
    headers = await api.cookie(alice)
    no_csrf = {k: v for k, v in headers.items() if k != "X-CSRF-Token"}
    response = await api.client.post(
        f"/api/v1/sync/{vault}/push",
        json={"operations": [_create("X.md", b"x")]},
        headers=no_csrf,
    )
    assert response.status_code == 403


# Snapshot ---------------------------------------------------------------------------------


async def test_snapshot_pages_by_path_with_one_cursor(api, owner):
    vault, headers = owner
    ids = {}
    for name in ("b.md", "a.md", "c.md"):
        ids[name] = (await _create_file(api, headers, vault, name, name.encode()))["file_id"]
    gone = await _create_file(api, headers, vault, "z.md", b"z")
    await _push(
        api,
        headers,
        vault,
        {
            "op": "delete",
            "client_op_id": str(uuid.uuid7()),
            "file_id": gone["file_id"],
            "base_revision": 1,
        },
    )
    url = f"/api/v1/sync/{vault}/snapshot"
    first = (await api.client.get(url, params={"limit": 2}, headers=headers)).json()
    assert [e["path"] for e in first["entries"]] == ["a.md", "b.md"]
    # A commit while paging: the snapshot's cursor still pulls it afterwards.
    late = await _create_file(api, headers, vault, "aa.md", b"late")
    second = (
        await api.client.get(url, params={"limit": 2, "page": first["next_page"]}, headers=headers)
    ).json()
    assert [e["path"] for e in second["entries"]] == ["c.md"]
    assert second["next_page"] is None
    assert second["cursor"] == first["cursor"]
    pulled = (
        await api.client.get(
            f"/api/v1/sync/{vault}/changes", params={"cursor": first["cursor"]}, headers=headers
        )
    ).json()
    assert [e["file_id"] for e in pulled["entries"]] == [late["file_id"]]


async def test_snapshot_rejects_a_bad_page_token(api, owner):
    vault, headers = owner
    response = await api.client.get(
        f"/api/v1/sync/{vault}/snapshot", params={"page": "garbage"}, headers=headers
    )
    assert response.status_code == 400


# Change hints -----------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _read_event(lines, name: str) -> dict:
    event = None
    async for line in lines:
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: ") and event == name:
            return json.loads(line.removeprefix("data: "))
    raise AssertionError(f"stream ended before a {name} event")


async def test_events_stream_change_hints_over_a_real_server(api, owner):
    vault, headers = owner
    other_vault = api.vault(api.user("bob"), "Bobs")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api.app, port=port, lifespan="off", log_level="error"))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:  # noqa: ASYNC110 - uvicorn offers a flag, no event
            await asyncio.sleep(0.05)
        async with (
            httpx2.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as http,
            http.stream("GET", "/api/v1/events", headers=headers) as stream,
        ):
            assert stream.status_code == 200
            assert stream.headers["content-type"].startswith("text/event-stream")
            assert stream.headers["x-accel-buffering"] == "no"
            lines = stream.aiter_lines()
            ready = await asyncio.wait_for(_read_event(lines, "ready"), 5)
            assert ready == {"vaults": [str(vault)]}
            created = await _create_file(api, headers, vault, "Hint.md", b"hint\n")
            change = await asyncio.wait_for(_read_event(lines, "change"), 5)
            assert change == {"vault_id": str(vault), "seq": created["seq"]}
            assert str(other_vault) not in json.dumps(change)
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_events_need_credentials(api):
    response = await api.client.get("/api/v1/events")
    assert response.status_code == 401
