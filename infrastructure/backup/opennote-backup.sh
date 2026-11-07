#!/usr/bin/env bash
# opennote-backup: one encrypted backup of OpenNote's PostgreSQL database, history store and
# vaults, taken while OpenNote runs (docs/deployment/backup.md).
#
#   opennote-backup
#
# Settings, from the environment:
#   OPENNOTE_DATABASE_URL or OPENNOTE_DATABASE_URL_FILE  the database, as OpenNote reads it
#   OPENNOTE_VAULT_ROOT, OPENNOTE_HISTORY_ROOT           the two directories, as OpenNote reads them
#   OPENNOTE_BACKUP_DIR                                  where the backup is written
#   OPENNOTE_BACKUP_PUBLIC_KEY_FILE                      the OpenPGP public key it is encrypted to
#   OPENNOTE_BACKUP_KEEP                                 backups kept in OPENNOTE_BACKUP_DIR, default 7; 0 keeps all
#
# Writes OPENNOTE_BACKUP_DIR/opennote-<UTC time>.tar.gz.gpg and a .sha256 beside it: a tar
# archive, gzip-compressed and encrypted to the public key, holding
#   FORMAT          "opennote-backup 1"
#   manifest.txt    time, database migration revision, pg_dump version, SHA-256 of db.dump
#   history-log/    <vault id>/log/*.jsonl, copied first
#   db.dump         pg_dump --format=custom, one consistent snapshot, taken second
#   history/        <vault id>/objects/..., read third
#   vaults/         the vault directories, read last
# Each revision is made durable in the order history object, database, log, vault file
# (app/sync/commit.py), so this order gives a backup in which the log holds no revision the
# database lacks, every revision in the database has its history object, and a vault file is
# either the database's revision or newer: the state a crash between two commit steps leaves,
# which OpenNote's recovery repairs on start (docs/deployment/backup.md, "Consistency").
#
# The private key never needs to be where backups are taken. Exits 0 after writing the
# backup and pruning old ones, 1 on any failure (a partial file is removed), 2 for bad settings.
set -euo pipefail
umask 077

die() {
  echo "opennote-backup: $*" >&2
  exit "${2:-1}"
}
log() {
  echo "opennote-backup: $*" >&2
}

# setting <name>: the variable's value, or the content of <name>_FILE; empty if neither.
setting() {
  local name=$1 file_var="${1}_FILE"
  if [[ -n ${!name:-} ]]; then
    printf '%s' "${!name}"
  elif [[ -n ${!file_var:-} ]]; then
    [[ -r ${!file_var} ]] || die "$file_var is not readable" 2
    tr -d '\n' <"${!file_var}"
  fi
}

