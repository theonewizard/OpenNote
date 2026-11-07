"""Login and token endpoints (ADR-0012, API contract §2). All keyless: they are how a
caller gets credentials, protected by PKCE, CSRF state and rate limits instead."""

import datetime as dt
import re
import secrets
import uuid
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

import anyio.to_thread
from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update

from app.api.deps import DB
from app.api.schemas import LoginRequest, LoginResult, TokenResponse
from app.api.schemas import User as UserOut
from app.auth import oidc
from app.auth.crypto import (
    AUTH_REQUEST_SECONDS,
    SESSION_DAYS,
    new_secret,
    pkce_matches,
    secret_hash,
    username_key,
    verify_password,
)
from app.auth.dependencies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    Principal,
    _from_session,
    get_current_principal,
)
from app.auth.models import AuthRequest, Device, RefreshToken, User, WebSession
from app.auth.store import create_device, create_session, issue_device_tokens, now
from app.core.audit import audit
from app.core.config import OidcProvider
from app.core.problems import ProblemError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_REDIRECT: dict[int | str, dict[str, Any]] = {
    302: {"description": "Redirect to the login page, the IdP or the client"}
}

# Public clients known to the server (R-P2-005). The web app itself is `opennote-web`; it
# only comes here to start an upstream OIDC login and lands back on `/`.
APPLE_CLIENT, APPLE_REDIRECT = "opennote-apple", "opennote://auth/callback"
CLI_CLIENT_PREFIX = "opennote-cli"
WEB_CLIENT, WEB_REDIRECT = "opennote-web", "/"
_LOOPBACK = re.compile(r"http://(?:127\.0\.0\.1|\[::1\]):([0-9]{1,5})/callback")
_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")  # RFC 7636 §4.1


def _native_client(client_id: str) -> bool:
    return client_id == APPLE_CLIENT or client_id.startswith(CLI_CLIENT_PREFIX)


def _redirect_allowed(client_id: str, redirect_uri: str) -> bool:
    if client_id == APPLE_CLIENT:
        return redirect_uri == APPLE_REDIRECT
    if client_id == WEB_CLIENT:
        return redirect_uri == WEB_REDIRECT
    if client_id.startswith(CLI_CLIENT_PREFIX):
        match = _LOOPBACK.fullmatch(redirect_uri)
        return match is not None and 0 < int(match[1]) < 65536
    return False


def _bad_request(title: str, slug: str, detail: str) -> ProblemError:
    return ProblemError(400, title, slug, detail)


def _grant_error(error: str, detail: str, status: int = 400) -> ProblemError:
    """RFC 6749 §5.2 error code as the `error` member of an RFC 9457 problem."""
    return ProblemError(
        status,
        error.replace("_", " ").capitalize(),
        error.replace("_", "-"),
        detail,
        extensions={"error": error},
        headers={"Cache-Control": "no-store"},
    )


def _provider(request: Request, name: str) -> OidcProvider:
    for provider in request.app.state.settings.oidc_providers:
        if provider.name == name:
            return provider  # type: ignore[no-any-return]
    raise _bad_request("Unknown provider", "unknown-provider", "No such login provider.")


def _issue_code(auth_request: AuthRequest, user_id: uuid.UUID) -> str:
    """Attach the user, store a single-use code (hashed) and return the client redirect."""
    code = new_secret("onc_")
    auth_request.user_id = user_id
    auth_request.code_hash = secret_hash(code)
    return auth_request.redirect_uri + "?" + urlencode({"code": code, "state": auth_request.state})


async def _start_session(db: DB, response: Response, user: User) -> str:
    """A new web session in both cookies; returns the CSRF token. The caller commits."""
    secret, csrf, _ = await create_session(db, user)
    for name, value, http_only in ((SESSION_COOKIE, secret, True), (CSRF_COOKIE, csrf, False)):
        response.set_cookie(
            name,
            value,
            max_age=SESSION_DAYS * 86400,
            path="/",
            secure=True,
            httponly=http_only,
            samesite="strict",
        )
    return csrf


async def _session_user(db: DB, request: Request) -> uuid.UUID | None:
    secret = request.cookies.get(SESSION_COOKIE)
    if not secret:
        return None
    try:
        return (await _from_session(db, request, secret)).user_id
    except ProblemError:
        return None


