"""The OCR job. An image or PDF upload enqueues `ocr_vault_job` for its vault; a run reads
only attachments not read before, so extra messages cost one query each."""

import uuid
from functools import cache

import dramatiq
from sqlalchemy import Engine

from app.core.config import get_settings
from app.core.db import make_sync_engine
from app.ocr.vault import ocr_vault

BUSY_DELAY_MS = 30_000  # another run holds the vault: look again after this long


@cache
def _engine() -> Engine:
    return make_sync_engine(get_settings())


@dramatiq.actor(max_retries=3, min_backoff=10_000, max_backoff=300_000, time_limit=3_600_000)
def ocr_vault_job(vault_id: str) -> None:
    if ocr_vault(_engine(), uuid.UUID(vault_id), get_settings().ocr_languages) is None:
        ocr_vault_job.send_with_options(args=(vault_id,), delay=BUSY_DELAY_MS)
