"""Bring a vault's OCR text up to date (P6-06), and ask the worker to do it.

Every live image or PDF attachment whose content hash has no `ocr_texts` row is read in
a child process (`python -m app.ocr`) limited in memory and time, so a hostile or broken
file cannot take the worker down. A file that cannot be read gets a `failed` row and is
not tried again until its content changes.
"""

import argparse
import logging
import os
import resource
import shutil
import signal
import subprocess  # nosec B404  # fixed argv, no shell
import sys
import uuid
from functools import cache
from pathlib import Path

import dramatiq
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import make_sync_engine
from app.core.logging import configure_logging
from app.notes.models import File
from app.ocr.models import OcrText
from app.vaults.fsio import PathEscapeError, open_root, read_file
from app.vaults.models import Vault
from app.workers.broker import broker_from_settings

log = logging.getLogger(__name__)

ACTOR = "ocr_vault_job"  # app.ocr.jobs.ocr_vault_job, on Dramatiq's default queue
SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif", ".webp", ".bmp", ".pdf")
FILE_TIMEOUT = 600  # seconds for one attachment, all its pages included
MEMORY_LIMIT = 2 * 1024**3  # address space of the child and the tesseract it runs
MAX_TEXT = 1_000_000  # characters kept per attachment
LOCK_CLASS = 0x0C12  # first key of the two-key advisory lock (the AI job uses one key)
BATCH = 50


def is_candidate(path: str | None) -> bool:
    return path is not None and path.lower().endswith(SUFFIXES)


def _limit() -> None:  # runs in the child between fork and exec
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))


def run_isolated(data: bytes, languages: str) -> str | None:
    """The file's text, or None when it cannot be read (logged without its content).
    The child runs in its own process group, so a timeout also kills its Tesseract."""
    with subprocess.Popen(  # noqa: S603  # nosec B603  # fixed argv, languages validated
        [sys.executable, "-m", "app.ocr", languages],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        process_group=0,
        preexec_fn=_limit,  # only setrlimit, which is async-signal-safe
        cwd=Path(__file__).resolve().parents[2],  # where `app` is importable
    ) as child:
        try:
            out, err = child.communicate(data, timeout=FILE_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            log.warning("ocr: gave up after %s s", FILE_TIMEOUT)
            return None
    if child.returncode != 0:
        reason = err.decode("utf-8", "replace").strip().splitlines()[-1:]
        log.info("ocr: unreadable (%s)", reason[0][:200] if reason else child.returncode)
        return None
    return out.decode("utf-8", "replace")[:MAX_TEXT]


def missing_languages(languages: str) -> set[str] | None:
    """The configured languages Tesseract has no data for, or None without Tesseract."""
    binary = shutil.which("tesseract")
    if binary is None:
        return None
    listed = subprocess.run(  # noqa: S603  # nosec B603  # fixed argv
        [binary, "--list-langs"], capture_output=True, timeout=30, check=False, text=True
    )
    return set(languages.split("+")) - set(listed.stdout.split()[1:])


def ocr_vault(engine: Engine, vault_id: uuid.UUID, languages: str) -> int | None:
    """Read the vault's new attachments; return how many were read, or None when another
    run holds the vault (try again later). Reads nothing without Tesseract or without
    data for a configured language, so no file is wrongly recorded as unreadable."""
    missing = missing_languages(languages)
    if missing is None:
        log.warning("ocr: tesseract is not installed; attachments are not read")
        return 0
    if missing:
        log.error("ocr: no Tesseract data for %s; attachments are not read", sorted(missing))
        return 0
    with engine.connect() as lock:
        key = int.from_bytes(vault_id.bytes[:4], signed=True)
        if not lock.scalar(select(func.pg_try_advisory_lock(LOCK_CLASS, key))):
            return None
        lock.commit()
        try:
            with Session(engine) as session:
                return _ocr_vault(session, vault_id, languages)
        finally:
            lock.execute(select(func.pg_advisory_unlock(LOCK_CLASS, key)))
            lock.commit()


def _ocr_vault(session: Session, vault_id: uuid.UUID, languages: str) -> int:
    root = session.scalar(select(Vault.root_path).where(Vault.id == vault_id))
    if root is None:
        return 0
    live = select(File.content_hash).where(
        File.vault_id == vault_id, File.kind == "attachment", ~File.deleted
    )
    session.execute(
        delete(OcrText).where(OcrText.vault_id == vault_id, OcrText.content_hash.not_in(live))
    )
    session.commit()
    suffix = func.lower(File.path).regexp_match(r"\.(" + "|".join(s[1:] for s in SUFFIXES) + ")$")
    done_hashes = select(OcrText.content_hash).where(OcrText.vault_id == vault_id)
    todo = (
        select(File.path, File.content_hash)
        .where(
            File.vault_id == vault_id,
            File.kind == "attachment",
            ~File.deleted,
            suffix,
            File.content_hash.not_in(done_hashes),
        )
        .order_by(File.path)
        .limit(BATCH)
    )
    done = 0
    root_fd = open_root(Path(root))
    try:
        last = ""
        while batch := session.execute(todo.where(File.path > last)).all():
            session.commit()  # no transaction stays open while a file is read
            for path, content_hash in batch:
                if session.get(OcrText, (vault_id, content_hash)) is not None:
                    continue  # a copy earlier in this batch
                try:
                    data = read_file(root_fd, path)
                except FileNotFoundError, PathEscapeError:
                    continue
                text = run_isolated(data, languages)
                session.add(
                    OcrText(
                        vault_id=vault_id,
                        content_hash=content_hash,
                        text=text or "",
                        failed=text is None,
                    )
                )
                session.commit()
                done += 1
            last = batch[-1].path
    finally:
        os.close(root_fd)
    return done


@cache
def _broker(settings: Settings) -> dramatiq.Broker:
    return broker_from_settings(settings)


def request_ocr(settings: Settings, vault_id: uuid.UUID) -> None:
    """Enqueue an OCR run for the vault; never raises, so an upload cannot fail because
    of it. Called by the API after an image or PDF attachment is committed."""
    try:
        message: dramatiq.Message[None] = dramatiq.Message(
            queue_name="default", actor_name=ACTOR, args=(str(vault_id),), kwargs={}, options={}
        )
        _broker(settings).enqueue(message)
    except Exception as exc:  # Valkey down: the next upload asks again
        log.warning("ocr: run not requested for vault %s: %s", vault_id, type(exc).__name__)


def main(argv: list[str] | None = None) -> int:
    """`python -m app.ocr.vault <vault-id>`: read a vault's attachments now, for example
    attachments uploaded before OCR was installed."""
    parser = argparse.ArgumentParser(prog="python -m app.ocr.vault")
    parser.add_argument("vault_id", type=uuid.UUID)
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)
    done = ocr_vault(make_sync_engine(settings), args.vault_id, settings.ocr_languages)
    if done is None:
        print("another OCR run holds this vault; try again later", file=sys.stderr)
        return 1
    print(f"{done} attachment(s) read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