@router.get("/authorize", response_class=RedirectResponse, status_code=302, responses=_REDIRECT)
async def authorize(
    request: Request,
    db: DB,
    response_type: Annotated[Literal["code"], Query()],
    client_id: Annotated[str, Query(max_length=255)],
    redirect_uri: Annotated[str, Query(max_length=2048)],
    code_challenge: Annotated[str, Query(min_length=43, max_length=128)],
    code_challenge_method: Annotated[Literal["S256"], Query()],
    state: Annotated[str, Query(max_length=1024)],
    provider: Annotated[
        str | None, Query(max_length=64, description="Log in through this OIDC provider")
    ] = None,
) -> RedirectResponse:
    """OAuth 2.0 authorization endpoint (code + PKCE, S256 only). With a valid session the
    browser goes straight back to `redirect_uri` with `code` and `state`; otherwise to the
    web login page with an `auth_request` id, or to the OIDC provider."""
    # Never redirect anywhere before the client and its redirect URI are known good.
    if not _redirect_allowed(client_id, redirect_uri) or (
        client_id == WEB_CLIENT and provider is None
    ):
        raise _bad_request("Invalid client", "invalid-client", "Unknown client or redirect URI.")
    upstream = _provider(request, provider) if provider else None
    auth_request = AuthRequest(
        id=uuid.uuid7(),
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=state,
        provider=provider,
        expires_at=now() + dt.timedelta(seconds=AUTH_REQUEST_SECONDS),
    )
    db.add(auth_request)
    if upstream is not None:
        config = await anyio.to_thread.run_sync(oidc.discover, upstream)
        auth_request.oidc_state = secrets.token_urlsafe(32)
        auth_request.oidc_nonce = secrets.token_urlsafe(32)
        callback = str(request.url_for("oidc_callback", provider=upstream.name))
        url = oidc.authorization_url(
            config, upstream, callback, auth_request.oidc_state, auth_request.oidc_nonce
        )
    elif (user_id := await _session_user(db, request)) is not None:
        url = _issue_code(auth_request, user_id)
    else:
        url = "/login?" + urlencode({"auth_request": str(auth_request.id)})
    await db.commit()
    return RedirectResponse(url, status_code=302)


async def _pending_request(db: DB, request_id: str) -> AuthRequest | None:
    """A live authorization request no user has completed yet, locked."""
    try:
        key = uuid.UUID(request_id)
    except ValueError:
        return None
    return await db.scalar(
        select(AuthRequest)
        .where(
            AuthRequest.id == key,
            AuthRequest.user_id.is_(None),
            AuthRequest.used_at.is_(None),
            AuthRequest.provider.is_(None),
            AuthRequest.expires_at > now(),
        )
        .with_for_update()
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: DB) -> LoginResult:
    """Local password login. Sets the httpOnly session cookie and the CSRF cookie."""
    pending = None
    if body.auth_request is not None:
        pending = await _pending_request(db, body.auth_request)
        if pending is None:
            raise _bad_request(
                "Invalid authorization request",
                "invalid-auth-request",
                "The authorization request is unknown, expired or already used.",
            )
    user = await db.scalar(select(User).where(User.username_key == username_key(body.username)))
    # verify_password costs the same for an unknown user (a dummy hash).
    valid = await anyio.to_thread.run_sync(
        verify_password, user.password_hash if user else None, body.password
    )
    if user is None or not valid or user.disabled:
        audit(db, request, "auth.login_failed", target=body.username)
        await db.commit()
        raise ProblemError(
            401, "Invalid credentials", "invalid-credentials", "Wrong username or password."
        )
    redirect_to = _issue_code(pending, user.id) if pending else None
    csrf = await _start_session(db, response, user)
    audit(db, request, "auth.login", user_id=user.id, details={"method": "password"})
    await db.commit()
    return LoginResult(
        user=UserOut.model_validate(user, from_attributes=True),
        csrf_token=csrf,
        redirect_to=redirect_to,
    )


@router.post("/token")
async def token(
    request: Request,
    response: Response,
    db: DB,
    grant_type: Annotated[Literal["authorization_code", "refresh_token"], Form()],
    client_id: Annotated[str, Form(max_length=255)],
    code: Annotated[str | None, Form(max_length=512)] = None,
    redirect_uri: Annotated[str | None, Form(max_length=2048)] = None,
    code_verifier: Annotated[str | None, Form(min_length=43, max_length=128)] = None,
    refresh_token: Annotated[str | None, Form(max_length=512)] = None,
    device_name: Annotated[
        str | None, Form(max_length=255, description="Names the device on first exchange")
    ] = None,
    device_platform: Annotated[str | None, Form(max_length=64)] = None,
) -> TokenResponse:
    """OAuth 2.0 token endpoint (RFC 6749 §4.1.3, §6): exchange a code with its PKCE
    verifier, or rotate a refresh token. Reusing a spent refresh token revokes the device."""
    response.headers["Cache-Control"] = "no-store"
    if not _native_client(client_id):
        raise _grant_error("invalid_client", "Unknown client.", 401)
    invalid = _grant_error("invalid_grant", "The grant is invalid, expired or already used.")
    if grant_type == "authorization_code":
        if not (code and redirect_uri and code_verifier):
            raise _grant_error("invalid_request", "code, redirect_uri and code_verifier needed.")
        auth_request = await db.scalar(
            select(AuthRequest).where(AuthRequest.code_hash == secret_hash(code)).with_for_update()
        )
        if auth_request is None or auth_request.user_id is None:
            raise invalid
        fresh = auth_request.used_at is None and auth_request.expires_at > now()
        auth_request.used_at = auth_request.used_at or now()
        await db.commit()  # a presented code is spent, whatever happens next
        if (
            not fresh
            or auth_request.client_id != client_id
            or auth_request.redirect_uri != redirect_uri
            or not _VERIFIER.fullmatch(code_verifier)
            or not pkce_matches(code_verifier, auth_request.code_challenge)
        ):
            raise invalid
        user = await db.get(User, auth_request.user_id)
        if user is None or user.disabled:
            raise invalid
        device = await create_device(db, user.id, device_name or client_id, device_platform)
    else:
        if not refresh_token:
            raise _grant_error("invalid_request", "refresh_token needed.")
        row = await db.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == secret_hash(refresh_token))
            .with_for_update()
        )
        found = await db.get(Device, row.device_id) if row else None
        if row is None or found is None:
            raise invalid
        device = found
        if row.used_at is not None:  # reuse: someone holds a copy, so the device goes
            if device.revoked_at is None:
                device.revoked_at = now()
                audit(
                    db,
                    request,
                    "auth.token_refresh_reuse",
                    user_id=device.user_id,
                    target=str(device.id),
                )
                await db.commit()
            raise invalid
        user = await db.get(User, device.user_id)
        if row.expires_at <= now() or device.revoked_at is not None or not user or user.disabled:
            raise invalid
        row.used_at = now()
    access, expires_in, refresh = await issue_device_tokens(db, device)
    await db.commit()
    return TokenResponse(
        access_token=access,
        token_type="Bearer",  # noqa: S106 (the token type, not a secret)
        expires_in=expires_in,
        refresh_token=refresh,
        device_id=device.id,
    )


