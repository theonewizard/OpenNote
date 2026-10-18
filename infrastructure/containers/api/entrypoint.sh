#!/bin/sh
# Start the OpenNote API. With OPENNOTE_MIGRATE_ON_START=true it first applies the
# database migrations (alembic upgrade head, which needs only OPENNOTE_DATABASE_URL or
# OPENNOTE_DATABASE_URL_FILE); the default is false, so production migrates deliberately.
# Enable it on one API instance only: concurrent upgrades are not coordinated.
#
# Runs in /app (the image's WORKDIR). uvicorn is exec'd so it runs as PID 1 and receives
# SIGTERM directly. Its access log is off because those lines would bypass the app's JSON
# logger and its redaction filter.
set -eu

case "${OPENNOTE_MIGRATE_ON_START:-false}" in
  true) alembic upgrade head ;;
  false) ;;
  *)
    echo "OpenNote cannot start: OPENNOTE_MIGRATE_ON_START must be true or false" >&2
    exit 1
    ;;
esac

exec uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --no-access-log
