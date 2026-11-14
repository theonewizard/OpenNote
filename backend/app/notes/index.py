"""The derived note index: titles, properties, tags and links, rebuildable from the vault.

Only `notes`, `note_tags`, `note_links` and `search_documents` are written here; `files`
(identity) is read.
"""

import os
import posixpath
import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy import ARRAY, ColumnElement, Text, any_, delete, func, literal, or_, select, update
from sqlalchemy.orm import Session

from app.notes.document import parse_note
from app.notes.extract import Link, extract
from app.notes.frontmatter import read_properties
from app.notes.links import name_keys, resolve, target_key
from app.notes.models import File, Note, NoteLink, NoteTag, SearchDocument
from app.vaults.fsio import open_root, read_file
from app.vaults.paths import casefold_key

BATCH = 500
# The derived rows of one file, dropped and rewritten together.
DERIVED = (NoteLink, NoteTag, SearchDocument, Note)
# A tsvector holds at most 1 MiB of lexemes; text past this is not searchable.
MAX_SEARCH_CHARS = 200_000


def index_file(
    session: Session, vault_id: uuid.UUID, file_id: uuid.UUID, raw: bytes, path: str
) -> None:
    """Replace the derived rows of one note, resolve its links, then re-resolve the links
    of other notes this file can change (`relink`)."""
    _write_rows(session, vault_id, file_id, raw, path)
    session.flush()
    _resolve_links(session, vault_id, NoteLink.file_id == file_id)
    relink(session, vault_id, file_id, path)


def relink(session: Session, vault_id: uuid.UUID, file_id: uuid.UUID, path: str | None) -> None:
    """Re-resolve the links a commit of `file_id` can change: those that point at it now
    (it moved or, with `path` None, was deleted) and those naming its file name at
    `path` (it may now be their best match). No other link's answer depends on it."""
    which = NoteLink.resolved_file_id == file_id
    if path is not None:
        which = or_(which, NoteLink.target_key.in_(name_keys(path)), NoteLink.target_key.is_(None))
    _resolve_links(session, vault_id, which)


def rebuild_index(session: Session, vault_id: uuid.UUID, root: Path) -> None:
    """Drop and recreate the derived rows of every live note, reading it from disk."""
    vault_files = select(File.file_id).where(File.vault_id == vault_id)
    for model in DERIVED:
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
                _write_rows(session, vault_id, file_id, read_file(root_fd, path), path)
            session.flush()
            last = batch[-1].path
    finally:
        os.close(root_fd)
    _resolve_links(session, vault_id, NoteLink.file_id.in_(vault_files))


def _write_rows(
    session: Session, vault_id: uuid.UUID, file_id: uuid.UUID, raw: bytes, path: str
) -> None:
    for model in DERIVED:
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
    seen: dict[str, str] = {}
    for tag in (t.strip().lstrip("#") for t in tags):
        if tag and (key := casefold_key(tag)) not in seen:
            seen[key] = tag
            session.add(NoteTag(file_id=file_id, tag=tag, tag_key=key))
    aliases = [a for a in (props or {}).get("aliases") or [] if isinstance(a, str)]
    session.add(
        SearchDocument(
            file_id=file_id,
            vault_id=vault_id,
            title=_searchable(title),
            keywords=_searchable(" ".join([*aliases, *seen.values()])),
            body=_searchable(doc.text[doc.body] if doc.text else ""),
        )
    )
    for ordinal, link in enumerate(found.links):
        session.add(
            NoteLink(
                file_id=file_id,
                ordinal=ordinal,
                target=link.target,
                target_key=target_key(link.target),
                embed=link.embed,
                heading=link.heading,
                block=link.block,
                alias=link.alias,
            )
        )


def _searchable(text: str) -> str:
    """PostgreSQL text holds no NUL; a tsvector holds at most 1 MiB."""
    return text.replace("\x00", "")[:MAX_SEARCH_CHARS]


def _resolve_links(session: Session, vault_id: uuid.UUID, which: ColumnElement[bool]) -> None:
    """Resolve the vault's links matching `which` against the live files with a matching
    file name, writing only the answers that changed."""
    rows = session.execute(
        select(
            NoteLink.file_id,
            NoteLink.ordinal,
            NoteLink.target,
            NoteLink.resolved_file_id,
            File.path,
        )
        .join(File, File.file_id == NoteLink.file_id)
        .where(File.vault_id == vault_id, which)
    ).all()
    keys = {target_key(r.target) for r in rows}
    leaf = func.regexp_replace(File.path_key, "^.*/", "")  # the files_leaf index
    live = session.execute(
        select(File.path, File.file_id).where(
            File.vault_id == vault_id,
            ~File.deleted,
            leaf == any_(literal(sorted(keys | {k + ".md" for k in keys}), ARRAY(Text))),
        )
    ).all()
    by_leaf: dict[str, list[str]] = defaultdict(list)
    for path, _ in live:
        by_leaf[casefold_key(posixpath.basename(path))].append(path)
    ids = dict(live)
    changed = []
    for file_id, ordinal, target, resolved, from_path in rows:
        key = target_key(target)
        link = Link(target, None, None, None, embed=False, markdown=False)
        hit = resolve(link, from_path, by_leaf[key] + by_leaf[key + ".md"])
        found = file_id if not target else ids.get(hit) if hit else None  # "" is the note itself
        if found != resolved:
            changed.append({"file_id": file_id, "ordinal": ordinal, "resolved_file_id": found})
    if changed:  # one executemany: an UPDATE by primary key per dict
        session.execute(update(NoteLink), changed)


def remove_file(session: Session, file_id: uuid.UUID) -> None:
    """Drop the derived rows of a deleted file; links to it become unresolved."""
    for model in DERIVED:
        session.execute(delete(model).where(model.file_id == file_id))
    session.execute(
        update(NoteLink).where(NoteLink.resolved_file_id == file_id).values(resolved_file_id=None)
    )
