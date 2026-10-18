"""Authentication dependencies; every non-keyless route needs one (CLAUDE.md §12).

Phase 0 has no credential store, so both dependencies reject every request with a 401
problem: deny by default until real token checks exist.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.problems import ProblemError

_bearer = HTTPBearer(auto_error=False)
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


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
) -> Principal:
    """The user or device behind the `Authorization: Bearer` OAuth 2.0 access token."""
    raise _unauthenticated()


async def get_api_key(api_key: Annotated[str | None, Depends(_api_key)]) -> Principal:
    """The automation token owner behind the `X-API-Key` header."""
    raise _unauthenticated()
