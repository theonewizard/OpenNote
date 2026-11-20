"""Web clipping (P6-04): the browser extension sends a page's HTML, the server turns it
into a Markdown note in the vault's clippings folder (R-P6-016).

Conversion runs server-side with the same HTML-to-Markdown converter as the ENEX import,
so the extension needs no libraries. Images stay remote links; scripts, forms and media
elements are dropped; only http(s) and mailto links survive."""

import datetime as dt
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.conventions import etag
from app.api.deps import DB, commit, require_vault
from app.api.imports import _free_path, _sha
from app.api.notes import _initial_content, _load, ok, refused
from app.api.schemas import ClipCreate, Note
from app.auth.dependencies import Principal, get_caller
from app.core.problems import ProblemError
from app.imports.enex import safe_name, to_markdown
from app.sync.commit import Create
from app.vaults.paths import normalize, validate
from app.vaults.scan import MAX_NOTE_BYTES

router = APIRouter(prefix="/api/v1/clips", tags=["clips"])
Caller = Annotated[Principal, Depends(get_caller)]


def _clip_text(body: ClipCreate, now: dt.datetime) -> str:
    tags = ["clippings", *(t.strip().lstrip("#").replace(" ", "-") for t in body.tags)]
    tags = list(dict.fromkeys(t for t in tags if t))
    header = [
        "---",
        f"title: {json.dumps(body.title or body.url, ensure_ascii=False)}",
        f"source: {json.dumps(body.url, ensure_ascii=False)}",
        f"created: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]",
        "---",
        "",
    ]
    return "\n".join(header) + to_markdown(body.html, {}, body.url)


@router.post("", status_code=201, response_model=Note, responses={201: {"description": "Created"}})
async def create_clip(body: ClipCreate, request: Request, caller: Caller, db: DB) -> JSONResponse:
    """Save a clipped page as a note in `folder` (default `Clippings`). A personal access
    token with write scope for the vault works, which is what the extension uses."""
    vault, _ = await require_vault(db, caller, body.vault_id, "editor")
    folder = normalize(body.folder.strip("/"))
    if validate(folder, note=False):
        raise ProblemError(
            422, "Invalid path", "invalid-path", "The folder breaks the vault's path rules."
        )
    name = safe_name(body.title, "Clipping")
    path = await _free_path(db, vault.id, f"{folder}/{name}.md", set())
    file_id = uuid.uuid7()
    data = _initial_content(_clip_text(body, dt.datetime.now(dt.UTC)), file_id)
    if len(data) > MAX_NOTE_BYTES:
        raise ProblemError(
            413, "Content too large", "content-too-large", "Note content is limited to 16 MiB."
        )
    result = await commit(
        request,
        vault,
        Create(uuid.uuid7(), file_id, path, "note", _sha(data)),
        caller.device_id,
        data,
    )
    if not ok(result) and result.status != "conflict":
        raise refused(result)
    _, _, note = await _load(db, caller, result.file_id, "viewer")
    return JSONResponse(
        note.model_dump(mode="json"),
        status_code=201,
        headers={"ETag": etag(note.revision), "Location": f"/api/v1/notes/{note.id}"},
    )