@router.get(
    "/oidc/{provider}/callback",
    response_class=RedirectResponse,
    status_code=302,
    responses=_REDIRECT,
)
async def oidc_callback(
    request: Request,
    db: DB,
    provider: str,
    code: Annotated[str, Query(max_length=2048)],
    state: Annotated[str, Query(max_length=1024)],
) -> RedirectResponse:
    """Redirect target of an upstream OIDC provider: signs the user in (creating the
    account on first login) and continues the pending authorization request."""
    upstream = _provider(request, provider)
    auth_request = await db.scalar(
        select(AuthRequest)
        .where(
            AuthRequest.oidc_state == state,
            AuthRequest.provider == provider,
            AuthRequest.user_id.is_(None),
            AuthRequest.used_at.is_(None),
            AuthRequest.expires_at > now(),
        )
        .with_for_update()
    )
    if auth_request is None or auth_request.oidc_nonce is None:
        raise _bad_request("Invalid state", "invalid-oidc-state", "Start the login again.")
    nonce = auth_request.oidc_nonce
    auth_request.oidc_state = None  # one attempt per state
    await db.commit()
    callback = str(request.url_for("oidc_callback", provider=upstream.name))
    claims = await anyio.to_thread.run_sync(oidc.id_token_claims, upstream, code, callback, nonce)
    user = await _oidc_user(db, upstream, claims)
    if user.disabled:
        raise ProblemError(401, "Invalid credentials", "invalid-credentials", "Account disabled.")
    if auth_request.client_id == WEB_CLIENT:
        auth_request.used_at = now()
        url = WEB_REDIRECT
    else:
        url = _issue_code(auth_request, user.id)
    redirect = RedirectResponse(url, status_code=302)
    await _start_session(db, redirect, user)
    audit(db, request, "auth.oidc_login", user_id=user.id, details={"provider": provider})
    await db.commit()
    return redirect


async def _oidc_user(db: DB, provider: OidcProvider, claims: dict[str, Any]) -> User:
    """The user with this (issuer, subject), created on first login; never matched by
    e-mail. The username is `preferred_username` or the subject, made unique."""
    subject = str(claims["sub"])
    user = await db.scalar(
        select(User).where(User.oidc_issuer == provider.issuer, User.oidc_subject == subject)
    )
    if user is not None:
        return user
    base = str(claims.get("preferred_username") or subject)[:200]
    name, n = base, 1
    while await db.scalar(select(User.id).where(User.username_key == username_key(name))):
        n += 1
        name = f"{base}-{n}"
    email, display = claims.get("email"), claims.get("name")
    user = User(
        username=name,
        username_key=username_key(name),
        display_name=str(display)[:255] if display else name,
        email=email if isinstance(email, str) else None,
        oidc_issuer=provider.issuer,
        oidc_subject=subject,
    )
    db.add(user)
    await db.flush()
    return user


@router.post("/logout", status_code=204)
async def logout(
    principal: Annotated[Principal, Depends(get_current_principal)],
    request: Request,
    response: Response,
    db: DB,
) -> None:
    """End the web session, or revoke the calling device's refresh tokens."""
    if principal.session_id is not None:
        await db.execute(
            update(WebSession).where(WebSession.id == principal.session_id).values(revoked_at=now())
        )
        for name, http_only in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
            response.delete_cookie(
                name, path="/", secure=True, httponly=http_only, samesite="strict"
            )
    elif principal.kind == "device":
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.device_id == uuid.UUID(principal.device_id),
                RefreshToken.used_at.is_(None),
            )
            .values(used_at=now())
        )
    audit(db, request, "auth.logout", principal)
    await db.commit()
