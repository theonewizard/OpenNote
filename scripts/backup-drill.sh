#!/usr/bin/env bash
# Restore drill on the Compose stack (docs/deployment/backup.md, "Restore drill"), run by
# the containers workflow:
#
#   1. Start the full stack, commit revisions through OpenNote's commit path
#      (scripts/backup_drill.py seed) and take a backup with the stack running.
#   2. Keep committing while a second backup is taken.
#   3. For each backup: delete every volume, start PostgreSQL and Valkey on empty volumes,
#      restore, start the stack, and check it: recovery leaves the revision log equal to the
#      database, every revision's bytes in the history store and every live file in the
#      vault (backup_drill.py verify); the smoke test passes. The first backup must restore
#      to exactly what was written before it (same revisions, log, live files, vault bytes).
#
#   scripts/backup-drill.sh
#
# Needs docker with compose, gpg and the images built (`docker compose build`); uses
# infrastructure/compose/.env, copied from .env.example when missing, and a throwaway
# OpenPGP key. Deletes the stack's volumes. Exits 0 when every check passes.
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f infrastructure/compose/compose.yaml)
work=$(mktemp -d)
created_env=false
cleanup() {
  local status=$?
  ((status == 0)) || "${compose[@]}" logs --no-color --tail 50 || true
  "${compose[@]}" --profile backup --profile restore down -v --remove-orphans >/dev/null 2>&1 || true
  $created_env && rm -f infrastructure/compose/.env
  rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

if [[ ! -f infrastructure/compose/.env ]]; then
  cp infrastructure/compose/.env.example infrastructure/compose/.env
  created_env=true
fi

# A throwaway key pair without a passphrase, and a backup directory UID 1001 can write.
mkdir -m 0700 "$work/gnupg"
gpg --batch --quiet --homedir "$work/gnupg" --passphrase '' \
  --quick-gen-key "OpenNote restore drill <drill@example.invalid>" default default never
gpg --batch --homedir "$work/gnupg" --armor --export >"$work/public.asc"
gpg --batch --homedir "$work/gnupg" --pinentry-mode loopback --passphrase '' --armor \
  --export-secret-keys >"$work/private.asc"
chmod 0644 "$work/public.asc" "$work/private.asc" # read by UID 1001 in the containers
mkdir "$work/backups"
chmod 0777 "$work/backups"
export OPENNOTE_BACKUP_HOST_DIR=$work/backups OPENNOTE_BACKUP_PUBLIC_KEY=$work/public.asc \
  OPENNOTE_BACKUP_PRIVATE_KEY=$work/private.asc OPENNOTE_MIGRATE_ON_START=true

drill() {
  "${compose[@]}" exec -T api python - "$@" <scripts/backup_drill.py
}
newest_backup() {
  find "$work/backups" -name 'opennote-*.tar.gz.gpg' -printf '%f\n' | sort | tail -n 1
}

echo "== 1. seed and back up"
"${compose[@]}" down -v
"${compose[@]}" up -d --wait --wait-timeout 300
drill seed
drill fingerprint >"$work/before.json"
"${compose[@]}" run --rm backup
first=$(newest_backup)
[[ -n $first && -f $work/backups/$first.sha256 ]] || { echo "no backup written"; exit 1; }

echo "== 2. back up while commits go on"
sleep 1 # backup names have a resolution of one second
drill churn 20 &
churn=$!
sleep 5
"${compose[@]}" run --rm backup
wait "$churn"
second=$(newest_backup)
[[ $second != "$first" ]] || { echo "no second backup written"; exit 1; }

# restore_and_check <backup file name>
restore_and_check() {
  "${compose[@]}" down -v
  "${compose[@]}" up -d --wait --wait-timeout 300 postgres valkey
  "${compose[@]}" run --rm restore "/backups/$1"
  "${compose[@]}" up -d --wait --wait-timeout 300
  drill verify
  scripts/smoke-test.sh http://localhost:8080
}

echo "== 3a. restore $first: exactly what was written"
restore_and_check "$first"
drill fingerprint >"$work/after.json"
cmp "$work/before.json" "$work/after.json" || {
  diff <(python3 -m json.tool "$work/before.json") <(python3 -m json.tool "$work/after.json") | head -40
  echo "the restored state differs from the state before the backup"
  exit 1
}
echo "restored state equals the state before the backup"

echo "== 3b. restore $second, taken during commits"
restore_and_check "$second"

echo "restore drill passed"
