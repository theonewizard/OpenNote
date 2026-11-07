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