database_url=$(setting OPENNOTE_DATABASE_URL)
[[ -n $database_url ]] || die "set OPENNOTE_DATABASE_URL or OPENNOTE_DATABASE_URL_FILE" 2
# OpenNote's SQLAlchemy URL names the driver (postgresql+psycopg://); libpq wants postgresql://.
dburl=${database_url/#postgresql+psycopg:/postgresql:}
vault_root=${OPENNOTE_VAULT_ROOT:-}
history_root=${OPENNOTE_HISTORY_ROOT:-}
backup_dir=${OPENNOTE_BACKUP_DIR:-}
public_key=${OPENNOTE_BACKUP_PUBLIC_KEY_FILE:-}
keep=${OPENNOTE_BACKUP_KEEP:-7}
for dir in "$vault_root" "$history_root" "$backup_dir"; do
  [[ -n $dir && -d $dir ]] || die "OPENNOTE_VAULT_ROOT, OPENNOTE_HISTORY_ROOT and OPENNOTE_BACKUP_DIR must be directories" 2
done
[[ -r $public_key ]] || die "OPENNOTE_BACKUP_PUBLIC_KEY_FILE is not readable" 2
[[ $keep =~ ^[0-9]+$ ]] || die "OPENNOTE_BACKUP_KEEP must be a whole number" 2

stage=$(mktemp -d)
gnupg_home=$(mktemp -d)
name=opennote-$(date -u +%Y%m%dT%H%M%SZ).tar.gz.gpg
partial=$backup_dir/.$name.partial
cleanup() {
  rm -rf "$stage" "$gnupg_home" "$partial"
}
trap cleanup EXIT

# The key is checked before anything is read, so a wrong key fails in seconds.
gpg_args=(--batch --quiet --homedir "$gnupg_home" --trust-model always --recipient-file "$public_key")
gpg "${gpg_args[@]}" --encrypt </dev/null >/dev/null || die "cannot encrypt to OPENNOTE_BACKUP_PUBLIC_KEY_FILE"

log "1/4 revision logs"
mkdir "$stage/history-log"
for log_dir in "$history_root"/*/log; do
  [[ -d $log_dir ]] || continue
  vault_id=$(basename "$(dirname "$log_dir")")
  mkdir "$stage/history-log/$vault_id"
  cp -R "$log_dir" "$stage/history-log/$vault_id/"
done

log "2/4 database"
pg_dump --format=custom --no-owner --no-privileges --file "$stage/db.dump" --dbname "$dburl"
echo "opennote-backup 1" >"$stage/FORMAT"
{
  echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "alembic_revision=$(psql -X -A -t -c 'select version_num from alembic_version' "$dburl")"
  echo "pg_dump=$(pg_dump --version)"
  echo "db_dump_sha256=$(sha256sum "$stage/db.dump" | cut -d ' ' -f 1)"
} >"$stage/manifest.txt"

log "3/4 history objects and 4/4 vaults, into $name"
# Member names start with history/ and vaults/ whatever the directories are called. The live
# logs are left out: history-log/ holds the copy taken before the dump. Symbolic links are
# stored as links, never followed. tar exits 1 when a file or directory changes while it is
# read: routinely a directory that gains a file during the backup, which the database
# snapshot does not need; OpenNote replaces files by rename, so only an edit made in place
# outside OpenNote can leave a half-written file in the archive.
history_parent=$(dirname "$history_root") history_base=$(basename "$history_root")
vault_parent=$(dirname "$vault_root") vault_base=$(basename "$vault_root")
for base in "$history_base" "$vault_base"; do
  [[ $base =~ ^[A-Za-z0-9._-]+$ ]] || die "directory name '$base' has characters other than letters, digits, . _ -" 2
done
set +e
tar --create --format=posix --warning=no-file-changed \
  -C "$stage" FORMAT manifest.txt history-log db.dump \
  --anchored --no-wildcards-match-slash --exclude="$history_base/*/log" \
  --transform="s,^$history_base\(/\|\$\),history\1,S" -C "$history_parent" "$history_base" \
  --transform="s,^$vault_base\(/\|\$\),vaults\1,S" -C "$vault_parent" "$vault_base" |
  gzip -6 | gpg "${gpg_args[@]}" --encrypt --output "$partial"
statuses=("${PIPESTATUS[@]}")
set -e
((statuses[0] <= 1)) || die "tar failed (exit ${statuses[0]})"
((statuses[0] == 0)) || log "warning: a file changed while it was read (tar exit 1)"
((statuses[1] == 0 && statuses[2] == 0)) || die "compression or encryption failed"

mv "$partial" "$backup_dir/$name"
(cd "$backup_dir" && sha256sum "$name" >"$name.sha256")
log "wrote $backup_dir/$name ($(du -h "$backup_dir/$name" | cut -f 1))"

if ((keep > 0)); then
  mapfile -t old < <(find "$backup_dir" -maxdepth 1 -name 'opennote-*.tar.gz.gpg' -printf '%f\n' |
    sort -r | tail -n "+$((keep + 1))")
  for file in "${old[@]}"; do
    rm -f "$backup_dir/$file" "$backup_dir/$file.sha256"
    log "removed $file (OPENNOTE_BACKUP_KEEP=$keep)"
  done
fi
