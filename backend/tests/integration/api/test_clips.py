"""Web clips (P6-04) over the v1 API."""

import pytest

from tests.integration.api.test_notes import _content

pytestmark = pytest.mark.anyio

PAGE = (
    "<article><h1>Big news</h1><p>Read <a href='/more'>more</a> or "
    "<a href='javascript:steal()'>this</a>.</p><img src='pics/a.png' alt='A'>"
    "<script>alert(1)</script><form><input name=q></form></article>"
)


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return alice, api.vault(alice), await api.bearer(alice)


async def _clip(api, headers, vault, **extra):
    body = {"vault_id": str(vault), "url": "https://news.example/2026/story", "html": PAGE}
    return await api.client.post("/api/v1/clips", json=body | extra, headers=headers)


async def test_clip_becomes_a_note(api, owner):
    _, vault, headers = owner
    response = await _clip(api, headers, vault, title="Big news: today", tags=["read later"])
    assert response.status_code == 201, response.text
    note = response.json()
    assert note["path"] == "Clippings/Big news today.md"
    assert note["title"] == "Big news: today"
    assert note["tags"] == ["clippings", "read-later"]
    text = (await _content(api, headers, note["id"])).decode()
    assert text.startswith(
        '---\ntitle: "Big news: today"\nsource: "https://news.example/2026/story"\n'
    )
    assert text.endswith(
        "# Big news\n\nRead [more](https://news.example/more) or [this].\n\n"
        "![A](https://news.example/2026/pics/a.png)\n"
    )
    assert "alert" not in text and "input" not in text
    again = await _clip(api, headers, vault, title="Big news: today")
    assert again.json()["path"] == "Clippings/Big news today 2.md"


async def test_clip_with_a_write_token(api, owner):
    alice, vault, _ = owner
    write = api.api_key(alice, [vault], scope="write")
    assert (await _clip(api, write, vault, folder="Web")).json()["path"] == "Web/Clipping.md"
    read = api.api_key(alice, [vault], scope="read")
    assert (await _clip(api, read, vault)).status_code == 403


async def test_clip_refusals(api, owner):
    _, vault, headers = owner
    assert (await _clip(api, headers, vault, url="file:///etc/passwd")).status_code == 422
    assert (await _clip(api, headers, vault, folder="../x")).status_code == 422
    assert (await _clip(api, {}, vault)).status_code == 401
