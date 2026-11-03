"""Server metadata (keyless): what a client needs to know before it logs in."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.vaults.paths import PATH_RULES

router = APIRouter()


class ServerMeta(BaseModel):
    server_version: str
    api_versions: list[str]
    sync_protocol_versions: list[int]
    login_methods: list[str]


def app_version() -> str:
    return __version__


@router.get("/api/v1/meta")
async def get_meta() -> ServerMeta:
    """The server version, the API and sync protocol versions, and the login methods."""
    return ServerMeta(
        server_version=app_version(),
        api_versions=["v1"],
        sync_protocol_versions=[1],
        login_methods=[],
    )


@router.get("/api/v1/meta/path-rules")
async def get_path_rules() -> dict[str, object]:
    """The file and folder naming rules every client applies (storage contract §3.2)."""
    return PATH_RULES
