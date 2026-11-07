"""The three credentials, revocation and vault access (Phase 2 Task 3)."""

import datetime as dt

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.api.deps import require_vault, vault_role
from app.auth.crypto import issue_access_token
from app.auth.dependencies import Principal
from app.auth.models import Device, User
from app.auth.store import signing_key
from app.core.problems import ProblemError

pytestmark = pytest.mark.anyio


async def test_anonymous_is_401_with_problem(api):
    response = await api.client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_bearer_token_identifies_the_user(api):
    alice = api.user("alice")
    response = await api.client.get("/api/v1/me", headers=await api.bearer(alice))
    assert response.status_code == 200
    assert response.json()["username"] == "alice"
    assert response.json()["is_admin"] is False


@pytest.mark.parametrize("token", ["garbage", "a.b.c", ""])
async def test_malformed_bearer_is_401(api, token):
    response = await api.client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_revoked_device_and_disabled_user_are_401(api):
    alice, bob = api.user("alice"), api.user("bob")
    alice_headers, bob_headers = await api.bearer(alice), await api.bearer(bob)
    with Session(api.engine) as s, s.begin():
        s.execute(
            update(Device)
            .where(Device.user_id == alice.id)
            .values(revoked_at=dt.datetime.now(dt.UTC))
        )
        s.execute(update(User).where(User.id == bob.id).values(disabled=True))
    assert (await api.client.get("/api/v1/me", headers=alice_headers)).status_code == 401
    assert (await api.client.get("/api/v1/me", headers=bob_headers)).status_code == 401


async def test_expired_access_token_is_401(api):
    alice = api.user("alice")
    headers = await api.bearer(alice)  # creates the device and the key
    async with AsyncSession(api.app.state.engine) as db:
        key = await signing_key(db)
        device = (await db.execute(Device.__table__.select())).first()
        stale = issue_access_token(
            key.kid,
            key.private_pem,
            alice.id,
            device.id,
            dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
        )
    assert (await api.client.get("/api/v1/me", headers=headers)).status_code == 200
    expired = {"Authorization": f"Bearer {stale}"}
    assert (await api.client.get("/api/v1/me", headers=expired)).status_code == 401


async def test_token_signed_by_an_unknown_key_is_401(api):
    from app.auth.crypto import new_signing_key

    alice = api.user("alice")
    headers = await api.bearer(alice)
    kid, pem = new_signing_key()
    async with AsyncSession(api.app.state.engine) as db:
        device = (await db.execute(Device.__table__.select())).first()
    forged = issue_access_token(kid, pem, alice.id, device.id, dt.datetime.now(dt.UTC))
    assert (await api.client.get("/api/v1/me", headers=headers)).status_code == 200
    response = await api.client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


async def test_csrf_matrix(api):
    alice = api.user("alice")
    cookie = await api.cookie(alice)
    assert (
        await api.client.get("/api/v1/me", headers={"Cookie": cookie["Cookie"]})
    ).status_code == 200
    body = {"name": "t", "vault_ids": ["0192a0c4-6a1e-7c3e-9a0b-5d0e1f2a3b4c"]}
    no_csrf = await api.client.post(
        "/api/v1/tokens", json=body, headers={"Cookie": cookie["Cookie"]}
    )
    assert no_csrf.status_code == 403
    assert no_csrf.json()["type"].endswith("/csrf-failed")
    wrong = {"Cookie": cookie["Cookie"], "X-CSRF-Token": "0" * 64}
    assert (await api.client.post("/api/v1/tokens", json=body, headers=wrong)).status_code == 403
    # With the right token the request reaches the endpoint (a stub until Task 4).
    assert (await api.client.post("/api/v1/tokens", json=body, headers=cookie)).status_code != 403
    # A bearer request needs no CSRF token.
    bearer = await api.bearer(alice)
    assert (await api.client.post("/api/v1/tokens", json=body, headers=bearer)).status_code != 403


async def test_personal_access_token_is_not_a_person(api):
    alice = api.user("alice")
    vault = api.vault(alice)
    key = api.api_key(alice, [vault])
    assert (await api.client.get("/api/v1/me", headers=key)).status_code == 401
    assert (
        await api.client.get("/api/v1/me", headers={"X-API-Key": "onp_wrong"})
    ).status_code == 401


async def test_vault_role_matrix(api):
    alice, bob, carol = api.user("alice"), api.user("bob"), api.user("carol")
    vault = api.vault(alice, bob="viewer")
    other = api.vault(carol)

    def person(user):
        return Principal(id=str(user.id), kind="user", user_id=user.id)

    def pat(user, vaults, scope):
        return Principal(
            id=str(user.id),
            kind="api_key",
            user_id=user.id,
            pat_vaults=frozenset(vaults),
            pat_scope=scope,
        )

    async with AsyncSession(api.app.state.engine) as db:
        assert await vault_role(db, person(alice), vault) == "owner"
        assert await vault_role(db, person(bob), vault) == "viewer"
        assert await vault_role(db, person(carol), vault) is None
        assert await vault_role(db, pat(alice, [vault], "write"), vault) == "editor"
        assert await vault_role(db, pat(alice, [vault], "read"), vault) == "viewer"
        assert await vault_role(db, pat(alice, [other], "write"), vault) is None
        with pytest.raises(ProblemError) as missing:
            await require_vault(db, person(carol), vault, "viewer")
        assert missing.value.status_code == 404
        with pytest.raises(ProblemError) as low:
            await require_vault(db, person(bob), vault, "editor")
        assert low.value.status_code == 403
        with pytest.raises(ProblemError) as foreign:
            await require_vault(db, person(alice), other, "viewer")
        assert foreign.value.status_code == 404  # same answer as a missing vault


async def test_audit_log_is_append_only(api):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with Session(api.engine) as s, s.begin():
        s.execute(text("INSERT INTO audit_events (id, action) VALUES (gen_random_uuid(), 'x')"))
    for statement in ("UPDATE audit_events SET action = 'y'", "DELETE FROM audit_events"):
        with Session(api.engine) as s, pytest.raises(DBAPIError, match="append-only"):
            s.execute(text(statement))
