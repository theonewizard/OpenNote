"""Evernote ENEX import (P6-10): one upload, one note per `<note>`, attachments beside it.

Each note and attachment is an ordinary create on the commit path, so the vault, history,
index and sync see them like any other new file. Notes land in `folder`, attachments in
`folder/_resources/<note>.resources/` (Obsidian Importer's layout), and embeds use the
attachment's vault path so names that repeat across notes stay unambiguous."""

import hashlib
import json
import posixpath
import uuid
from collections.abc import Iterator
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.attachments import _UploadRoute
from app.api.deps import DB, commit, require_vault
from app.api.notes import _initial_content, live_file_at, ok
from app.api.schemas import ImportResult, ImportSkip, NoteRef
from app.auth.dependencies import Principal, get_caller
from app.core.audit import audit
from app.core.problems import ProblemError
from app.imports.enex import EnexError, EnexNote, read_enex, safe_name, to_markdown
from app.sync.commit import Create
from app.vaults.models import Vault
from app.vaults.paths import normalize, validate
from app.vaults.scan import MAX_NOTE_BYTES

router = APIRouter(prefix="/api/v1/imports", tags=["imports"], route_class=_UploadRoute)
Caller = Annotated[Principal, Depends(get_caller)]


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


async def _free_path(db: DB, vault_id: uuid.UUID, path: str, taken: set[str]) -> str:
    """`path`, or `name 2.ext`, `name 3.ext` ... for the first one no file has."""
    stem, ext = posixpath.splitext(path)
    candidate, n = path, 1
    while candidate.casefold() in taken or await live_file_at(db, vault_id, candidate):
        n += 1
        candidate = f"{stem} {n}{ext}"
    taken.add(candidate.casefold())
    return candidate


def _frontmatter(note: EnexNote) -> str:
    """Evernote's metadata as YAML; strings are JSON-quoted, which YAML reads as is."""
    lines = []
    tags = [t.replace(" ", "-").lstrip("#") for t in note.tags]
    if tags := [t for t in tags if t]:
        lines.append("tags: [" + ", ".join(json.dumps(t, ensure_ascii=False) for t in tags) + "]")
    for key, value in (("created", note.created), ("updated", note.updated)):
        if value is not None:
            lines.append(f"{key}: {value.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if note.source_url:
        lines.append(f"source: {json.dumps(note.source_url, ensure_ascii=False)}")
    return "---\n" + "".join(line + "\n" for line in lines) + "---\n" if lines else ""


@router.post("/enex")
async def import_enex(
    request: Request,
    caller: Caller,
    db: DB,
    vault_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File(description="An Evernote export (.enex)")],
    folder: Annotated[str, Form(min_length=1, max_length=512)] = "Evernote",
) -> ImportResult:
    """Import every note of an ENEX export into `folder` (R-P6-011). A note that cannot be
    written is listed in `skipped`; the others are imported."""
    vault, _ = await require_vault(db, caller, vault_id, "editor")
    folder = normalize(folder.strip("/"))
    if validate(folder, note=False):
        raise ProblemError(
            422, "Invalid path", "invalid-path", "The folder breaks the vault's path rules."
        )
    notes: Iterator[EnexNote] = read_enex(file.file)
    imported: list[NoteRef] = []
    skipped: list[ImportSkip] = []
    attachments = 0
    taken: set[str] = set()
    while True:
        try:
            note = await anyio.to_thread.run_sync(next, notes, None)
        except EnexError:
            if not imported and not skipped:
                raise ProblemError(
                    422, "Invalid ENEX", "invalid-enex", "The file is not an Evernote export."
                ) from None
            skipped.append(ImportSkip(title="", reason="The rest of the file is not valid ENEX."))
            break
        if note is None:
            break
        written = await _import_note(request, db, caller, vault, folder, note, taken)
        if isinstance(written, ImportSkip):
            skipped.append(written)
        else:
            imported.append(written[0])
            attachments += written[1]
    audit(
        db,
        request,
        "import.enex",
        caller,
        vault_id=vault.id,
        details={"folder": folder, "notes": len(imported), "skipped": len(skipped)},
    )
    await db.commit()
    return ImportResult(notes=imported, attachments=attachments, skipped=skipped)


async def _import_note(
    request: Request,
    db: DB,
    caller: Principal,
    vault: Vault,
    folder: str,
    note: EnexNote,
    taken: set[str],
) -> tuple[NoteRef, int] | ImportSkip:
    title = note.title or "Untitled"
    name = safe_name(title, "Untitled")
    media: dict[str, str] = {}
    count = 0
    for resource in note.resources:
        if len(resource.data) > request.app.state.settings.max_blob_bytes:
            continue
        leaf = safe_name(
            resource.file_name, f"attachment{posixpath.splitext(resource.file_name)[1]}"
        )
        if leaf.lower().endswith(".md"):
            leaf += ".txt"  # an attached .md file stays an attachment, not a note
        path = await _free_path(db, vault.id, f"{folder}/_resources/{name}.resources/{leaf}", taken)
        op = Create(uuid.uuid7(), uuid.uuid7(), path, "attachment", _sha(resource.data))
        result = await commit(request, vault, op, caller.device_id, resource.data)
        if ok(result) or result.status == "conflict":
            media.setdefault(resource.md5, result.path or path)
            count += 1
    path = await _free_path(db, vault.id, f"{folder}/{name}.md", taken)
    file_id = uuid.uuid7()
    data = _initial_content(_frontmatter(note) + to_markdown(note.enml, media), file_id)
    if len(data) > MAX_NOTE_BYTES:
        return ImportSkip(title=title, reason="The note is larger than 16 MiB.")
    result = await commit(
        request,
        vault,
        Create(uuid.uuid7(), file_id, path, "note", _sha(data)),
        caller.device_id,
        data,
    )
    if not ok(result) and result.status != "conflict":
        return ImportSkip(title=title, reason="The note could not be written.")
    final = result.path or path
    return NoteRef(id=result.file_id, path=final, title=title), count
