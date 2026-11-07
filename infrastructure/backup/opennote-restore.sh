#!/usr/bin/env bash
# opennote-restore: restore a backup made by opennote-backup into an empty database and
# empty vault and history directories, with OpenNote stopped (docs/deployment/backup.md).
#
#   opennote-restore <backup file>
#
# Settings, from the environment:
#   OPENNOTE_DATABASE_URL or OPENNOTE_DATABASE_URL_FILE  the database to restore into (no tables)
#   OPENNOTE_VAULT_ROOT, OPENNOTE_HISTORY_ROOT           the two directories (empty)
#   OPENNOTE_BACKUP_PRIVATE_KEY_FILE                     the OpenPGP private key the backup is encrypted to
#   OPENNOTE_BACKUP_PASSPHRASE_FILE                      its passphrase, if it has one
#
# Checks the .sha256 beside the backup when there is one, decrypts the backup, writes the
# vaults, the history objects and the revision logs straight into the two directories,
# restores the database dump, and checks the restored migration revision against the
# manifest. Refuses to touch a database that has tables or a directory that is not empty,
# so it never overwrites anything. On the next start OpenNote's recovery reconciles the
# vaults with the database (docs/deployment/backup.md, "Consistency"). Exits 0 when
# restored, 1 on failure, 2 for bad usage or settings.
set -euo pipefail
umask 077

die() {
  echo "opennote-restore: $*" >&2
  exit "${2:-1}"
}
log() {
  echo "opennote-restore: $*" >&2
}

setting() {
  local name=$1 file_var="${1}_FILE"
  if [[ -n ${!name:-} ]]; then
    printf '%s' "${!name}"
  elif [[ -n ${!file_var:-} ]]; then
    [[ -r ${!file_var} ]] || die "$file_var is not readable" 2
    tr -d '\n' <"${!file_var}"
  fi
}

(($# == 1)) || die "usage: opennote-restore <backup file>" 2
backup=$1
[[ -r $backup ]] || die "cannot read $backup" 2
database_url=$(setting OPENNOTE_DATABASE_URL)
[[ -n $database_url ]] || die "set OPENNOTE_DATABASE_URL or OPENNOTE_DATABASE_URL_FILE" 2
dburl=${database_url/#postgresql+psycopg:/postgresql:}
vault_root=${OPENNOTE_VAULT_ROOT:-}
history_root=${OPENNOTE_HISTORY_ROOT:-}
private_key=${OPENNOTE_BACKUP_PRIVATE_KEY_FILE:-}
passphrase=${OPENNOTE_BACKUP_PASSPHRASE_FILE:-}
for dir in "$vault_root" "$history_root"; do
  [[ $dir == /* && -d $dir ]] || die "OPENNOTE_VAULT_ROOT and OPENNOTE_HISTORY_ROOT must be absolute paths of directories" 2
  [[ -z $(find "$dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || die "$dir is not empty"
done
[[ -r $private_key ]] || die "OPENNOTE_BACKUP_PRIVATE_KEY_FILE is not readable" 2
[[ -z $passphrase || -r $passphrase ]] || die "OPENNOTE_BACKUP_PASSPHRASE_FILE is not readable" 2
tables=$(psql -X -A -t -c "select count(*) from pg_tables where schemaname = 'public'" "$dburl") ||
  die "cannot connect to the database"
[[ $tables == 0 ]] || die "the database has $tables tables; restore into an empty database"

if [[ -r $backup.sha256 ]]; then
  (cd "$(dirname "$backup")" && sha256sum --check --quiet "$(basename "$backup").sha256") ||
    die "$backup does not match its .sha256"
  log "checksum matches"
fi

stage=$(mktemp -d)
gnupg_home=$(mktemp -d)
cleanup() {
  rm -rf "$stage" "$gnupg_home"
}
trap cleanup EXIT

gpg_args=(--batch --quiet --homedir "$gnupg_home" --pinentry-mode loopback)
[[ -n $passphrase ]] && gpg_args+=(--passphrase-file "$passphrase")
gpg "${gpg_args[@]}" --import "$private_key" || die "cannot import OPENNOTE_BACKUP_PRIVATE_KEY_FILE"

# The whole file is decrypted once before anything is written: gpg checks its integrity
# only at the end, and a damaged file must not leave half a restore behind.
log "checking that $backup decrypts"
gpg "${gpg_args[@]}" --decrypt "$backup" | gunzip | tar --list >/dev/null ||
  die "$backup does not decrypt and unpack (wrong key or damaged file)"

log "extracting $backup"
# One pass over the archive: vaults/ and history/ into the two directories, the logs back
# into <vault id>/log/, the rest into the staging directory. Members are extracted relative
# to /, so each name is rewritten to its absolute target minus the leading slash; tar
# refuses names with "..". Files keep their archived modes (group 0 must keep its access
# for an arbitrary UID); existing directories (the mount points) keep their owner and mode.
set +e
gpg "${gpg_args[@]}" --decrypt "$backup" | gunzip | tar --extract --no-same-owner --no-overwrite-dir --preserve-permissions \
  -C / \
  --transform="s,^vaults\(/\|\$\),${vault_root#/}\1,S" \
  --transform="s,^history\(/\|\$\),${history_root#/}\1,S" \
  --transform="s,^history-log\(/\|\$\),${history_root#/}\1,S" \
  --transform="s,^\(FORMAT\|manifest\.txt\|db\.dump\)\$,${stage#/}/\1,S"
statuses=("${PIPESTATUS[@]}")
set -e
((statuses[0] == 0)) || die "decryption failed (wrong key or damaged file)"
((statuses[1] == 0 && statuses[2] == 0)) || die "the archive is damaged (gunzip ${statuses[1]}, tar ${statuses[2]})"
[[ $(cat "$stage/FORMAT" 2>/dev/null) == "opennote-backup 1" ]] || die "not an opennote-backup 1 archive"

expected_sha=$(sed -n 's/^db_dump_sha256=//p' "$stage/manifest.txt")
[[ $(sha256sum "$stage/db.dump" | cut -d ' ' -f 1) == "$expected_sha" ]] || die "db.dump does not match the manifest"

log "restoring the database"
# Without the extensions' comments: only an extension's owner may set them, and the
# database role need not own vector and pg_trgm (an administrator may have created them).
pg_restore --list "$stage/db.dump" | grep -v ' COMMENT - EXTENSION ' >"$stage/db.list"
pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
  --use-list "$stage/db.list" --dbname "$dburl" "$stage/db.dump"
expected_revision=$(sed -n 's/^alembic_revision=//p' "$stage/manifest.txt")
revision=$(psql -X -A -t -c 'select version_num from alembic_version' "$dburl")
[[ $revision == "$expected_revision" ]] || die "restored migration revision $revision, manifest says $expected_revision"

log "restored the backup of $(sed -n 's/^created=//p' "$stage/manifest.txt") (migration $revision)"
