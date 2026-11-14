"""Users, devices and personal access tokens, and the auth matrix over every account
route (Phase 2 Task 4)."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth.crypto import issue_access_token
from app.auth.dependencies import CSRF_HEADER
from app.auth.models import Device, PersonalAccessToken
from app.auth.store import signing_key
from app.core.audit import AuditEvent

pytestmark = pytest.mark.anyio


def actions(api) -> list[str]:
    with Session(api.engine) as s:
        return list(s.scalars(select(AuditEvent.action)))


# Users -----------------------------------------------------------------------------------


async def test_admin_lists_users_with_cursor_pages(api):
    root = api.user("root", admin=True)
    for name in ["Carol", "bob", "dave", "alice"]:
        api.user(name)
    headers = await api.bearer(root)
    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await api.client.get("/api/v1/users", params=params, headers=headers)).json()
        seen += [user["username"] for user in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ["alice", "bob", "Carol", "dave", "root"]


async def test_admin_creates_a_user_idempotently(api):
    root = api.user("root", admin=True)
    headers = await api.bearer(root) | {"Idempotency-Key": str(uuid.uuid4())}
    body = {"username": "Erin", "password": "a long password", "email": "erin@example.org"}
    first = await api.client.post("/api/v1/users", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert first.json()["email"] == "erin@example.org"
    again = await api.client.post("/api/v1/users", json=body, headers=headers)
    assert again.status_code == 201
    assert again.json() == first.json()
    other = await api.client.post(
        "/api/v1/users", json=body | {"username": "frank"}, headers=headers
    )
    assert other.status_code == 422
    assert other.json()["type"].endswith("/idempotency-key-reused")
    login = await api.client.post(
        "/api/v1/auth/login", json={"username": "erin", "password": "a long password"}
    )
    assert login.status_code == 200
    assert actions(api).count("user.create") == 1


async def test_duplicate_username_is_409(api):
    root = api.user("root", admin=True)
    api.user("alice")
    body = {"username": "ALICE", "password": "a long password"}
    response = await api.client.post("/api/v1/users", json=body, headers=await api.bearer(root))
    assert response.status_code == 409


async def test_non_admin_cannot_manage_users(api):
    alice = api.user("alice")
    headers = await api.bearer(alice)
    assert (await api.client.get("/api/v1/users", headers=headers)).status_code == 403
    body = {"username": "mallory", "password": "a long password"}
    assert (await api.client.post("/api/v1/users", json=body, headers=headers)).status_code == 403


# Devices -------------------------------------------------------------------------------------


async def test_devices_are_listed_and_revoked_by_their_owner_only(api):
    alice, bob = api.user("alice"), api.user("bob")
    current = await api.bearer(alice)
    await api.bearer(alice)  # a second device
    bob_headers = await api.bearer(bob)
    page = (await api.client.get("/api/v1/devices", headers=current)).json()
    assert len(page["items"]) == 2
    assert [d["current"] for d in page["items"]] == [True, False]
    other_id = page["items"][1]["id"]
    assert (
        await api.client.delete(f"/api/v1/devices/{other_id}", headers=bob_headers)
    ).status_code == 404
    assert (
        await api.client.delete(f"/api/v1/devices/{other_id}", headers=current)
    ).status_code == 204
    page = (await api.client.get("/api/v1/devices", headers=current)).json()
    assert [d["id"] for d in page["items"]] != [other_id] and len(page["items"]) == 1
    with Session(api.engine) as s:
        assert s.get(Device, uuid.UUID(other_id)).revoked_at is not None
    assert "device.revoke" in actions(api)


async def test_revoking_the_current_device_logs_it_out(api):
    alice = api.user("alice")
    headers = await api.bearer(alice)
    device_id = (await api.client.get("/api/v1/devices", headers=headers)).json()["items"][0]["id"]
    assert (
        await api.client.delete(f"/api/v1/devices/{device_id}", headers=headers)
    ).status_code == 204
    assert (await api.client.get("/api/v1/me", headers=headers)).status_code == 401


# Personal access tokens ----------------------------------------------------------------------


async def test_token_is_shown_once_and_works_in_its_vaults(api):
    alice = api.user("alice")
    vault = api.vault(alice)
    headers = await api.bearer(alice)
    body = {"name": "backup", "vault_ids": [str(vault)], "scope": "read"}
    response = await api.client.post("/api/v1/tokens", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["secret"].startswith("onp_")
    assert created["token"]["vault_ids"] == [str(vault)]
    listed = (await api.client.get("/api/v1/tokens", headers=headers)).json()
    assert [t["id"] for t in listed["items"]] == [created["token"]["id"]]
    assert "secret" not in str(listed) and created["secret"] not in str(listed)
    with Session(api.engine) as s:
        row = s.get(PersonalAccessToken, uuid.UUID(created["token"]["id"]))
        assert created["secret"] not in row.token_hash
    assert "token.create" in actions(api)


@pytest.mark.parametrize(
    ("role", "scope", "status"),
    [
        ("viewer", "read", 201),
        ("viewer", "write", 404),
        ("editor", "write", 201),
        (None, "read", 404),
    ],
)
async def test_token_needs_the_role_in_every_vault(api, role, scope, status):
    alice, bob = api.user("alice"), api.user("bob")
    own = api.vault(bob)
    members = {"bob": role} if role else {}
    shared = api.vault(alice, **members)
    body = {"name": "t", "vault_ids": [str(own), str(shared)], "scope": scope}
    response = await api.client.post("/api/v1/tokens", json=body, headers=await api.bearer(bob))
    assert response.status_code == status, response.text


async def test_token_revocation_is_owner_only(api):
    alice, bob = api.user("alice"), api.user("bob")
    vault = api.vault(alice)
    headers = await api.bearer(alice)
    body = {"name": "t", "vault_ids": [str(vault)]}
    created = (await api.client.post("/api/v1/tokens", json=body, headers=headers)).json()
    token_id = created["token"]["id"]
    bob_headers = await api.bearer(bob)
    assert (
        await api.client.delete(f"/api/v1/tokens/{token_id}", headers=bob_headers)
    ).status_code == 404
    assert (
        await api.client.delete(f"/api/v1/tokens/{token_id}", headers=headers)
    ).status_code == 204
    assert (await api.client.get("/api/v1/tokens", headers=headers)).json()["items"] == []
    with Session(api.engine) as s:
        assert s.get(PersonalAccessToken, uuid.UUID(token_id)).revoked_at is not None
    assert "token.revoke" in actions(api)


# The auth matrix -----------------------------------------------------------------------------

# Each account route with a request that succeeds for a person (status below 400 or a 404
# for a random id); `None` for the body means no body.
ROUTES = [
    ("GET", "/api/v1/me", None),
    ("GET", "/api/v1/users", None),
    ("POST", "/api/v1/users", "user"),
    ("GET", "/api/v1/devices", None),
    ("DELETE", "/api/v1/devices/{random}", None),
    ("GET", "/api/v1/tokens", None),
    ("POST", "/api/v1/tokens", "token"),
    ("DELETE", "/api/v1/tokens/{random}", None),
    ("POST", "/api/v1/auth/logout", None),
]
CREDENTIALS = ["none", "bearer", "cookie", "cookie_no_csrf", "pat", "revoked", "expired"]


async def credential(api, user, vault, kind):
    if kind == "none":
        return {}
    if kind == "pat":
        return api.api_key(user, [vault], "write")
    if kind in ("cookie", "cookie_no_csrf"):
        headers = await api.cookie(user)
        if kind == "cookie_no_csrf":
            del headers[CSRF_HEADER]
        return headers
    headers = await api.bearer(user)
    async with AsyncSession(api.app.state.engine) as db:
        device = await db.scalar(select(Device).order_by(Device.id.desc()).limit(1))
        if kind == "revoked":
            await db.execute(
                update(Device)
                .where(Device.id == device.id)
                .values(revoked_at=dt.datetime.now(dt.UTC))
            )
            await db.commit()
        if kind == "expired":
            key = await signing_key(db)
            stale = issue_access_token(
                key.kid,
                key.private_pem,
                user.id,
                device.id,
                dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            )
            return {"Authorization": f"Bearer {stale}"}
    return headers


@pytest.mark.parametrize("kind", CREDENTIALS)
async def test_auth_matrix(api, kind):
    root = api.user("root", admin=True)
    vault = api.vault(root)
    for method, path, body_kind in ROUTES:
        headers = await credential(api, root, vault, kind)
        body = None
        if body_kind == "user":
            body = {"username": f"u{uuid.uuid4().hex[:8]}", "password": "a long password"}
        if body_kind == "token":
            body = {"name": "t", "vault_ids": [str(vault)]}
        url = path.replace("{random}", str(uuid.uuid4()))
        response = await api.client.request(method, url, json=body, headers=headers)
        where = (kind, method, path, response.status_code)
        if kind in ("none", "pat", "revoked", "expired"):
            assert response.status_code == 401, where
        elif kind == "cookie_no_csrf" and method != "GET":
            assert response.status_code == 403, where
            assert response.json()["type"].endswith("/csrf-failed")
        else:
            assert response.status_code < 400 or response.status_code == 404, where
