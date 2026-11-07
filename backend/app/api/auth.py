"""Login and token endpoints (ADR-0012, API contract §2). All keyless: they are how a
caller gets credentials, protected by PKCE, CSRF state and rate limits instead."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import RedirectResponse

from app.api.http import not_implemented
from app.api.schemas import LoginRequest, LoginResult, TokenResponse
from app.auth.dependencies import Principal, get_current_principal

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_REDIRECT: dict[int | str, dict[str, Any]] = {
    302: {"description": "Redirect to the login page, the IdP or the client"}
}


@router.get("/authorize", response_class=RedirectResponse, status_code=302, responses=_REDIRECT)
async def authorize(
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
    raise not_implemented()


@router.post("/login")
async def login(body: LoginRequest) -> LoginResult:
    """Local password login. Sets the httpOnly session cookie and the CSRF cookie."""
    raise not_implemented()


@router.post("/token")
async def token(
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
    raise not_implemented()


@router.get(
    "/oidc/{provider}/callback",
    response_class=RedirectResponse,
    status_code=302,
    responses=_REDIRECT,
)
async def oidc_callback(
    provider: str,
    code: Annotated[str, Query(max_length=2048)],
    state: Annotated[str, Query(max_length=1024)],
) -> RedirectResponse:
    """Redirect target of an upstream OIDC provider: signs the user in (creating the
    account on first login) and continues the pending authorization request."""
    raise not_implemented()


@router.post("/logout", status_code=204)
async def logout(principal: Annotated[Principal, Depends(get_current_principal)]) -> None:
    """End the web session, or revoke the calling device's refresh tokens."""
    raise not_implemented()
