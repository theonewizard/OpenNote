"""Alembic environment: runs the migrations over a synchronous psycopg 3 connection.

The URL comes from `alembic -x url=...` or else from the app's settings
(OPENNOTE_DATABASE_URL or OPENNOTE_DATABASE_URL_FILE); it is never written to a file.
"""

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.core.config import load_settings

url = context.get_x_argument(as_dictionary=True).get("url") or str(load_settings().database_url)

with create_engine(url, poolclass=NullPool).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
