"""Authentication dependencies; every non-keyless route needs one (CLAUDE.md §12).

Until the credential store lands (Phase 2, P2-02) every dependency rejects every request
with a 401 problem: deny by default until real token checks exist.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from fastapi.security import APIKeyCookie, APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.problems import ProblemError

SESSION_COOKIE = "opennote_session"
CSRF_COOKIE = "opennote_csrf"

_bearer = HTTPBearer(auto_error=False)
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)
_session = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="Web session (httpOnly). Mutating requests also need `X-CSRF-Token`.",
)


@dataclass(frozen=True)
class Principal:
    id: str
    kind: Literal["user", "device", "api_key"]


def _unauthenticated() -> ProblemError:
    return ProblemError(
        401, "Authentication required", "unauthenticated", "Valid credentials are required."
    )


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[str | None, Depends(_session)],
) -> Principal:
    """The user or device behind an OAuth 2.0 access token (`Authorization: Bearer`) or
    the web session cookie."""
    raise _unauthenticated()


async def get_api_key(api_key: Annotated[str | None, Depends(_api_key)]) -> Principal:
    """The automation token owner behind the `X-API-Key` header."""
    raise _unauthenticated()


async def get_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[str | None, Depends(_session)],
    api_key: Annotated[str | None, Depends(_api_key)],
) -> Principal:
    """Whoever is calling, by any of the three credentials; for the vault-scoped routes a
    personal access token may also reach (the token's vaults and scope still apply)."""
    raise _unauthenticated()
