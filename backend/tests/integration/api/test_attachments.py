"""Attachments (Phase 2 Task 6): upload checks, type sniffing, Range downloads, delete,
listing and idempotent replay."""

import hashlib
import struct
import uuid
import zlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.main import create_app
from app.core.audit import AuditEvent
from app.core.config import Settings
from app.sync.commit import Create
from tests.integration.api.conftest import Api
from tests.integration.conftest import serve

pytestmark = pytest.mark.anyio


def png() -> bytes:
    """A real 1x1 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def vault_files(api: Api, pattern: str) -> list[Path]:
    return list(Path(api.settings.vault_root).glob(pattern))


async def upload(
    api: Api,
    headers: dict[str, str],
    vault_id: uuid.UUID,
    path: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    **extra: str,
):
    return await api.client.post(
        "/api/v1/attachments",
        headers=headers | extra,
        data={"vault_id": str(vault_id), "path": path},
        files={"file": (path.rsplit("/", 1)[-1], data, content_type)},
    )


async def owner_vault(api: Api):
    alice = api.user("alice")
    vault_id = api.vault(alice)
    return alice, vault_id, await api.bearer(alice)


# Upload ------------------------------------------------------------------------------------


async def test_upload_creates_the_file(api):
    _, vault_id, headers = await owner_vault(api)
    data = png()
    response = await upload(api, headers, vault_id, "Assets/dot.png", data, "image/png")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["path"] == "Assets/dot.png"
    assert body["vault_id"] == str(vault_id)
    assert body["revision"] == 1
    assert body["size"] == len(data)
    assert body["content_hash"] == "sha256:" + hashlib.sha256(data).hexdigest()
    assert body["media_type"] == "image/png"
    assert response.headers["etag"] == '"1"'
    assert response.headers["location"] == f"/api/v1/attachments/{body['id']}"
    (on_disk,) = vault_files(api, "*/Assets/dot.png")
    assert on_disk.read_bytes() == data

    fetched = await api.client.get(f"/api/v1/attachments/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json() == body
    assert fetched.headers["etag"] == '"1"'


@pytest.mark.parametrize(
    "path",
    ["../escape.png", "a/../b.png", "/abs.png", "bad:name.png", ".hidden.png", "a//b.png"],
)
async def test_upload_rejects_invalid_paths(api, path):
    _, vault_id, headers = await owner_vault(api)
    response = await upload(api, headers, vault_id, path, b"x")
    assert response.status_code == 422
    assert response.json()["type"].endswith("/invalid-path")


async def test_upload_of_a_note_path_points_to_notes(api):
    _, vault_id, headers = await owner_vault(api)
    response = await upload(api, headers, vault_id, "Notes/a.md", b"# hi\n")
    assert response.status_code == 422
    assert "/api/v1/notes" in response.json()["detail"]


async def test_upload_to_a_taken_path_is_409(api):
    _, vault_id, headers = await owner_vault(api)
    assert (await upload(api, headers, vault_id, "a.png", b"one")).status_code == 201
    response = await upload(api, headers, vault_id, "A.PNG", b"two")
    assert response.status_code == 409
    assert response.json()["type"].endswith("/path-taken")


async def test_upload_needs_an_editor(api):
    alice = api.user("alice")
    bob, carol = api.user("bob"), api.user("carol")
    vault_id = api.vault(alice, bob="viewer")
    viewer = await upload(api, await api.bearer(bob), vault_id, "a.png", b"x")
    assert viewer.status_code == 403
    outsider = await upload(api, await api.bearer(carol), vault_id, "a.png", b"x")
    assert outsider.status_code == 404
    read_token = await upload(api, api.api_key(alice, [vault_id], "read"), vault_id, "a.png", b"x")
    assert read_token.status_code == 403
    write_token = api.api_key(alice, [vault_id], "write")
    assert (await upload(api, write_token, vault_id, "a.png", b"x")).status_code == 201


async def test_upload_without_credentials_is_401(api):
    _, vault_id, _ = await owner_vault(api)
    assert (await upload(api, {}, vault_id, "a.png", b"x")).status_code == 401


@pytest.fixture
async def small_api(engine: Engine, make_settings: Callable[..., Settings]) -> AsyncIterator[Api]:
    settings = make_settings(max_blob_bytes=1000)
    app = create_app(settings)
    async with serve(app) as client:
        yield Api(app, client, engine, settings)


async def test_upload_larger_than_the_limit_is_413(small_api):
    _, vault_id, headers = await owner_vault(small_api)
    assert (await upload(small_api, headers, vault_id, "ok.bin", b"x" * 1000)).status_code == 201
    response = await upload(small_api, headers, vault_id, "big.bin", b"x" * 1001)
    assert response.status_code == 413
    assert response.json()["type"].endswith("/blob-too-large")
    huge = await upload(small_api, headers, vault_id, "huge.bin", b"x" * 200_000)
    assert huge.status_code == 413


async def test_chunked_upload_is_cut_off_at_the_limit(small_api):
    """Without Content-Length the body is counted as it arrives; reading stops past the
    limit instead of spooling the whole upload."""
    _, vault_id, headers = await owner_vault(small_api)
    sent = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal sent
        yield (
            b'--b\r\nContent-Disposition: form-data; name="vault_id"\r\n\r\n'
            + str(vault_id).encode()
            + b'\r\n--b\r\nContent-Disposition: form-data; name="path"\r\n\r\nbig.bin'
            + b'\r\n--b\r\nContent-Disposition: form-data; name="file"; filename="big.bin"\r\n'
            + b"Content-Type: application/octet-stream\r\n\r\n"
        )
        for _ in range(100):
            sent += 1
            yield b"x" * 10_000
        yield b"\r\n--b--\r\n"

    response = await small_api.client.post(
        "/api/v1/attachments",
        headers=headers | {"Content-Type": "multipart/form-data; boundary=b"},
        content=body(),
    )
    assert response.status_code == 413
    assert sent < 100
    anonymous = await upload(small_api, {}, vault_id, "huge.bin", b"x" * 200_000)
    assert anonymous.status_code == 401


async def test_idempotent_upload_replays_the_first_response(api):
    _, vault_id, headers = await owner_vault(api)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    first = await upload(api, headers, vault_id, "a.png", b"one", **key)
    again = await upload(api, headers, vault_id, "a.png", b"one", **key)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["etag"] == first.headers["etag"]
    assert again.headers["location"] == first.headers["location"]
    other = await upload(api, headers, vault_id, "a.png", b"two", **key)
    assert other.status_code == 422
    assert other.json()["type"].endswith("/idempotency-key-reused")


# Sniffing ----------------------------------------------------------------------------------


async def content(api: Api, headers: dict[str, str], attachment_id: str, **extra: str):
    return await api.client.get(
        f"/api/v1/attachments/{attachment_id}/content", headers=headers | extra
    )


async def test_html_disguised_as_png_is_downloaded(api):
    _, vault_id, headers = await owner_vault(api)
    html = b"\xef\xbb\xbf  <!DOCTYPE html><html><script>alert(1)</script></html>"
    created = await upload(api, headers, vault_id, "x.png", html, "image/png")
    assert created.status_code == 201
    assert created.json()["media_type"] == "text/html"
    response = await content(api, headers, created.json()["id"])
    assert response.status_code == 200
    assert response.content == html
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''x.png"
    assert response.headers["content-security-policy"] == "sandbox"


async def test_real_png_is_inline(api):
    _, vault_id, headers = await owner_vault(api)
    created = await upload(api, headers, vault_id, "Bilder/grün dot.png", png(), "text/html")
    assert created.json()["media_type"] == "image/png"
    response = await content(api, headers, created.json()["id"])
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == (
        "inline; filename*=UTF-8''gr%C3%BCn%20dot.png"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["etag"] == '"1"'


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "image/svg+xml"),
        (b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>', "image/svg+xml"),
        (b'<?xml version="1.0"?><feed/>', "application/xml"),
        (b"plain words\n", "text/plain"),
        (b"a" * 8191 + "ü".encode() * 10, "text/plain"),  # the sniffed head ends mid-character
        (b"\x00\x01\x02\xff\xfe", "application/octet-stream"),
        (b"%PDF-1.7\n", "application/pdf"),
    ],
)
async def test_sniffed_types(api, data, media_type):
    _, vault_id, headers = await owner_vault(api)
    created = await upload(api, headers, vault_id, "file.bin", data, "image/png")
    assert created.json()["media_type"] == media_type
    response = await content(api, headers, created.json()["id"])
    inline = media_type == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("inline;" if inline else "attachment;")


# Range -------------------------------------------------------------------------------------

DATA = bytes(range(256)) * 4  # 1024 bytes


@pytest.fixture
async def stored(api):
    _, vault_id, headers = await owner_vault(api)
    created = await upload(api, headers, vault_id, "data.bin", DATA)
    return headers, created.json()["id"], vault_id


async def test_full_download_advertises_ranges(api, stored):
    headers, attachment_id, _ = stored
    response = await content(api, headers, attachment_id)
    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "1024"
    assert response.headers["content-type"] == "application/octet-stream"


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [
        ("bytes=0-9", 0, 9),
        ("bytes=1000-", 1000, 1023),
        ("bytes=-24", 1000, 1023),
        ("bytes=-5000", 0, 1023),
        ("bytes=1020-5000", 1020, 1023),
        ("bytes=5-5", 5, 5),
    ],
)
async def test_single_range_is_206(api, stored, header, start, end):
    headers, attachment_id, _ = stored
    response = await content(api, headers, attachment_id, Range=header)
    assert response.status_code == 206
    assert response.content == DATA[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/1024"
    assert response.headers["content-length"] == str(end - start + 1)
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("header", ["bytes=1024-", "bytes=2000-3000", "bytes=-0"])
async def test_unsatisfiable_range_is_416(api, stored, header):
    headers, attachment_id, _ = stored
    response = await content(api, headers, attachment_id, Range=header)
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1024"


@pytest.mark.parametrize("header", ["bytes=0-1,5-6", "items=0-5", "bytes=9-2", "bytes=x-y"])
async def test_multiple_or_unparsable_ranges_get_the_whole_file(api, stored, header):
    headers, attachment_id, _ = stored
    response = await content(api, headers, attachment_id, Range=header)
    assert response.status_code == 200
    assert response.content == DATA


async def test_content_falls_back_to_history_when_the_vault_file_differs(api, stored):
    headers, attachment_id, _ = stored
    (on_disk,) = vault_files(api, "*/data.bin")
    on_disk.write_bytes(b"changed outside")
    response = await content(api, headers, attachment_id, Range="bytes=-24")
    assert response.status_code == 206
    assert response.content == DATA[-24:]


# Read access, delete, list -----------------------------------------------------------------


async def test_outsider_cannot_see_an_attachment(api, stored):
    _, attachment_id, _ = stored
    carol = await api.bearer(api.user("carol"))
    missing = await api.client.get(f"/api/v1/attachments/{uuid.uuid4()}", headers=carol)
    assert missing.status_code == 404
    for url in [
        f"/api/v1/attachments/{attachment_id}",
        f"/api/v1/attachments/{attachment_id}/content",
    ]:
        response = await api.client.get(url, headers=carol)
        assert response.status_code == 404
        assert response.json().keys() == missing.json().keys()
        for key in ("type", "title", "status", "detail"):
            assert response.json()[key] == missing.json()[key]


async def test_delete_needs_if_match(api, stored):
    headers, attachment_id, vault_id = stored
    url = f"/api/v1/attachments/{attachment_id}"
    assert (await api.client.delete(url, headers=headers)).status_code == 428
    stale = await api.client.delete(url, headers=headers | {"If-Match": '"7"'})
    assert stale.status_code == 412
    assert stale.json()["current"]["id"] == attachment_id
    assert stale.json()["current"]["revision"] == 1
    gone = await api.client.delete(url, headers=headers | {"If-Match": '"1"'})
    assert gone.status_code == 204
    assert (await api.client.get(url, headers=headers)).status_code == 404
    assert (await content(api, headers, attachment_id)).status_code == 404
    assert not vault_files(api, "*/data.bin")
    with Session(api.engine) as s:
        event = s.scalars(select(AuditEvent).where(AuditEvent.action == "attachment.delete")).one()
    assert event.target == attachment_id
    assert (await upload(api, headers, vault_id, "data.bin", b"new")).status_code == 201


async def test_delete_needs_an_editor(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault_id = api.vault(alice, bob="viewer")
    created = await upload(api, await api.bearer(alice), vault_id, "a.png", b"x")
    url = f"/api/v1/attachments/{created.json()['id']}"
    response = await api.client.delete(url, headers=await api.bearer(bob) | {"If-Match": '"1"'})
    assert response.status_code == 403
    viewer_read = await api.client.get(url, headers=await api.bearer(bob))
    assert viewer_read.status_code == 200


async def test_list_pages_through_a_folder(api):
    _, vault_id, headers = await owner_vault(api)
    for name in ["c.png", "a.png", "b.png", "d.png", "e.png"]:
        assert (await upload(api, headers, vault_id, f"Img/{name}", b"x")).status_code == 201
    await upload(api, headers, vault_id, "Img/Sub/deep.png", b"x")
    await upload(api, headers, vault_id, "top.png", b"x")
    await upload(api, headers, vault_id, "Imgx.png", b"x")

    seen, cursor = [], None
    while True:
        params = {"vault_id": str(vault_id), "folder": "Img", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = await api.client.get("/api/v1/attachments", headers=headers, params=params)
        assert page.status_code == 200
        body = page.json()
        assert len(body["items"]) <= 2
        seen += [item["path"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"Img/{n}.png" for n in "abcde"]

    everything = await api.client.get(
        "/api/v1/attachments", headers=headers, params={"vault_id": str(vault_id)}
    )
    assert len(everything.json()["items"]) == 8
    assert all(item["media_type"] == "text/plain" for item in everything.json()["items"])
    root = await api.client.get(
        "/api/v1/attachments", headers=headers, params={"vault_id": str(vault_id), "folder": ""}
    )
    assert [i["path"] for i in root.json()["items"]] == ["Imgx.png", "top.png"]


async def test_list_hides_notes_and_other_vaults(api):
    alice = api.user("alice")
    bob = api.user("bob")
    vault_id = api.vault(alice)
    headers = await api.bearer(alice)
    await upload(api, headers, vault_id, "a.png", b"x")
    note = b"# A note\n"
    committer = api.app.state.committers.get(vault_id, str(vault_files(api, "*")[0]))
    op = Create(
        uuid.uuid7(), uuid.uuid7(), "n.md", "note", "sha256:" + hashlib.sha256(note).hexdigest()
    )
    assert committer.commit(op, "test", note).status == "applied"
    mine = await api.client.get(
        "/api/v1/attachments", headers=headers, params={"vault_id": str(vault_id)}
    )
    assert [i["path"] for i in mine.json()["items"]] == ["a.png"]
    listing = await api.client.get(
        "/api/v1/attachments", headers=await api.bearer(bob), params={"vault_id": str(vault_id)}
    )
    assert listing.status_code == 404
    bad = await api.client.get(
        "/api/v1/attachments", headers=headers, params={"vault_id": str(vault_id), "cursor": "zz"}
    )
    assert bad.status_code == 400
