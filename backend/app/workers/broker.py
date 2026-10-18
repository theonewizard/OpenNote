"""Dramatiq's broker on Valkey. Building it makes no connection; the first send or
consume does."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import Settings

# Prefix of every key the broker keeps in Valkey.
NAMESPACE = "opennote"


def broker_from_settings(s: Settings) -> dramatiq.Broker:
    # RedisBroker.__init__ has no type annotations.
    return RedisBroker(url=str(s.valkey_url), namespace=NAMESPACE)  # type: ignore[no-untyped-call]


def configure_broker(settings: Settings) -> dramatiq.Broker:
    """Make the settings' broker dramatiq's global broker and return it. Actors bind to
    the global broker when they are declared, so this runs before app.workers.jobs is
    imported."""
    broker = broker_from_settings(settings)
    dramatiq.set_broker(broker)
    return broker
