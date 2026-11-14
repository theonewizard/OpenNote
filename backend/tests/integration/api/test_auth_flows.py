"""Login, OAuth code + PKCE, refresh rotation, logout (Phase 2 Task 4)."""

import datetime as dt
import hashlib
import uuid
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.dependencies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.auth.models import AuthRequest, Device, RefreshToken, User, WebSession
from app.core.audit import AuditEvent
from tests.integration.api.conftest import PASSWORD

pytestmark = pytest.mark.anyio

APPLE = {"client_id": "opennote-apple", "redirect_uri": "opennote://auth/callback"}


def pkce() -> tuple[str, str]:
    verifier = uuid.uuid4().hex + uuid.uuid4().hex
    digest = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, digest.rstrip(b"=").decode()


def authorize_params(challenge: str, **overrides: str) -> dict[str, str]:
    return {
        "response_type": "code",
        **APPLE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz-state",
    } | overrides


def set_cookies(response) -> dict[str, str]:
    """name -> the whole Set-Cookie header, lowercased."""
    return {
        header.split("=", 1)[0]: header.lower()
        for header in response.headers.get_list("set-cookie")
    }


def cookie_value(response, name: str) -> str:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(name + "="):
            return header.split("=", 1)[1].split(";", 1)[0]
    raise KeyError(name)


async def login(api, username="alice", password=PASSWORD, **extra):
    body = {"username": username, "password": password} | extra
    return await api.client.post("/api/v1/auth/login", json=body)


async def code_for(api, username="alice", **params) -> tuple[str, str]:
    """Run authorize -> login page -> login; return (code, verifier)."""
    verifier, challenge = pkce()
    start = await api.client.get(
        "/api/v1/auth/authorize", params=authorize_params(challenge, **params)
    )
    assert start.status_code == 302, start.text
    location = urlsplit(start.headers["location"])
    assert location.path == "/login"
    request_id = parse_qs(location.query)["auth_request"][0]
    done = await login(api, username, auth_request=request_id)
    assert done.status_code == 200, done.text
    redirect = urlsplit(done.json()["redirect_to"])
    query = parse_qs(redirect.query)
    assert query["state"] == ["xyz-state"]
    assert query["code"][0].startswith("onc_")
    return query["code"][0], verifier


async def exchange(api, code, verifier, **overrides):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": verifier,
        **APPLE,
        "device_name": "Alice's iPhone",
        "device_platform": "ios",
    } | overrides
    return await api.client.post("/api/v1/auth/token", data=data)


async def refresh(api, token, client_id="opennote-apple"):
    data = {"grant_type": "refresh_token", "refresh_token": token, "client_id": client_id}
    return await api.client.post("/api/v1/auth/token", data=data)


def actions(api) -> list[str]:
    with Session(api.engine) as s:
        return list(s.scalars(select(AuditEvent.action).order_by(AuditEvent.at, AuditEvent.id)))


# Local login ------------------------------------------------------------------------------


async def test_login_sets_session_and_csrf_cookies(api):
    api.user("alice")
    response = await login(api)
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "alice"
    assert body["redirect_to"] is None
    cookies = set_cookies(response)
    session, csrf = cookies[SESSION_COOKIE], cookies[CSRF_COOKIE]
    for header in (session, csrf):
        assert "secure" in header and "samesite=strict" in header and "path=/" in header
        assert "max-age=1209600" in header
    assert "httponly" in session and "httponly" not in csrf
    assert cookie_value(response, CSRF_COOKIE) == body["csrf_token"]
    headers = {
        "Cookie": f"{SESSION_COOKIE}={cookie_value(response, SESSION_COOKIE)}",
    }
    me = await api.client.get("/api/v1/me", headers=headers)
    assert me.json()["username"] == "alice"
    assert "auth.login" in actions(api)


@pytest.mark.parametrize("username", ["alice", "nobody"])
async def test_bad_login_is_a_generic_401(api, username):
    api.user("alice")
    response = await login(api, username, "wrong password!")
    assert response.status_code == 401
    assert response.json()["type"].endswith("/invalid-credentials")
    assert "set-cookie" not in response.headers
    with Session(api.engine) as s:
        event = s.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed")).one()
    assert event.target == username
    assert "wrong password" not in str(event.details)


async def test_disabled_user_cannot_log_in(api):
    alice = api.user("alice")
    with Session(api.engine) as s, s.begin():
        s.execute(update(User).where(User.id == alice.id).values(disabled=True))
    response = await login(api)
    assert response.status_code == 401
    assert response.json()["type"].endswith("/invalid-credentials")


# Authorization code + PKCE ----------------------------------------------------------------


