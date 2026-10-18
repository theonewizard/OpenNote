"""Background jobs. Importing this module binds its actors to dramatiq's global broker,
so configure_broker() must have run: app.workers.__main__ does it in each worker
process."""

import time
from typing import cast

import dramatiq
from dramatiq.brokers.redis import RedisBroker

PING_TTL_SECONDS = 60


@dramatiq.actor
def ping(token: str, delay_seconds: float = 0.0) -> None:
    """Smoke-test job: set opennote:ping:<token>:started, wait `delay_seconds`, then set
    opennote:ping:<token>. Both hold "1" for 60 s, in the broker's Valkey."""
    valkey = cast(RedisBroker, ping.broker).client
    valkey.set(f"opennote:ping:{token}:started", "1", ex=PING_TTL_SECONDS)
    time.sleep(delay_seconds)
    valkey.set(f"opennote:ping:{token}", "1", ex=PING_TTL_SECONDS)
