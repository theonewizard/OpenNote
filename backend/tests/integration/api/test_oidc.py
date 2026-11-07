"""Upstream OIDC login against a fake issuer served over real HTTP on 127.0.0.1, with a
key generated here (R-P2-006)."""

import base64
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.main import create_app
from app.auth.dependencies import SESSION_COOKIE
from app.auth.models import User
from app.core.config import Settings
from tests.integration.api.conftest import Api
from tests.integration.api.test_auth_flows import cookie_value, exchange, pkce, set_cookies
from tests.integration.conftest import serve

pytestmark = pytest.mark.anyio

CLIENT_ID, CLIENT_SECRET = "opennote-test", "fake-client-secret"


class FakeIssuer:
    """Discovery, JWKS and a token endpoint. `codes` maps an upstream code to the claims
    its ID token will carry."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.codes: dict[str, dict[str, Any]] = {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        issuer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _json(self, status: int, body: dict[str, Any]) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/.well-known/openid-configuration":
                    self._json(
                        200,
                        {
                            "issuer": issuer.url,
                            "authorization_endpoint": issuer.url + "/authorize",
                            "token_endpoint": issuer.url + "/token",
                            "jwks_uri": issuer.url + "/jwks",
                        },
                    )
                elif self.path == "/jwks":
                    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(issuer.key.public_key()))
                    self._json(200, {"keys": [jwk | {"kid": "k1", "use": "sig", "alg": "RS256"}]})
                else:
                    self._json(404, {})

            def do_POST(self) -> None:
                length = int(self.headers["Content-Length"])
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
                basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                claims = issuer.codes.pop(form.get("code", ""), None)
                if self.headers.get("Authorization") != f"Basic {basic}" or claims is None:
                    self._json(400, {"error": "invalid_grant"})
                    return
                id_token = jwt.encode(claims, issuer.key, "RS256", headers={"kid": "k1"})
                self._json(200, {"access_token": "x", "token_type": "Bearer", "id_token": id_token})

        return Handler

    def claims(self, nonce: str, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        claims = {
            "iss": self.url,
            "aud": CLIENT_ID,
            "sub": "subject-1",
            "nonce": nonce,
            "iat": now,
            "exp": now + 300,
            "preferred_username": "olivia",
            "email": "olivia@example.org",
        }
        return {k: v for k, v in (claims | overrides).items() if v is not None}


@pytest.fixture
def issuer() -> Iterator[FakeIssuer]:
    fake = FakeIssuer()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture
async def oidc_api(
    engine: Engine, make_settings: Callable[..., Settings], issuer: FakeIssuer
) -> AsyncIterator[Api]:
    provider = {
        "name": "fake",
        "issuer": issuer.url,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    settings = make_settings(oidc_providers=[provider])
    app = create_app(settings)
    async with serve(app) as client:
        yield Api(app, client, engine, settings)


async def start(api: Api, client: str = "opennote-apple") -> tuple[str, str, str]:
    """authorize?provider=fake; return (upstream state, nonce, PKCE verifier)."""
    verifier, challenge = pkce()
    redirect = "/" if client == "opennote-web" else "opennote://auth/callback"
    params = {
        "response_type": "code",
        "client_id": client,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "client-state",
        "provider": "fake",
    }
    response = await api.client.get("/api/v1/auth/authorize", params=params)
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    query = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert location.path == "/authorize"
    assert query["client_id"] == CLIENT_ID and query["response_type"] == "code"
    assert "openid" in query["scope"].split()
    assert query["redirect_uri"].endswith("/api/v1/auth/oidc/fake/callback")
    return query["state"], query["nonce"], verifier


async def callback(api: Api, issuer: FakeIssuer, state: str, claims: dict[str, Any]):
    issuer.codes["upstream-code"] = claims
    return await api.client.get(
        "/api/v1/auth/oidc/fake/callback", params={"code": "upstream-code", "state": state}
    )


async def test_oidc_login_for_a_native_client(oidc_api, issuer):
    state, nonce, verifier = await start(oidc_api)
    response = await callback(oidc_api, issuer, state, issuer.claims(nonce))
    assert response.status_code == 302, response.text
    assert SESSION_COOKIE in set_cookies(response)
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "opennote://auth/callback"
    query = parse_qs(location.query)
    assert query["state"] == ["client-state"]
    tokens = (await exchange(oidc_api, query["code"][0], verifier)).json()
    me = await oidc_api.client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.json()["username"] == "olivia"
    assert me.json()["email"] == "olivia@example.org"
    with Session(oidc_api.engine) as s:
        user = s.scalars(select(User)).one()
        assert (user.oidc_issuer, user.oidc_subject) == (issuer.url, "subject-1")
        assert user.password_hash is None


async def test_oidc_web_login_lands_on_the_app(oidc_api, issuer):
    state, nonce, _ = await start(oidc_api, "opennote-web")
    response = await callback(oidc_api, issuer, state, issuer.claims(nonce))
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    session = cookie_value(response, SESSION_COOKIE)
    me = await oidc_api.client.get("/api/v1/me", headers={"Cookie": f"{SESSION_COOKIE}={session}"})
    assert me.json()["username"] == "olivia"


async def test_users_are_matched_on_issuer_and_subject_not_email(oidc_api, issuer):
    oidc_api.user("olivia")  # a local account with the same name
    state, nonce, _ = await start(oidc_api, "opennote-web")
    assert (await callback(oidc_api, issuer, state, issuer.claims(nonce))).status_code == 302
    state, nonce, _ = await start(oidc_api, "opennote-web")
    assert (await callback(oidc_api, issuer, state, issuer.claims(nonce))).status_code == 302
    state, nonce, _ = await start(oidc_api, "opennote-web")
    other = issuer.claims(nonce, sub="subject-2", preferred_username=None)
    assert (await callback(oidc_api, issuer, state, other)).status_code == 302
    with Session(oidc_api.engine) as s:
        users = {u.username: u.oidc_subject for u in s.scalars(select(User))}
    assert users == {"olivia": None, "olivia-2": "subject-1", "subject-2": "subject-2"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "wrong"},
        {"aud": "someone-else"},
        {"iss": "http://127.0.0.1:1"},
        {"exp": int(time.time()) - 60},
        {"sub": None},
    ],
)
async def test_bad_id_token_is_refused(oidc_api, issuer, overrides):
    state, nonce, _ = await start(oidc_api)
    response = await callback(oidc_api, issuer, state, issuer.claims(nonce) | overrides)
    assert response.status_code in (400, 401), response.text
    assert "location" not in response.headers
    assert "set-cookie" not in response.headers
    with Session(oidc_api.engine) as s:
        assert s.scalars(select(User)).all() == []


async def test_unknown_or_replayed_state_is_refused(oidc_api, issuer):
    state, nonce, _ = await start(oidc_api)
    assert (await callback(oidc_api, issuer, "made-up", issuer.claims(nonce))).status_code == 400
    assert (await callback(oidc_api, issuer, state, issuer.claims(nonce))).status_code == 302
    assert (await callback(oidc_api, issuer, state, issuer.claims(nonce))).status_code == 400


async def test_unknown_provider_is_400(oidc_api):
    _, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": "opennote-apple",
        "redirect_uri": "opennote://auth/callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "s",
        "provider": "nope",
    }
    response = await oidc_api.client.get("/api/v1/auth/authorize", params=params)
    assert response.status_code == 400
    assert "location" not in response.headers


async def test_meta_lists_the_provider(oidc_api):
    meta = (await oidc_api.client.get("/api/v1/meta")).json()
    assert meta["login_methods"] == ["password", "fake"]


def test_provider_settings(make_settings, monkeypatch, tmp_path):
    from app.core.config import SettingsError

    with pytest.raises(ValueError, match="https"):
        make_settings(
            oidc_providers=[
                {
                    "name": "x",
                    "issuer": "http://idp.example",
                    "client_id": "c",
                    "client_secret": "s",
                }
            ]
        )
    with pytest.raises(SettingsError, match="oidc_corp_idp_client_secret"):
        make_settings(
            oidc_providers=[{"name": "corp-idp", "issuer": "https://i", "client_id": "c"}]
        )
    secret = tmp_path / "secret"
    secret.write_text("from-file\n")
    monkeypatch.setenv("OPENNOTE_OIDC_CORP_IDP_CLIENT_SECRET_FILE", str(secret))
    settings = make_settings(
        oidc_providers=[{"name": "corp-idp", "issuer": "https://i/", "client_id": "c"}]
    )
    provider = settings.oidc_providers[0]
    assert (provider.issuer, provider.client_secret) == ("https://i/", "from-file")
    assert "from-file" not in repr(settings)