async def test_full_pkce_flow(api):
    api.user("alice")
    code, verifier = await code_for(api)
    response = await exchange(api, code, verifier)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    tokens = response.json()
    assert tokens["token_type"] == "Bearer"
    assert tokens["expires_in"] == 900
    assert tokens["refresh_token"].startswith("onr_")
    me = await api.client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["username"] == "alice"
    with Session(api.engine) as s:
        device = s.get(Device, uuid.UUID(tokens["device_id"]))
        assert (device.name, device.platform) == ("Alice's iPhone", "ios")


async def test_authorize_with_a_session_redirects_straight_back(api):
    alice = api.user("alice")
    cookie = await api.cookie(alice)
    verifier, challenge = pkce()
    response = await api.client.get(
        "/api/v1/auth/authorize",
        params=authorize_params(challenge, state="a b&c"),
        headers={"Cookie": cookie["Cookie"]},
    )
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == APPLE["redirect_uri"]
    query = parse_qs(location.query)
    assert query["state"] == ["a b&c"]  # URL-encoded on the way out
    assert (await exchange(api, query["code"][0], verifier)).status_code == 200


@pytest.mark.parametrize(
    "redirect_uri", ["http://127.0.0.1:53682/callback", "http://[::1]:8080/callback"]
)
async def test_cli_clients_use_loopback_redirects(api, redirect_uri):
    api.user("alice")
    code, verifier = await code_for(api, client_id="opennote-cli", redirect_uri=redirect_uri)
    response = await exchange(
        api, code, verifier, client_id="opennote-cli", redirect_uri=redirect_uri
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("client_id", "redirect_uri"),
    [
        ("evil", "opennote://auth/callback"),
        ("opennote-apple", "https://evil.example/callback"),
        ("opennote-apple", "opennote://auth/callback/x"),
        ("opennote-apple", "http://127.0.0.1:8080/callback"),
        ("opennote-cli", "http://127.0.0.1/callback"),
        ("opennote-cli", "http://localhost:8080/callback"),
        ("opennote-cli", "http://127.0.0.1:8080/other"),
        ("opennote-cli", "http://127.0.0.1:8080/callback?x=1"),
        ("opennote-cli", "http://user@127.0.0.1:8080/callback"),
        ("opennote-cli", "https://127.0.0.1:8080/callback"),
    ],
)
async def test_bad_client_or_redirect_is_400_never_a_redirect(api, client_id, redirect_uri):
    _, challenge = pkce()
    response = await api.client.get(
        "/api/v1/auth/authorize",
        params=authorize_params(challenge, client_id=client_id, redirect_uri=redirect_uri),
    )
    assert response.status_code == 400
    assert "location" not in response.headers
    assert response.headers["content-type"] == "application/problem+json"


async def test_plain_challenge_method_is_refused(api):
    _, challenge = pkce()
    response = await api.client.get(
        "/api/v1/auth/authorize", params=authorize_params(challenge, code_challenge_method="plain")
    )
    assert response.status_code == 422
    assert "location" not in response.headers


def assert_grant_error(response, error="invalid_grant", status=400):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"] == error


async def test_wrong_verifier_is_refused_and_spends_the_code(api):
    api.user("alice")
    code, verifier = await code_for(api)
    other, _ = pkce()
    assert_grant_error(await exchange(api, code, other))
    assert_grant_error(await exchange(api, code, verifier))


async def test_code_is_single_use(api):
    api.user("alice")
    code, verifier = await code_for(api)
    assert (await exchange(api, code, verifier)).status_code == 200
    assert_grant_error(await exchange(api, code, verifier))


async def test_expired_code_is_refused(api):
    api.user("alice")
    code, verifier = await code_for(api)
    with Session(api.engine) as s, s.begin():
        s.execute(update(AuthRequest).values(expires_at=dt.datetime.now(dt.UTC)))
    assert_grant_error(await exchange(api, code, verifier))


async def test_code_bound_to_redirect_uri_and_client(api):
    api.user("alice")
    code, verifier = await code_for(api)
    assert_grant_error(await exchange(api, code, verifier, redirect_uri="opennote://other"))
    code, verifier = await code_for(api)
    assert_grant_error(
        await exchange(
            api,
            code,
            verifier,
            client_id="opennote-cli",
            redirect_uri="http://127.0.0.1:1/callback",
        )
    )
    code, verifier = await code_for(api)
    assert_grant_error(await exchange(api, code, verifier, client_id="evil"), "invalid_client", 401)
    assert_grant_error(await exchange(api, "onc_unknown", verifier))


