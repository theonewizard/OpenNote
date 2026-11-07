# Backup and restore

OpenNote's state lives in three places that must be backed up together: the PostgreSQL database, the history volume (every revision's bytes and the revision logs) and the vault volume (the Markdown files). `opennote-backup` takes all three into one encrypted file while OpenNote keeps running; `opennote-restore` puts such a file back into an empty database and empty volumes. Both are shell scripts in the `opennote-postgres` image (`infrastructure/backup/`), because they need PostgreSQL 18's `pg_dump` and `pg_restore`.

## Keys

Backups are encrypted to an OpenPGP public key; only the matching private key decrypts them. The public key is all that ever sits next to OpenNote: a stolen backup volume, or a compromised cluster, does not reveal the notes. Keep the private key offline (a password manager, a hardware token, a safe), with a passphrase, and keep a copy of it somewhere that does not fail with the server. Without it no backup can be restored.

```bash
gpg --quick-gen-key "OpenNote backups <you@example.org>" default default never
gpg --armor --export "OpenNote backups" > backup-public-key.asc
gpg --armor --export-secret-keys "OpenNote backups" > backup-private-key.asc   # store offline
```

## What a backup holds

`opennote-<UTC time>.tar.gz.gpg`, with a `.sha256` beside it: a tar archive, gzip-compressed, encrypted to the public key (gpg's integrity protection included), holding

| Member | Content |
|---|---|
| `FORMAT` | `opennote-backup 1` |
| `manifest.txt` | time, database migration revision, `pg_dump` version, SHA-256 of `db.dump` |
| `history-log/<vault id>/log/*.jsonl` | the revision logs, copied first |
| `db.dump` | `pg_dump --format=custom` without owners or privileges, one consistent snapshot |
| `history/<vault id>/…` | history objects and the recovery area of deleted files, without the live logs |
| `vaults/…` | the vault directories, symbolic links stored as links |

`opennote-backup` keeps the newest `OPENNOTE_BACKUP_KEEP` backups (default 7; 0 keeps all) in its directory and deletes older ones. A failed run removes its partial file and exits non-zero.

## Consistency

The backup is taken while OpenNote writes. OpenNote makes each revision durable in a fixed order: history object, database (the commit point), revision log, vault file ([sync protocol](../architecture/sync-protocol.md) §2.3, `app/sync/commit.py`). `opennote-backup` reads in an order that matches: the logs first, then the database snapshot, then the history objects, then the vaults. So in every backup:

- the logs hold no revision the database lacks (they were copied before the snapshot);
- every revision in the database has its history object (objects are read after the snapshot, and never removed);
- a vault file is the database's revision of it, or newer.

That is a state a crash between two commit steps can leave, and OpenNote's recovery (`Committer.recover`) repairs it: it appends the revisions the logs lack, and commits a vault file that is newer than the database as an edit from the server's file system, so it is kept rather than overwritten. tar reports a file or directory that changed while it was read (exit 1); the backup logs a warning and continues. That happens routinely when a directory gains a file during the backup, which is harmless for the reasons above. OpenNote replaces files by rename, so only a file edited in place outside OpenNote can be captured half-written; recovery then commits it as an edit, and its previous revision stays in the history.

In Phase 1 the server does not yet run recovery on start by itself (the API that wires the storage engine in arrives with Phase 2). The restore drill below runs it explicitly; until Phase 2, run `scripts/backup_drill.py verify` in the api container after a restore (see [Restore with Compose](#restore-with-compose)).

## Compose

```bash
mkdir -p infrastructure/compose/backups && sudo chown 1001:0 infrastructure/compose/backups
cp ~/backup-public-key.asc infrastructure/compose/backup-public-key.asc
docker compose -f infrastructure/compose/compose.yaml run --rm backup
```

The `backup` service reads the vault and history volumes read-only and writes to `infrastructure/compose/backups/` (or `OPENNOTE_BACKUP_HOST_DIR`), which UID 1001 or group 0 must be able to write. `OPENNOTE_BACKUP_PUBLIC_KEY` names another public key file. Both paths are git-ignored inside `infrastructure/compose/`. Schedule it with cron or a systemd timer on the host, and copy the backups off the host.

### Restore with Compose

Restore into a stopped stack with empty volumes; the restore refuses a database that has tables or a volume that is not empty, so it never overwrites anything.

```bash
compose="docker compose -f infrastructure/compose/compose.yaml"
$compose down -v                       # deletes the volumes: only on a host you are restoring
$compose up -d --wait postgres valkey
OPENNOTE_BACKUP_PRIVATE_KEY=~/backup-private-key.asc \
  $compose run --rm restore /backups/opennote-20261107T020000Z.tar.gz.gpg
OPENNOTE_MIGRATE_ON_START=true $compose up -d --wait
$compose exec -T api python - verify < scripts/backup_drill.py
```

A passphrase-protected key needs `OPENNOTE_BACKUP_PASSPHRASE_FILE` pointing at a file mounted into the `restore` container. The restore checks the `.sha256`, decrypts the whole file once before writing anything (a damaged file or the wrong key stops it there), writes the vaults, history objects and logs straight into the volumes, restores the database and compares the migration revision with the manifest.

## Kubernetes and OpenShift

The chart runs `opennote-backup` as a CronJob with `backup.enabled=true`:

```bash
kubectl -n opennote create configmap opennote-backup-key --from-file=public.asc=backup-public-key.asc
helm upgrade opennote infrastructure/helm/opennote --namespace opennote --reuse-values \
  --set backup.enabled=true --set backup.schedule='0 2 * * *'
kubectl -n opennote create job --from=cronjob/opennote-backup opennote-backup-now   # one now
```

The CronJob mounts the vault and history volumes read-only next to the running pods, so they must be `ReadWriteMany` (the chart's default); it reads only the database URL from the Secret, as a file. Backups go to the PersistentVolumeClaim `<fullname>-backups` (20 GiB, ReadWriteOnce, kept on `helm uninstall`) or to `backup.persistence.existingClaim`. Put that claim on storage that does not fail with the data volumes, or copy the backups off the cluster. The database dump is staged in an `emptyDir` of `backup.tmpSize` (2 GiB). Values: `backup.enabled`, `schedule`, `keep`, `publicKeyConfigMap`, `tmpSize`, `persistence.existingClaim`, `persistence.storageClassName`, `persistence.size`, `resources`; the image is `image.postgresRepository` at the chart's tag.

### Restore on Kubernetes

Restore into a new namespace (or after deleting the release's volumes and emptying the database): install the chart there with `api.replicas=0` and `worker.replicas=0` so nothing writes, put the backup on a volume, create a Secret with the private key, and run `opennote-restore` once as a Pod with the release's volumes mounted read-write:

```bash
kubectl -n opennote-restore create secret generic opennote-backup-private-key --from-file=private.asc=backup-private-key.asc
kubectl -n opennote-restore apply -f restore-pod.yaml   # below
kubectl -n opennote-restore logs -f pod/opennote-restore
kubectl -n opennote-restore delete pod/opennote-restore secret/opennote-backup-private-key
helm -n opennote-restore upgrade opennote infrastructure/helm/opennote --reuse-values --set api.replicas=1 --set worker.replicas=1
```

`restore-pod.yaml`, for a release named `opennote` with its backups on `opennote-backups`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: opennote-restore
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: restore
      image: ghcr.io/theonewizard/opennote-postgres:0.1.0
      command: [opennote-restore, /backups/opennote-20261107T020000Z.tar.gz.gpg]
      env:
        - {name: OPENNOTE_DATABASE_URL_FILE, value: /run/secrets/opennote/OPENNOTE_DATABASE_URL}
        - {name: OPENNOTE_VAULT_ROOT, value: /var/lib/opennote/vaults}
        - {name: OPENNOTE_HISTORY_ROOT, value: /var/lib/opennote/history}
        - {name: OPENNOTE_BACKUP_PRIVATE_KEY_FILE, value: /run/opennote-backup-key/private.asc}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: {drop: [ALL]}
      volumeMounts:
        - {name: vaults, mountPath: /var/lib/opennote/vaults}
        - {name: history, mountPath: /var/lib/opennote/history}
        - {name: backups, mountPath: /backups, readOnly: true}
        - {name: secrets, mountPath: /run/secrets/opennote, readOnly: true}
        - {name: key, mountPath: /run/opennote-backup-key, readOnly: true}
        - {name: tmp, mountPath: /tmp}
  volumes:
    - {name: vaults, persistentVolumeClaim: {claimName: opennote-vaults}}
    - {name: history, persistentVolumeClaim: {claimName: opennote-history}}
    - {name: backups, persistentVolumeClaim: {claimName: opennote-backups, readOnly: true}}
    - {name: secrets, secret: {secretName: opennote}}
    - {name: key, secret: {secretName: opennote-backup-private-key}}
    - {name: tmp, emptyDir: {sizeLimit: 2Gi}}
```

The private key is in the cluster only for the restore; delete its Secret afterwards. On Kubernetes add `fsGroup: 1001` to the pod's `securityContext` (OpenShift assigns one).

## Restore drill

`scripts/backup-drill.sh` runs on every `containers` workflow run, on the Compose stack built from the branch:

1. It commits revisions through OpenNote's commit path (`scripts/backup_drill.py seed`: 20 notes, three updates each, two moves, two deletes, an attachment) and takes a backup with the stack running.
2. It takes a second backup while another process keeps committing (`churn`).
3. For each backup it deletes every volume, restores onto empty ones, starts the stack, runs recovery and checks that the revision log equals the database, every revision's bytes are in the history store and match their hash, and every live file is in the vault with the database's hash; the smoke test must pass. The first backup must restore to exactly the state before it: the same revisions, logs, live files and vault bytes.

Run it locally with Docker after `docker compose -f infrastructure/compose/compose.yaml build`; it deletes the stack's volumes.

A restore drill on your own installation is the only proof that your backups and your private key work: restore the newest backup into a scratch namespace or host now and then, and run `verify` there.
