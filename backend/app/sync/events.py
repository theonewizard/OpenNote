"""Change hints (sync protocol §4): after each commit the vault's newest `seq` is
published on Valkey, and `WSS /api/v1/events` forwards it to the vault's subscribers.
Hints are advisory: a lost one only delays a client until its next timed pull."""

import logging
import uuid

from redis import Redis
from redis.exceptions import RedisError

log = logging.getLogger(__name__)

CHANNEL_PREFIX = "opennote:changes:"


def channel(vault_id: uuid.UUID) -> str:
    return f"{CHANNEL_PREFIX}{vault_id}"


class Publisher:
    """Publishes from the commit threads; never raises (a commit is already durable)."""

    def __init__(self, valkey_url: str) -> None:
        self.client = Redis.from_url(valkey_url, socket_connect_timeout=0.5, socket_timeout=0.5)

    def publish(self, vault_id: uuid.UUID, seq: int) -> None:
        try:
            self.client.publish(channel(vault_id), str(seq))
        except RedisError:
            log.warning("change hint not published; clients catch up on their next pull")

    def close(self) -> None:
        self.client.close()
