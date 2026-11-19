"""Resumable chunked blob upload and the streaming commit path (P5-02)."""

import hashlib
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.api import sync as sync_routes
from app.sync.history import HistoryStore
from app.vaults.models import Vault

pytestmark = pytest.mark.anyio

MIB = 1024 * 1024


def _hash(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _root(api, vault_id) -> Path:
    with Session(api.engine) as s:
        return Path(s.get(Vault, vault_id).root_path)


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _chunk(api, headers, vault, content_hash, data, first, total):
    last = first + len(data) - 1
    return await api.client.put(
        f"/api/v1/blobs/{content_hash[7:]}",
        params={"vault_id": str(vault)},
        content=data,
        headers=headers | {"Content-Range": f"bytes {first}-{last}/{total}"},
    )


async def _offset(api, headers, vault, content_hash) -> tuple[int, int]:
    response = await api.client.head(
        f"/api/v1/blobs/{content_hash[7:]}", params={"vault_id": str(vault)}, headers=headers
    )
    return response.status_code, int(response.headers.get("upload-offset", -1))


async def test_chunked_upload_resumes_after_an_interruption(api, owner):
    vault, headers = owner
    data = os.urandom(20 * MIB)
    content_hash, total = _hash(data), len(data)
    assert await _offset(api, headers, vault, content_hash) == (404, 0)

    first = await _chunk(api, headers, vault, content_hash, data[: 8 * MIB], 0, total)
    assert first.status_code == 202
    assert first.headers["upload-offset"] == str(8 * MIB)
    # The connection drops here; the client asks where to continue.
    assert await _offset(api, headers, vault, content_hash) == (404, 8 * MIB)
    # A retried first chunk is refused with the offset to continue from.
    again = await _chunk(api, headers, vault, content_hash, data[: 8 * MIB], 0, total)
    assert again.status_code == 409
    assert again.headers["upload-offset"] == str(8 * MIB)

    second = await _chunk(
        api, headers, vault, content_hash, data[8 * MIB : 16 * MIB], 8 * MIB, total
    )
    assert second.status_code == 202
    last = await _chunk(api, headers, vault, content_hash, data[16 * MIB :], 16 * MIB, total)
    assert last.status_code == 204
    status, _ = await _offset(api, headers, vault, content_hash)
    assert status == 200
    uploads = Path(api.settings.history_root) / str(vault) / "uploads"
    assert not list(uploads.iterdir())

    op = {
        "op": "create",
        "client_op_id": str(uuid.uuid7()),
        "file_id": str(uuid.uuid7()),
        "path": "big.bin",
        "kind": "attachment",
        "content_hash": content_hash,
    }
    push = await api.client.post(
        f"/api/v1/sync/{vault}/push", json={"operations": [op]}, headers=headers
    )
    [result] = push.json()["results"]
    assert result["status"] == "applied"
    assert (_root(api, vault) / "big.bin").read_bytes() == data
    pulled = await api.client.get(f"/api/v1/sync/{vault}/changes", headers=headers)
    assert pulled.json()["entries"][0]["size"] == total


async def test_a_completed_upload_with_the_wrong_bytes_is_discarded(api, owner):
    vault, headers = owner
    claimed = _hash(b"what the client meant")
    response = await _chunk(api, headers, vault, claimed, b"something else", 0, 14)
    assert response.status_code == 422
    assert response.json()["type"].endswith("/blob-hash-mismatch")
    assert await _offset(api, headers, vault, claimed) == (404, 0)


@pytest.mark.parametrize(
    "header",
    ["bytes 5-1/10", "bytes 0-10/10", "items 0-1/2", "bytes 0-1/*", "bytes 1-2/10"],
)
async def test_bad_content_ranges_are_400(api, owner, header):
    vault, headers = owner
    content_hash = _hash(b"0123456789")
    response = await api.client.put(
        f"/api/v1/blobs/{content_hash[7:]}",
        params={"vault_id": str(vault)},
        content=b"01",
        headers=headers | {"Content-Range": header},
    )
    # "bytes 1-2/10" is well formed but does not start at the offset: 409, not 400.
    assert response.status_code == (409 if header == "bytes 1-2/10" else 400)


async def test_chunk_and_total_limits(api, owner, make_settings, monkeypatch):
    vault, headers = owner
    monkeypatch.setattr(sync_routes, "MAX_CHUNK_BYTES", 4)
    data = b"0123456789"
    too_big = await _chunk(api, headers, vault, _hash(data), data[:5], 0, 10)
    assert too_big.status_code == 413
    assert too_big.json()["type"].endswith("/chunk-too-large")
    api.app.state.settings = make_settings(max_blob_bytes=9)
    over = await _chunk(api, headers, vault, _hash(data), data[:4], 0, 10)
    assert over.status_code == 413
    assert over.json()["type"].endswith("/blob-too-large")


async def test_attachment_commits_never_read_whole_blobs(api, owner, monkeypatch):
    """The commit path streams attachments: from the store into the vault on create and
    update, and a concurrent attachment update is a conflict decided by hash."""
    vault, headers = owner
    real_get = HistoryStore.get

    def notes_only(self, content_hash):
        data = real_get(self, content_hash)
        assert len(data) < MIB, "an attachment was read whole"
        return data

    monkeypatch.setattr(HistoryStore, "get", notes_only)
    blobs = [os.urandom(2 * MIB) for _ in range(3)]
    for blob in blobs:
        response = await api.client.put(
            f"/api/v1/blobs/{_hash(blob)[7:]}",
            params={"vault_id": str(vault)},
            content=blob,
            headers=headers,
        )
        assert response.status_code == 204
    fid = str(uuid.uuid7())

    async def push(op):
        response = await api.client.post(
            f"/api/v1/sync/{vault}/push", json={"operations": [op]}, headers=headers
        )
        return response.json()["results"][0]

    def update(base, blob):
        return {
            "op": "update",
            "client_op_id": str(uuid.uuid7()),
            "file_id": fid,
            "base_revision": base,
            "content_hash": _hash(blob),
        }

    created = await push(
        {
            "op": "create",
            "client_op_id": str(uuid.uuid7()),
            "file_id": fid,
            "path": "a.bin",
            "kind": "attachment",
            "content_hash": _hash(blobs[0]),
        }
    )
    assert created["status"] == "applied"
    assert (await push(update(1, blobs[1])))["status"] == "applied"
    conflict = await push(update(1, blobs[2]))
    assert conflict["status"] == "conflict"
    root = _root(api, vault)
    assert (root / "a.bin").read_bytes() == blobs[1]
    assert (root / conflict["path"]).read_bytes() == blobs[2]


async def test_multipart_attachment_upload_streams_into_the_store(api, owner):
    vault, headers = owner
    data = b"\x89PNG\r\n\x1a\n" + os.urandom(3 * MIB)
    response = await api.client.post(
        "/api/v1/attachments",
        data={"vault_id": str(vault), "path": "img/pic.png"},
        files={"file": ("pic.png", data, "application/octet-stream")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["media_type"] == "image/png"
    assert body["size"] == len(data)
    assert body["content_hash"] == _hash(data)
    assert (_root(api, vault) / "img/pic.png").read_bytes() == data


@pytest.fixture
def _only_when_slow(request: pytest.FixtureRequest) -> None:
    if "slow" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("slow: run with -m slow")


@pytest.mark.slow
@pytest.mark.usefixtures("_only_when_slow")
async def test_interrupted_500_mib_upload_resumes(api, owner, tmp_path):
    """Roadmap P5-02 acceptance: a 500 MiB upload interrupted halfway resumes and commits."""
    vault, headers = owner
    total, chunk = 500 * MIB, 8 * MIB
    source = tmp_path / "big.bin"
    content_hash = _write_random(source, total)
    offset = 0
    for data in _chunks(source, 0, chunk):  # the first half, then the "connection" drops
        response = await _chunk(api, headers, vault, content_hash, data, offset, total)
        assert response.status_code == 202
        offset += len(data)
        if offset >= total // 2:
            break
    status, resume_at = await _offset(api, headers, vault, content_hash)
    assert status == 404
    assert resume_at == offset
    for data in _chunks(source, resume_at, chunk):
        response = await _chunk(api, headers, vault, content_hash, data, resume_at, total)
        resume_at += len(data)
        assert response.status_code == (204 if resume_at == total else 202)
    op = {
        "op": "create",
        "client_op_id": str(uuid.uuid7()),
        "file_id": str(uuid.uuid7()),
        "path": "big.bin",
        "kind": "attachment",
        "content_hash": content_hash,
    }
    push = await api.client.post(
        f"/api/v1/sync/{vault}/push", json={"operations": [op]}, headers=headers
    )
    assert push.json()["results"][0]["status"] == "applied"
    written = _root(api, vault) / "big.bin"
    assert written.stat().st_size == total
    assert _file_hash(written) == content_hash


def _write_random(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    with open(path, "wb") as fh:
        for _ in range(size // MIB):
            block = os.urandom(MIB)
            digest.update(block)
            fh.write(block)
    return "sha256:" + digest.hexdigest()


def _chunks(path: Path, start: int, size: int) -> Iterator[bytes]:
    with open(path, "rb") as fh:
        fh.seek(start)
        while data := fh.read(size):
            yield data


def _file_hash(path: Path) -> str:
    with open(path, "rb") as fh:
        return "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