async def test_missing_parameters_are_invalid_request(api):
    response = await api.client.post(
        "/api/v1/auth/token", data={"grant_type": "authorization_code", **APPLE}
    )
    assert_grant_error(response, "invalid_request")
    response = await api.client.post(
        "/api/v1/auth/token", data={"grant_type": "refresh_token", "client_id": "opennote-apple"}
    )
    assert_grant_error(response, "invalid_request")


async def test_login_with_an_unknown_or_spent_auth_request_is_400(api):
    api.user("alice")
    response = await login(api, auth_request=str(uuid.uuid4()))
    assert response.status_code == 400
    response = await login(api, auth_request="not-a-uuid")
    assert response.status_code == 400
    _, challenge = pkce()
    start = await api.client.get("/api/v1/auth/authorize", params=authorize_params(challenge))
    request_id = parse_qs(urlsplit(start.headers["location"]).query)["auth_request"][0]
    assert (await login(api, auth_request=request_id)).status_code == 200
    assert (await login(api, auth_request=request_id)).status_code == 400


async def test_disabled_user_cannot_exchange_a_code(api):
    alice = api.user("alice")
    code, verifier = await code_for(api)
    with Session(api.engine) as s, s.begin():
        s.execute(update(User).where(User.id == alice.id).values(disabled=True))
    assert_grant_error(await exchange(api, code, verifier))


# Refresh rotation --------------------------------------------------------------------------


async def tokens_for(api, username="alice"):
    code, verifier = await code_for(api, username)
    response = await exchange(api, code, verifier)
    assert response.status_code == 200
    return response.json()


async def test_refresh_rotates_on_the_same_device(api):
    api.user("alice")
    first = await tokens_for(api)
    response = await refresh(api, first["refresh_token"])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    second = response.json()
    assert second["device_id"] == first["device_id"]
    assert second["refresh_token"] != first["refresh_token"]
    third = await refresh(api, second["refresh_token"])
    assert third.status_code == 200


async def test_refresh_reuse_revokes_device(api):
    api.user("alice")
    first = await tokens_for(api)
    second = (await refresh(api, first["refresh_token"])).json()
    assert_grant_error(await refresh(api, first["refresh_token"]))  # spent: reuse
    with Session(api.engine) as s:
        assert s.get(Device, uuid.UUID(first["device_id"])).revoked_at is not None
    # The whole device is gone: the newer refresh token and its access token too.
    assert_grant_error(await refresh(api, second["refresh_token"]))
    bearer = {"Authorization": f"Bearer {second['access_token']}"}
    assert (await api.client.get("/api/v1/me", headers=bearer)).status_code == 401
    assert "auth.token_refresh_reuse" in actions(api)


async def test_unknown_or_expired_refresh_token_is_invalid_grant(api):
    api.user("alice")
    tokens = await tokens_for(api)
    assert_grant_error(await refresh(api, "onr_unknown"))
    with Session(api.engine) as s, s.begin():
        s.execute(update(RefreshToken).values(expires_at=dt.datetime.now(dt.UTC)))
    assert_grant_error(await refresh(api, tokens["refresh_token"]))
    assert_grant_error(await refresh(api, tokens["refresh_token"], "evil"), "invalid_client", 401)


# Logout --------------------------------------------------------------------------------------


async def test_logout_ends_the_web_session(api):
    alice = api.user("alice")
    cookie = await api.cookie(alice)
    response = await api.client.post("/api/v1/auth/logout", headers=cookie)
    assert response.status_code == 204
    cleared = set_cookies(response)
    assert "max-age=0" in cleared[SESSION_COOKIE] and "max-age=0" in cleared[CSRF_COOKIE]
    assert (await api.client.get("/api/v1/me", headers=cookie)).status_code == 401
    with Session(api.engine) as s:
        assert s.scalars(select(WebSession.revoked_at)).one() is not None
    assert "auth.logout" in actions(api)


async def test_logout_needs_csrf_with_a_cookie(api):
    alice = api.user("alice")
    cookie = await api.cookie(alice)
    del cookie[CSRF_HEADER]
    assert (await api.client.post("/api/v1/auth/logout", headers=cookie)).status_code == 403


async def test_logout_with_a_bearer_spends_the_refresh_tokens(api):
    api.user("alice")
    tokens = await tokens_for(api)
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await api.client.post("/api/v1/auth/logout", headers=bearer)).status_code == 204
    assert_grant_error(await refresh(api, tokens["refresh_token"]))


# Meta ------------------------------------------------------------------------------------------


async def test_meta_lists_password_login(api):
    assert (await api.client.get("/api/v1/meta")).json()["login_methods"] == ["password"]
