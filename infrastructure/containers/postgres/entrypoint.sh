#!/bin/bash
# opennote-postgres entrypoint. On the first start, with an empty data volume, it creates
# the cluster and, each with the vector and pg_trgm extensions (so migration 0001 has
# nothing to do there):
#   - the database POSTGRES_DB (default opennote), and
#   - the database POSTGRES_TEST_DB if set (the dev stack sets opennote_test, the
#     integration tests' database).
# POSTGRES_USER (default opennote) becomes the cluster's superuser, with the password from
# POSTGRES_PASSWORD or, if that is unset or empty, from the file POSTGRES_PASSWORD_FILE.
# These are read only on the first start. Connections over TCP need that password; local
# socket connections, which only processes inside the container can make, need none.
#
# Then it runs the server as PID 1; arguments are passed to it (for example -c settings).
set -euo pipefail

user=${POSTGRES_USER:-opennote}
database=${POSTGRES_DB:-opennote}
socket_dir=/tmp

# The image may run as any UID (OpenShift assigns one), and initdb needs a passwd entry for
# it: /etc/passwd points to /tmp/passwd (see the Containerfile), written here unless the
# runtime already provides an entry for this UID.
if ! getent passwd "$(id -u)" >/dev/null; then
  {
    cat /etc/passwd.image
    echo "opennote-postgres:x:$(id -u):0:PostgreSQL:/var/lib/postgresql:/sbin/nologin"
  } >/tmp/passwd
fi

if [[ ! -s $PGDATA/PG_VERSION ]]; then
  password=${POSTGRES_PASSWORD:-}
  if [[ -z $password && -n ${POSTGRES_PASSWORD_FILE:-} ]]; then
    password=$(<"$POSTGRES_PASSWORD_FILE")
  fi
  if [[ -z $password ]]; then
    echo "opennote-postgres cannot initialise: set POSTGRES_PASSWORD or POSTGRES_PASSWORD_FILE" >&2
    exit 1
  fi

  # Built in a scratch directory and moved into place when complete, so a first start
  # that fails part-way is redone from the beginning on the next start.
  init=$PGDATA.init
  rm -rf "$init"
  # The builtin C.UTF-8 locale sorts by code point, so an operating system update can
  # never change the order of an existing index.
  initdb --pgdata="$init" --username="$user" --pwfile=<(printf '%s\n' "$password") \
    --auth-local=trust --auth-host=scram-sha-256 \
    --encoding=UTF8 --locale=C.UTF-8 --locale-provider=builtin
  # initdb allows TCP from 127.0.0.1 and ::1 only; the other containers connect over the
  # container network.
  echo "host all all all scram-sha-256" >>"$init/pg_hba.conf"

  # Socket only, so health checks over TCP fail until the databases exist.
  pg_ctl --pgdata="$init" --wait --silent \
    --options="-c listen_addresses='' -c unix_socket_directories=$socket_dir" start
  for name in "$database" ${POSTGRES_TEST_DB:+"$POSTGRES_TEST_DB"}; do
    psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 --set=name="$name" \
      --host="$socket_dir" --username="$user" --dbname=postgres <<'SQL'
CREATE DATABASE :"name";
\connect :"name"
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
  done
  pg_ctl --pgdata="$init" --wait --silent --mode=fast stop
  mv --no-target-directory "$init" "$PGDATA"
fi

exec postgres -D "$PGDATA" -c listen_addresses='*' -c unix_socket_directories="$socket_dir" "$@"
