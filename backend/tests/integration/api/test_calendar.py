"""Calendar feeds (P6-03) over the v1 API."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar.models import CalendarFeed
from app.vaults.models import VaultMember
from tests.integration.api.test_notes import _create

pytestmark = pytest.mark.anyio


@pytest.fixture
async def owner(api):
    alice = api.user("alice")
    return api.vault(alice), await api.bearer(alice)


async def _feed(api, headers, vault, name="Tasks"):
    response = await api.client.post(
        "/api/v1/calendar-feeds", json={"vault_id": str(vault), "name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_feed_lists_open_dated_tasks(api, owner):
    vault, headers = owner
    await _create(
        api,
        headers,
        vault,
        "Plans.md",
        "- [ ] pay rent ⏫ 🔁 every month 📅 2026-12-01\n"
        "- [ ] call Bob, Ann; then (@2026-11-20 10:30)\n"
        "- [x] done 📅 2026-11-01\n"
        "- [ ] undated\n",
    )
    created = await _feed(api, headers, vault)
    assert created["url"].startswith("/api/v1/calendar/tasks.ics?token=onc_")
    response = await api.client.get(created["url"])  # no credentials: the token is one
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/calendar")
    body = response.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:pay rent\r\n" in body
    assert "DTSTART;VALUE=DATE:20261201\r\nDTEND;VALUE=DATE:20261202\r\n" in body
    assert "SUMMARY:call Bob\\, Ann\\; then\r\n" in body
    assert "DTSTART:20261120T103000\r\nDURATION:PT15M\r\nBEGIN:VALARM" in body
    assert "undated" not in body and "done" not in body
    listed = await api.client.get("/api/v1/calendar-feeds", headers=headers)
    [feed] = listed.json()["items"]
    assert feed["id"] == created["feed"]["id"] and feed["last_used_at"] is not None
    assert "token" not in feed


async def test_bad_and_revoked_tokens(api, owner):
    vault, headers = owner
    created = await _feed(api, headers, vault)
    assert (await api.client.get("/api/v1/calendar/tasks.ics?token=onc_nope")).status_code == 404
    assert (await api.client.get("/api/v1/calendar/tasks.ics")).status_code == 422
    gone = await api.client.delete(
        f"/api/v1/calendar-feeds/{created['feed']['id']}", headers=headers
    )
    assert gone.status_code == 204
    assert (await api.client.get(created["url"])).status_code == 404
    again = await api.client.delete(
        f"/api/v1/calendar-feeds/{created['feed']['id']}", headers=headers
    )
    assert again.status_code == 404


async def test_feed_stops_when_the_owner_loses_access(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice, bob="viewer")
    created = await _feed(api, await api.bearer(bob), vault)
    assert (await api.client.get(created["url"])).status_code == 200
    with Session(api.engine) as s, s.begin():
        s.delete(s.get(VaultMember, (vault, bob.id)))
    assert (await api.client.get(created["url"])).status_code == 404


async def test_only_members_and_not_tokens_create_feeds(api, owner):
    vault, headers = owner
    bob = api.user("bob")
    response = await api.client.post(
        "/api/v1/calendar-feeds", json={"vault_id": str(vault)}, headers=await api.bearer(bob)
    )
    assert response.status_code == 404
    token = api.api_key(api.user("carol"), [vault], scope="read")
    refused = await api.client.post(
        "/api/v1/calendar-feeds", json={"vault_id": str(vault)}, headers=token
    )
    assert refused.status_code == 403
    others = await api.client.delete(
        f"/api/v1/calendar-feeds/{(await _feed(api, headers, vault))['feed']['id']}",
        headers=await api.bearer(bob),
    )
    assert others.status_code == 404


async def test_only_the_hash_is_stored(api, owner):
    vault, headers = owner
    created = await _feed(api, headers, vault)
    token = created["url"].split("token=")[1]
    with Session(api.engine) as s:
        hashes = s.scalars(select(CalendarFeed.token_hash)).all()
    assert token not in hashes and len(hashes) == 1
