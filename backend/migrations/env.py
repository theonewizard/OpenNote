"""Alembic environment: migrations run over a synchronous psycopg 3 connection, or are
printed as SQL without connecting (`--sql`).

The URL comes from `alembic -x url=...` or else from OPENNOTE_DATABASE_URL (or
OPENNOTE_DATABASE_URL_FILE); no other setting is needed and the URL is never written to
a file. From the command line, Alembic's progress is logged as the app's JSON lines on
stderr, so stdout carries only Alembic's own output (the `--sql` script, `current`).
"""

import sys

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import load_database_url
from app.core.db import DB_CONNECT_TIMEOUT_SECONDS
from app.core.logging import configure_logging


def run_migrations_offline(url: str) -> None:
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online(url: str) -> None:
    engine = create_engine(
        url, poolclass=NullPool, connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS}
    )
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


# Callers that run Alembic in-process keep their own logging (Alembic's convention).
if context.config.attributes.get("configure_logger", True):
    configure_logging("INFO", stream=sys.stderr)
url = context.get_x_argument(as_dictionary=True).get("url") or load_database_url()
if context.is_offline_mode():
    run_migrations_offline(url)
else:
    run_migrations_online(url)
