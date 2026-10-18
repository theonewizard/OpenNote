"""Server metadata (keyless): what a client needs to know before it logs in."""

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__

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
    return ServerMeta(
        server_version=app_version(),
        api_versions=["v1"],
        sync_protocol_versions=[1],
        login_methods=[],
    )
