"""Evernote ENEX import (P6-10) over the v1 API."""

import base64
import hashlib

import pytest

from tests.integration.api.test_notes import _content

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _note(title, body, *, resources=(), tags=(), created="20261114T081500Z"):
    res = "".join(
        f"<resource><data encoding='base64'>{base64.b64encode(data).decode()}</data>"
        f"<mime>{mime}</mime><resource-attributes><file-name>{name}</file-name>"
        "</resource-attributes></resource>"
        for name, mime, data in resources
    )
    tag_xml = "".join(f"<tag>{t}</tag>" for t in tags)
    return (
        f"<note><title>{title}</title><content><![CDATA[<?xml version='1.0'?>"
        f"<!DOCTYPE en-note SYSTEM 'http://xml.evernote.com/pub/enml2.dtd'>"
        f"<en-note>{body}</en-note>]]></content><created>{created}</created>{tag_xml}{res}</note>"
    )


def _enex(*notes):
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<!DOCTYPE en-export SYSTEM 'http://xml.evernote.com/pub/evernote-export4.dtd'>"
        f"<en-export>{''.join(notes)}</en-export>"
    ).encode()


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _import(api, headers, vault, data, **form):
    return await api.client.post(
        "/api/v1/imports/enex",
        data={"vault_id": str(vault), **form},
        files={"file": ("export.enex", data, "application/xml")},
        headers=headers,
    )


async def test_import_notes_with_attachments(api, owner):
    vault, headers = owner
    md5 = hashlib.md5(PNG, usedforsecurity=False).hexdigest()
    data = _enex(
        _note(
            "Trip: Rome/Paris",
            f"<div><en-todo checked='true'/>Pack</div><en-media hash='{md5}' type='image/png'/>",
            resources=[("image.png", "image/png", PNG)],
            tags=["travel plans"],
        ),
        _note("Trip: Rome/Paris", "<p>second with the same title</p>"),
    )
    response = await _import(api, headers, vault, data, folder="Imported/Evernote")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [n["path"] for n in body["notes"]] == [
        "Imported/Evernote/Trip Rome Paris.md",
        "Imported/Evernote/Trip Rome Paris 2.md",
    ]
    assert body["attachments"] == 1 and body["skipped"] == []
    first = body["notes"][0]["id"]
    text = (await _content(api, headers, first)).decode()
    assert text == (
        "---\n"
        'tags: ["travel-plans"]\n'
        "created: 2026-11-14T08:15:00Z\n"
        f"id: {first}\n"
        "---\n"
        "- [x] Pack\n\n"
        "![[Imported/Evernote/_resources/Trip Rome Paris.resources/image.png]]\n"
    )
    attachments = await api.client.get(
        "/api/v1/attachments", params={"vault_id": str(vault)}, headers=headers
    )
    assert [a["path"] for a in attachments.json()["items"]] == [
        "Imported/Evernote/_resources/Trip Rome Paris.resources/image.png"
    ]
    links = await api.client.get(f"/api/v1/notes/{first}/links", headers=headers)
    assert links.json()["unresolved"] == []  # the embed resolves to the attachment
    tasks = await api.client.get(f"/api/v1/notes/{first}", headers=headers)
    assert tasks.json()["tags"] == ["travel-plans"]


async def test_invalid_files_and_folders(api, owner):
    vault, headers = owner
    assert (await _import(api, headers, vault, b"not xml")).status_code == 422
    bad_folder = await _import(api, headers, vault, _enex(), folder="../up")
    assert bad_folder.status_code == 422
    empty = await _import(api, headers, vault, _enex())
    assert empty.status_code == 200 and empty.json()["notes"] == []


async def test_entity_expansion_is_refused(api, owner):
    vault, headers = owner
    bomb = (
        b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaaaaaaaa'>"
        + b"".join(
            f"<!ENTITY {c} '{('&' + p + ';') * 10}'>".encode()
            for p, c in zip("abcdefg", "bcdefgh", strict=True)
        )
        + b"]><en-export><note><title>&h;</title></note></en-export>"
    )
    response = await _import(api, headers, vault, bomb)
    assert response.status_code == 422


async def test_viewers_cannot_import(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    response = await _import(api, await api.bearer(bob), vault, _enex(_note("x", "y")))
    assert response.status_code == 403


async def test_anonymous_is_refused_before_the_body(api, owner):
    vault, _ = owner
    response = await _import(api, {}, vault, _enex(_note("x", "y")))
    assert response.status_code == 401
