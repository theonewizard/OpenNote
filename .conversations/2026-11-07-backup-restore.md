# 2026-11-07 — P8-04 backup and restore

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Workstream 3 of the parallel plan; rulings R-P8-020 onwards (the workstream's numbering is explained in [2026-11-07-openshift-deployment.md](2026-11-07-openshift-deployment.md)).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |

The coordinator's brief: P8-04 backup and restore of vault, history and DB, with P8-06 and P8-08; UBI images, no privileged containers, arbitrary UIDs.

## Rulings

- R-P8-020: the roadmap lists M5 as P8-04's dependency, but the storage engine (Phase 1) already fixes everything a backup must respect: the commit order and the recovery that repairs a crash between steps. P8-04 is built now against that; the restore drill exercises the real commit path and recovery, so a Phase 2 change to either fails the drill rather than silently breaking backups.
- R-P8-021: backups are online and consistent by read order instead of by stopping writers: revision logs, then one `pg_dump` snapshot, then history objects, then vaults. The commit order (object, database, log, vault) makes every such backup a state recovery already repairs (log ⊆ database, objects ⊇ database, vault ≥ database). The drill checks this with a backup taken during about 60 commits per second. A filesystem snapshot was not required: RWX volumes rarely offer one, and Compose hosts may not have one.
- R-P8-022: encryption is OpenPGP public-key (`gpg --recipient-file`, no keyring), so the host or cluster that takes backups holds only the public key. gpg is in UBI's repositories and known to every Linux administrator; `age` would need a binary from outside UBI. The restore decrypts the whole file once before writing, because gpg checks integrity only at the end of the stream.
- R-P8-023: the tools are two bash scripts in the opennote-postgres image, not a new image and not Python in the api image: they need PostgreSQL 18's `pg_dump`/`pg_restore`, which only that image has (UBI's own PostgreSQL client is older, and `pg_dump` refuses a newer server). The image gains `tar`, `gzip`, `gnupg2` and `findutils` and the two vault mount points, so a fresh volume mounted there first is group-0 writable.
- R-P8-024: restore refuses a database with tables and non-empty directories instead of offering an overwrite flag: restoring is rare and destructive, and wiping is a separate, deliberate step the operator takes.
- R-P8-025: restore drops the extensions' comments from the dump's restore list, because only an extension's owner may set them and a managed database's role often does not own vector and pg_trgm.
- R-P8-026: the chart's CronJob is opt-in (`backup.enabled=false`), mounts the vault and history claims read-only next to the running pods (so RWX, the chart's default), and keeps its own backups claim on uninstall. A Kubernetes run of it (`kubectl create job --from=cronjob/...` in the kind deployment test) is added once the P8-06 deployment test is on `main`, to keep the two pull requests independent.
- R-P8-027: the drill helper `scripts/backup_drill.py` writes through `Committer` (the only write path until Phase 2's API) and runs inside the api image; it is a test tool, not shipped in an image.

## Output

Branch `feature/backup-restore` in `.worktrees/backup/`: `infrastructure/backup/opennote-backup.sh` and `opennote-restore.sh`, the postgres Containerfile changes, the Compose `backup` and `restore` services, the chart's backup CronJob and values, `scripts/backup-drill.sh` and `scripts/backup_drill.py`, the drill step in the containers workflow, `docs/deployment/backup.md`, the rows in ROADMAP.md, IMPLEMENTATION_STATUS.md, setup.md and kubernetes.md, the threat model's backup line, and this record.

## 2026-11-14 follow-up

- R-P8-028: `main` merged into the branch after PostgreSQL 18.7 (#49) and UBI 10.3 (#51): the postgres image keeps `tar gzip gnupg2 findutils` on top of main's 18.7 packages; the drill step runs before main's new DAST step; Compose keeps the `backup`/`restore` services beside main's fixed network.
- R-P8-029: retention (P5-07, Phase 5 PR #63, stacked on `feature/resumable-blobs`, not on `main` yet) deletes old revisions and then unlinks the objects no revision refers to, by file age only (GRACE 7 days from the object's mtime). A prune between the backup's snapshot and its object pass would leave revisions in the backup without bytes. `opennote-backup` now holds a shared session-level advisory lock, key 5714577825249056080 ("ONBACKUP" in ASCII), from before the logs are copied until it exits; retention is asked to take the same key with `pg_try_advisory_xact_lock` before it removes objects and to skip that step while a backup holds it (message sent to the Phase 5 thread). Tested locally against PostgreSQL 16: while held, an exclusive try returns false and a second shared lock true; after the script exits the lock is free; an unreachable database makes the script stop before reading anything.
- R-P8-029 follow-up: the Phase 5 thread matched it in PR #55 (head 4f90e7b, ruling R-P5-014): retention takes `pg_try_advisory_xact_lock(5714577825249056080)` in the transaction that reads referenced hashes and sweeps objects, and leaves objects for its next run when not granted, with an integration test holding the shared lock.

## 2026-11-20 follow-up

- R-P8-040: with #38 (kind deploy test) and #40 (backup) both on `main`, the follow-up promised in R-P8-026 lands: `scripts/kind-deploy-test.sh` installs the chart with `backup.enabled=true` and `image.postgresRepository=opennote-postgres`, makes a throwaway gpg key pair in its work directory and puts the public key in the `opennote-backup-key` ConfigMap, then runs `kubectl create job backup-now --from=cronjob/opennote-backup` after the network policy probe, waits up to 300 s for it to complete and requires the `wrote /backups/opennote-….tar.gz.gpg` log line. `helm uninstall` must also keep `opennote-backups`. kubernetes.md's "Backups" line now links backup.md. No restore runs on kind; the Compose drill covers restore.
- R-P8-041: the first CI run of R-P8-040 found a real chart limitation. kind's StorageClass binds on first consumer (WaitForFirstConsumer), nothing mounts `<fullname>-backups` before the first backup, so `helm install --wait` with `backup.enabled=true` waited until its 10 min timeout ("PVC is not Bound"). The same happens on any WaitForFirstConsumer class (many CSI classes). backup.md now says so and gives the way out: create the claim and set `backup.persistence.existingClaim`, or install without `--wait`. The test does the former (claim `backups`, 1 GiB). The chart is unchanged; whether it should stop creating the claim itself is Flemming's call.
