# Disaster recovery

What to do when the PostgreSQL database of an OpenNote server is lost or unusable (P8-05). If a database backup exists and is newer than the last commit you care about, restore it instead: it brings back everything, accounts included (`docs/deployment/backup.md`, P8-04). The procedure here is for when there is no usable database backup.

## What survives without the database

OpenNote keeps a vault's data in two places outside PostgreSQL (storage contract §7, sync protocol §2.3):

| Store | Holds | Rebuilt into |
|---|---|---|
| Vault folder | The current Markdown files and attachments: authoritative | `files`, the note index (titles, tags, links, search) |
| History store `<history_root>/<vault_id>/` | Every committed revision's bytes and a JSONL revision log (sequence, file id, revision, path, hash, device, operation, time) | `vaults`, `revisions`, `vault_seq`, `files` |

A commit writes the history object and its log line before it answers the client, so the log holds every revision a client was told about.

These are **not** rebuilt, because only the database held them: user accounts, devices, refresh tokens, sessions and personal access tokens; vault memberships and vault settings; idempotency records; the conflict list; the audit log. After a rebuild every user signs in again (local accounts are re-created, OIDC users are created at their next sign-in), every device is registered again, and an administrator adds the vault members back.

## Procedure

Run each step where the backend runs (the api image, or a working copy with `.venv`), with the server's `OPENNOTE_*` settings. Keep the API, the worker and the vault watcher stopped until step 5.

1. **Keep the files.** Copy the vault root and the history root aside before anything else, or snapshot their volumes.
2. **Create an empty database** and apply the migrations:

   ```bash
   alembic upgrade head        # in backend/; the api image runs it at start
   ```

3. **Create an administrator:**

   ```bash
   python -m app.auth.admin create-user --admin admin   # password on stdin
   ```

4. **Rebuild the vaults** from the history store. Look at the plan first:

   ```bash
   python -m app.sync.rebuild --dry-run
   python -m app.sync.rebuild --owner admin
   ```

   Each line of output is one vault as JSON: `rebuilt`, `skip` (with the reason in `note`) or `failed`. A vault's folder is found by its `.opennote/config.json`, else as the direct child of the vault root holding at least 90 % of the files its log says are live. A vault that matches neither is skipped: give its folder with `--map VAULT_ID=FOLDER` and run again. Vaults already in the database are skipped, so the command can be repeated. `--owner` makes that user the owner of every rebuilt vault.

5. **Start the services.** The API and the vault watcher (`python -m app.vaults`) first run recovery on each vault, then the watcher scans every folder: files changed, added or removed while the database was down are committed as new revisions (device `server-fs`). Nothing in a vault folder is overwritten with older history.
6. **Restore access.** Add vault members (`PUT /api/v1/vaults/{id}/members/{user_id}`), ask users to sign in and register their devices again. Vault ids, file ids, revisions and sequence numbers are rebuilt as they were, so a client's sync cursor stays valid; a client that pulled revisions the log does not hold cannot exist (the log line is written before the answer). An operation a client retries from before the loss is not recognised as a duplicate (its idempotency record is gone), but it carries its base revision, so it is merged or kept as a conflict copy, never applied twice silently.

## Checking the result

`python -m app.sync.rebuild` refuses a log with a repeated sequence number and checks every history object against its hash while it reads sizes; a `failed` line names the vault and the error.

Retention prunes old revisions and removes their history objects but leaves the log as it is. The rebuild leaves out a logged revision whose object is gone, so it restores the revisions retention kept. A file's current revision is never pruned, and if its object is missing the vault fails instead of being rebuilt without that file.

To compare with a known state, the backup drill helper (`scripts/backup_drill.py fingerprint` and `verify`, P8-04) prints every vault's revisions, revision log and live files, and checks that the log, the history objects and the vault agree with the database.

## Verified

- Integration tests (`backend/tests/integration/sync/test_rebuild.py`): the rows rebuilt from the log equal the rows before the loss (vault, revisions, sequence, files, notes, tags, links, search documents), including moves, deletes, a path reused after a delete and an attachment; edits made while the database was down become new revisions; folder matching by config, by files and by `--map`; the command-line tool with `--dry-run` and `--owner`.
- By hand on 2026-11-14 with the P8-04 drill helper: seed (85 revisions, 19 live files), fingerprint, drop and re-create the database, migrate, create the admin, `python -m app.sync.rebuild --owner admin`: the fingerprint matched in full and `verify` passed; the API then listed the vault's notes, served a note's bytes and found them by search.
- Not yet in CI against the Compose stack: that drill is added to `scripts/backup-drill.sh` once P8-04's pull request is merged.
