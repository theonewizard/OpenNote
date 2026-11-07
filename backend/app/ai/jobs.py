"""The embedding job. Whatever changes a note enqueues `embed_vault_job` for its vault;
a run embeds only what changed, so extra messages cost one query each."""

import uuid
from functools import cache

import dramatiq
from sqlalchemy import Engine

from app.ai.config import get_ai_settings
from app.ai.embeddings import embed_vault
from app.core.config import get_settings
from app.core.db import make_sync_engine

# Another run holds the vault: look again after this long, so its later edits are seen.
BUSY_DELAY_MS = 30_000


@cache
def _engine() -> Engine:
    return make_sync_engine(get_settings())


# A provider that is down fails the job; Dramatiq retries it three times with backoff,
# and the next enqueue picks up whatever was left.
@dramatiq.actor(max_retries=3, min_backoff=10_000, max_backoff=300_000, time_limit=3_600_000)
def embed_vault_job(vault_id: str) -> None:
    if embed_vault(_engine(), uuid.UUID(vault_id), get_ai_settings()) is None:
        embed_vault_job.send_with_options(args=(vault_id,), delay=BUSY_DELAY_MS)
