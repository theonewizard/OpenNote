"""The embedding pipeline (P7-02): notes are cut into chunks at headings and paragraph
breaks, each chunk is embedded with the note's title in front, and the vectors go to
`ai_chunks`. A run embeds only notes whose file content or model changed since the last
run, and in a changed note only the chunks whose text changed."""

import hashlib
import logging
import os
import re
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Engine, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.config import AISettings
from app.ai.models import AIChunk, AINoteState, AIVaultSettings
from app.ai.providers import AIProvider, provider_from_settings
from app.notes.document import parse_note
from app.notes.models import File, Note
from app.vaults.fsio import PathEscapeError, open_root, read_file
from app.vaults.models import Vault

log = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 2000  # about 500 tokens: inside every common embedding model's window
EMBED_BATCH = 32  # texts per provider request
NOTE_BATCH = 100  # notes per database query
_PARAGRAPH_BREAK = re.compile(r"\r?\n[ \t]*\r?\n")
_HEADING = re.compile(r"#{1,6}[ \t]")


def chunk_text(body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Paragraphs joined up to `max_chars`; a heading always starts a new chunk, and a
    paragraph longer than `max_chars` is cut into pieces of that size."""
    chunks: list[str] = []
    current = ""
    for block in (b.strip() for b in _PARAGRAPH_BREAK.split(body)):
        if not block:
            continue
        if current and (_HEADING.match(block) or len(current) + 2 + len(block) > max_chars):
            chunks.append(current)
            current = ""
        while len(block) > max_chars:
            chunks.append(block[:max_chars])
            block = block[max_chars:]
        current = f"{current}\n\n{block}" if current else block
    if current:
        chunks.append(current)
    return chunks


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def vault_provider(
    session: Session, vault_id: uuid.UUID, settings: AISettings
) -> AIProvider | None:
    """The provider this vault may use, or None: AI off on the server, off for the vault
    (the default), or the provider is external and the vault has not allowed that."""
    provider = provider_from_settings(settings)
    if provider is None:
        return None
    row = session.get(AIVaultSettings, vault_id)
    if row is None or not row.enabled or (provider.external and not row.allow_external):
        return None
    return provider


def set_vault_ai(
    session: Session, vault_id: uuid.UUID, *, enabled: bool, allow_external: bool = False
) -> None:
    """Switch AI on or off for a vault; turning it off also drops its embeddings."""
    values = {"enabled": enabled, "allow_external": enabled and allow_external}
    session.execute(
        insert(AIVaultSettings)
        .values(vault_id=vault_id, **values)
        .on_conflict_do_update(index_elements=["vault_id"], set_=values)
    )
    if not enabled:
        vault_files = select(File.file_id).where(File.vault_id == vault_id)
        for model in (AIChunk, AINoteState):
            session.execute(delete(model).where(model.file_id.in_(vault_files)))


def embed_vault(engine: Engine, vault_id: uuid.UUID, settings: AISettings) -> int | None:
    """Bring the vault's embeddings up to date; return the number of notes embedded, 0
    when AI is off for it, or None when another run holds the vault (try again later).

    Provider calls happen between transactions, so a slow provider holds no row locks."""
    with engine.connect() as lock:
        # A session-level lock, released explicitly: the connection returns to the pool.
        key = int.from_bytes(vault_id.bytes[:8], signed=True)
        if not lock.scalar(select(func.pg_try_advisory_lock(key))):
            return None
        lock.commit()
        try:
            with Session(engine) as session:
                return _embed_vault(session, vault_id, settings)
        finally:
            lock.execute(select(func.pg_advisory_unlock(key)))
            lock.commit()


def _embed_vault(session: Session, vault_id: uuid.UUID, settings: AISettings) -> int:
    provider = vault_provider(session, vault_id, settings)
    model = settings.embed_model
    root = session.scalar(select(Vault.root_path).where(Vault.id == vault_id))
    if provider is None or model is None or root is None:
        session.commit()
        return 0
    gone = select(File.file_id).where(
        File.vault_id == vault_id, or_(File.deleted, File.kind != "note")
    )
    for table in (AIChunk, AINoteState):
        session.execute(delete(table).where(table.file_id.in_(gone)))
    session.commit()
    stale = (
        select(File.file_id, File.path, Note.title)
        .outerjoin(Note, Note.file_id == File.file_id)
        .outerjoin(AINoteState, AINoteState.file_id == File.file_id)
        .where(
            File.vault_id == vault_id,
            File.kind == "note",
            ~File.deleted,
            or_(
                AINoteState.file_id.is_(None),
                AINoteState.content_hash != File.content_hash,
                AINoteState.model != model,
            ),
        )
        .order_by(File.path)
        .limit(NOTE_BATCH)
    )
    done = 0
    root_fd = open_root(Path(root))
    try:
        last = ""
        while batch := session.execute(stale.where(File.path > last)).all():
            session.commit()  # end the read transaction before calling the provider
            for file_id, path, title in batch:
                try:
                    raw = read_file(root_fd, path)
                except FileNotFoundError, PathEscapeError:
                    log.info("ai: note %s is gone from disk; skipped", file_id)
                    continue
                _embed_note(session, provider, model, file_id, title or "", raw)
                done += 1
            last = batch[-1].path
    finally:
        os.close(root_fd)
    return done


def _embed_note(
    session: Session, provider: AIProvider, model: str, file_id: uuid.UUID, title: str, raw: bytes
) -> None:
    doc = parse_note(raw)
    # A note that is not UTF-8 is opaque bytes (storage contract §2.2): nothing to embed.
    chunks = chunk_text(doc.text[doc.body]) if doc.text is not None else []
    texts = [f"{title}\n\n{chunk}" for chunk in chunks]
    hashes = [_sha(t.encode()) for t in texts]
    state = session.get(AINoteState, file_id)
    known: dict[str, list[float]] = {}
    if state is not None and state.model == model:
        rows = session.execute(
            select(AIChunk.text_hash, AIChunk.embedding).where(AIChunk.file_id == file_id)
        )
        known = {h: e for h, e in rows}
    session.commit()
    missing = {h: t for t, h in zip(texts, hashes, strict=True) if h not in known}
    known |= dict(zip(missing, _embed(provider, list(missing.values()), model), strict=True))
    session.execute(delete(AIChunk).where(AIChunk.file_id == file_id))
    session.add_all(
        AIChunk(file_id=file_id, ordinal=i, text_hash=h, text=c, embedding=known[h])
        for i, (h, c) in enumerate(zip(hashes, chunks, strict=True))
    )
    values = {"content_hash": _sha(raw), "model": model}
    session.execute(
        insert(AINoteState)
        .values(file_id=file_id, **values)
        .on_conflict_do_update(index_elements=["file_id"], set_=values)
    )
    session.commit()


def _embed(provider: AIProvider, texts: Sequence[str], model: str) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors += provider.embed(texts[start : start + EMBED_BATCH], model)
    return vectors
