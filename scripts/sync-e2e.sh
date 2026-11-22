#!/usr/bin/env bash
# Cross-client sync suite (roadmap P5-09): the web app and the Apple sync engine against one
# real server. Builds `opennote-sync` (apple/Packages/OpenNoteSync), migrates the database,
# creates a throwaway user, starts the API, the vault watcher and the web dev server on
# loopback ports, then runs web/tests/sync-e2e with Playwright. Everything it starts is
# stopped on exit; logs are printed when a step fails.
#
# Needs: PostgreSQL with pgvector and Valkey (the backend test services), .venv with the
# backend dev requirements, web/node_modules, Chromium for Playwright, Swift 6.4 and the
# SQLite headers. Development settings only: never point it at a server with real vaults.
#
#   OPENNOTE_E2E_DATABASE_URL  default postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote_e2e
#   OPENNOTE_E2E_VALKEY_URL    default redis://127.0.0.1:6379/2
#   OPENNOTE_SYNC_CLI          an opennote-sync already built (skips the Swift build)
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
pids=()

cleanup() {
  status=$?
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  if ((status != 0)); then
    for log in "$work"/*.log; do
      [[ -f $log ]] || continue
      echo "::group::$(basename "$log")"
      tail -n 200 "$log"
      echo "::endgroup::"
    done
  fi
  rm -rf "$work"
}
trap cleanup EXIT

wait_for() { # url, name
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "$2 did not start" >&2
  return 1
}

if [[ -n ${OPENNOTE_SYNC_CLI:-} ]]; then
  cli=$OPENNOTE_SYNC_CLI # an opennote-sync built elsewhere
else
  echo "== build opennote-sync"
  swift build -c release --package-path "$repo/apple/Packages/OpenNoteSync" --product opennote-sync
  cli="$(swift build -c release --package-path "$repo/apple/Packages/OpenNoteSync" --show-bin-path)/opennote-sync"
fi

mkdir -p "$work/vaults" "$work/history"
export OPENNOTE_DATABASE_URL=${OPENNOTE_E2E_DATABASE_URL:-postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote_e2e}
export OPENNOTE_VALKEY_URL=${OPENNOTE_E2E_VALKEY_URL:-redis://127.0.0.1:6379/2}
export OPENNOTE_VAULT_ROOT=$work/vaults OPENNOTE_HISTORY_ROOT=$work/history
# Development: the session cookie works over plain http on loopback. No rate limits, as
# the suite signs in and syncs faster than a person.
export OPENNOTE_ENVIRONMENT=development
export OPENNOTE_RATE_LIMIT_PER_PRINCIPAL=0 OPENNOTE_RATE_LIMIT_PER_IP=0 OPENNOTE_RATE_LIMIT_AUTH_PER_IP=0
python=$repo/.venv/bin/python

echo "== migrate and create the user"
cd "$repo/backend"
"$repo/.venv/bin/alembic" upgrade head
# An administrator, as only one may create a vault in an existing folder (the suite edits
# that folder directly, as Obsidian on the server would); a new name each run.
user=e2e-$(date +%s)
password=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
printf '%s\n' "$password" | "$python" -m app.auth.admin create-user "$user" --admin >/dev/null

echo "== start API, vault watcher and web app"
"$python" -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 >"$work/api.log" 2>&1 &
pids+=($!)
"$python" -m app.vaults >"$work/watcher.log" 2>&1 &
pids+=($!)
cd "$repo/web"
OPENNOTE_API_URL=http://127.0.0.1:8000 npx vite --host 127.0.0.1 --port 5173 --strictPort >"$work/web.log" 2>&1 &
pids+=($!)
wait_for http://127.0.0.1:8000/readyz API
wait_for http://127.0.0.1:5173/ "web app"

echo "== cross-client suite"
OPENNOTE_SYNC_CLI=$cli OPENNOTE_E2E_VAULT_ROOT=$work/vaults OPENNOTE_E2E_USER=$user OPENNOTE_E2E_PASSWORD=$password \
  OPENNOTE_E2E_API=http://127.0.0.1:8000 OPENNOTE_E2E_WEB=http://127.0.0.1:5173 \
  npx playwright test -c playwright.sync-e2e.config.ts "$@"
