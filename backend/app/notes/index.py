"""The derived note index: titles, properties, tags and links, rebuildable from the vault.

Only `notes`, `note_tags` and `note_links` are written here; `files` (identity) is read.
"""

import os
import posixpath
import uuid
from pathlib import Path

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.notes.document import parse_note
from app.notes.extract import Link, extract
from app.notes.frontmatter import read_properties
from app.notes.links import resolve
from app.notes.models import File, Note, NoteLink, NoteTag
from app.vaults.fsio import open_root, read_file
from app.vaults.paths import casefold_key

BATCH = 500


def index_file(
    session: Session, vault_id: uuid.UUID, file_id: uuid.UUID, raw: bytes, path: str
) -> None:
    """Replace the derived rows of one note, then re-resolve the links this note could
    now satisfy (unresolved ones, and ones resolved to a file with the same name)."""
    _write_rows(session, file_id, raw, path)
    session.flush()
    leaf = casefold_key(posixpath.basename(path))
    same_name = select(File.file_id).where(
        File.vault_id == vault_id, func.regexp_replace(File.path_key, "^.*/", "") == leaf
    )
    _resolve_links(
        session,
        vault_id,
        or_(
            NoteLink.file_id == file_id,
            NoteLink.resolved_file_id.is_(None),
            NoteLink.resolved_file_id.in_(same_name),
        ),
    )


def rebuild_index(session: Session, vault_id: uuid.UUID, root: Path) -> None:
    """Drop and recreate the derived rows of every live note, reading it from disk."""
    vault_files = select(File.file_id).where(File.vault_id == vault_id)
    for model in (NoteLink, NoteTag, Note):
        session.execute(delete(model).where(model.file_id.in_(vault_files)))
    live_notes = (
        select(File.file_id, File.path)
        .where(File.vault_id == vault_id, File.kind == "note", ~File.deleted)
        .order_by(File.path)
    )
    root_fd = open_root(root)
    try:
        last = ""
        while batch := session.execute(live_notes.where(File.path > last).limit(BATCH)).all():
            for file_id, path in batch:
                _write_rows(session, file_id, read_file(root_fd, path), path)
            session.flush()
            last = batch[-1].path
    finally:
        os.close(root_fd)
    _resolve_links(session, vault_id, NoteLink.file_id.in_(vault_files))


def _write_rows(session: Session, file_id: uuid.UUID, raw: bytes, path: str) -> None:
    for model in (NoteLink, NoteTag, Note):
        session.execute(delete(model).where(model.file_id == file_id))
    doc = parse_note(raw)
    props, error = read_properties(doc)
    title = props.get("title") if props else None
    if not isinstance(title, str) or not title.strip():
        title = posixpath.basename(path).rsplit(".", 1)[0]
    session.add(
        Note(
            file_id=file_id,
            title=title,
            properties=props,
            frontmatter_error=error,
            read_only=doc.text is None,
        )
    )
    found = extract(doc)
    tags = [t for t in (props or {}).get("tags") or [] if isinstance(t, str)] + found.tags
    seen: set[str] = set()
    for tag in (t.strip().lstrip("#") for t in tags):
        if tag and (key := casefold_key(tag)) not in seen:
            seen.add(key)
            session.add(NoteTag(file_id=file_id, tag=tag, tag_key=key))
    for ordinal, link in enumerate(found.links):
        session.add(
            NoteLink(
                file_id=file_id,
                ordinal=ordinal,
                target=link.target,
                embed=link.embed,
                heading=link.heading,
                block=link.block,
                alias=link.alias,
            )
        )


def _resolve_links(session: Session, vault_id: uuid.UUID, which: ColumnElement[bool]) -> None:
    live = dict(
        session.execute(
            select(File.path, File.file_id).where(File.vault_id == vault_id, ~File.deleted)
        ).all()
    )
    paths = list(live)
    rows = session.execute(
        select(NoteLink.file_id, NoteLink.ordinal, NoteLink.target, File.path)
        .join(File, File.file_id == NoteLink.file_id)
        .where(File.vault_id == vault_id, which)
    ).all()
    for file_id, ordinal, target, from_path in rows:
        link = Link(target, None, None, None, embed=False, markdown=False)
        hit = resolve(link, from_path, paths)
        session.execute(
            update(NoteLink)
            .where(NoteLink.file_id == file_id, NoteLink.ordinal == ordinal)
            .values(resolved_file_id=live.get(hit) if hit else None)
        )


def remove_file(session: Session, file_id: uuid.UUID) -> None:
    """Drop the derived rows of a deleted file; links to it become unresolved."""
    for model in (NoteLink, NoteTag, Note):
        session.execute(delete(model).where(model.file_id == file_id))
    session.execute(
        update(NoteLink).where(NoteLink.resolved_file_id == file_id).values(resolved_file_id=None)
    )
