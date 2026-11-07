"""Upstream OpenID Connect login (R-P2-006): discovery, the code exchange and the ID token
check, with the standard library and PyJWKClient. Blocking: call from a worker thread."""

import base64
import hmac
import json
import urllib.request
from typing import Any
from urllib.parse import quote_plus, urlencode

import jwt

from app.core.config import OidcProvider
from app.core.problems import ProblemError

TIMEOUT_SECONDS = 10
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "ES256", "ES384", "EdDSA"]


def _failed() -> ProblemError:
    return ProblemError(
        401, "Login failed", "oidc-failed", "The identity provider's answer was not accepted."
    )


def _get_json(request: str | urllib.request.Request) -> dict[str, Any]:
    # Only http(s): the issuer is checked in settings, the endpoints by discover().
    url = request if isinstance(request, str) else request.full_url
    if not url.startswith(("https://", "http://")):
        raise ValueError("not an http(s) URL")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310
        body = json.load(response)
    if not isinstance(body, dict):
        raise ValueError("not a JSON object")
    return body


def discover(provider: OidcProvider) -> dict[str, Any]:
    """The provider's metadata; its endpoints must be https (or under a local http issuer),
    so a tampered document cannot send us to file: or plain-text URLs."""
    url = provider.issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        config = _get_json(url)
        endpoints = [config[k] for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")]
    except OSError, ValueError, KeyError:
        config, endpoints = {}, []
    trusted = ("https://", provider.issuer.rstrip("/") + "/")
    if (
        config.get("issuer") != provider.issuer
        or not endpoints
        or not all(isinstance(e, str) and e.startswith(trusted) for e in endpoints)
    ):
        raise ProblemError(
            502, "Identity provider unavailable", "oidc-unavailable", "Try again later."
        )
    return config


def authorization_url(
    config: dict[str, Any], provider: OidcProvider, redirect_uri: str, state: str, nonce: str
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
        }
    )
    endpoint: str = config["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + query


def id_token_claims(
    provider: OidcProvider, code: str, redirect_uri: str, nonce: str
) -> dict[str, Any]:
    """Exchange the code (client_secret_basic) and return the checked ID token's claims:
    signature by the provider's JWKS, `iss`, `aud`, `exp`, `nonce`."""
    config = discover(provider)
    credentials = f"{quote_plus(provider.client_id)}:{quote_plus(provider.client_secret)}"
    request = urllib.request.Request(  # noqa: S310 (endpoint checked by discover)
        config["token_endpoint"],
        data=urlencode(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        ).encode(),
        headers={
            "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
            "Accept": "application/json",
        },
    )
    try:
        id_token = _get_json(request)["id_token"]
        key = jwt.PyJWKClient(config["jwks_uri"], timeout=TIMEOUT_SECONDS)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key.get_signing_key_from_jwt(id_token).key,
            algorithms=_ALGORITHMS,
            audience=provider.client_id,
            issuer=provider.issuer,
            options={"require": ["exp", "sub", "nonce"]},
        )
    except OSError, ValueError, KeyError, TypeError, jwt.PyJWTError:
        raise _failed() from None
    if not hmac.compare_digest(str(claims["nonce"]).encode(), nonce.encode()):
        raise _failed()
    return claims
