"""Ask the worker to bring a vault's embeddings up to date, from a process that runs no
jobs (the API). The message is built by actor name, so this neither imports app.ai.jobs
nor needs dramatiq's global broker."""

import logging
import uuid
from functools import cache

import dramatiq

from app.ai.config import get_ai_settings
from app.core.config import Settings
from app.workers.broker import broker_from_settings

log = logging.getLogger(__name__)

ACTOR = "embed_vault_job"  # app.ai.jobs.embed_vault_job, on Dramatiq's default queue


@cache
def _broker(settings: Settings) -> dramatiq.Broker:
    return broker_from_settings(settings)


def request_embedding(settings: Settings, vault_id: uuid.UUID) -> None:
    """Enqueue an embedding run when the server has an AI provider; never raises, so a
    note save cannot fail because of AI. The job itself checks the vault's opt-in."""
    try:
        if get_ai_settings().provider == "none":
            return
        message: dramatiq.Message[None] = dramatiq.Message(
            queue_name="default", actor_name=ACTOR, args=(str(vault_id),), kwargs={}, options={}
        )
        _broker(settings).enqueue(message)
    except Exception as exc:  # Valkey down, invalid AI settings: the next save asks again
        log.warning("ai: embedding not requested for vault %s: %s", vault_id, type(exc).__name__)
