# Operator guide

How to install, run and upgrade OpenNote on one host with Docker Compose (P8-07). Kubernetes and OpenShift are in [kubernetes.md](kubernetes.md). Calling the API is in [using-the-api.md](../api/using-the-api.md).

OpenNote is pre-release. Run it with real notes only if you keep your own copy of the vault folders.

## What runs

| Service | Image | Does |
|---|---|---|
| `web` | `opennote-web` (nginx) | Serves the web app on port 8080 and forwards `/api/`, `/healthz` and `/readyz` to `api` |
| `api` | `opennote-api` | The HTTP API on port 8000 |
| `worker` | `opennote-api` | Background jobs from the Valkey queue |
| `watcher` | `opennote-api` | Commits files changed directly in a vault folder (edits from Obsidian, a file sync tool, a script) |
| `postgres` | `opennote-postgres` (PostgreSQL with pgvector) | The database: accounts, tokens, the index. Everything except accounts can be rebuilt from the vault and history |
| `valkey` | `opennote-valkey` | The job queue. Keeps nothing on disk |

All images are built from Red Hat UBI 10 (`infrastructure/containers/`). UBI 10 needs an x86-64-v3 CPU (Intel Haswell, AMD Excavator or later) on x86. Every container runs as a non-root user with a read-only root filesystem and no capabilities.

Data lives in three volumes:

| Volume | Holds | Lose it and |
|---|---|---|
| `opennote_vaults` | The Markdown vaults, the source of truth | the notes are gone. Back it up |
| `opennote_history` | Every revision of every file, compressed | version history is gone, and the database can no longer be rebuilt |
| `opennote_pgdata` | PostgreSQL | rebuild it with `python -m app.sync.rebuild`, but accounts and tokens are only in the database backup |

## Install

You need Docker with Compose v2 and the repository checked out. Podman is supported by design and untested.

```bash
cp infrastructure/compose/.env.example infrastructure/compose/.env
chmod 600 infrastructure/compose/.env
```

Edit `.env`. The file explains every variable. For anything beyond a test install:

- Set `POSTGRES_PASSWORD` to a long random value, and the same value in `OPENNOTE_DATABASE_URL`. Or put them in files and use `POSTGRES_PASSWORD_FILE` and `OPENNOTE_DATABASE_URL_FILE` with Compose secrets.
- Set `OPENNOTE_ENVIRONMENT=production`.
- Leave `OPENNOTE_MIGRATE_ON_START=false` so that upgrades apply migrations when you decide to.

Build, migrate and start:

```bash
make up                                                                           # build and start, wait for health
docker compose -f infrastructure/compose/compose.yaml run --rm api alembic upgrade head
scripts/smoke-test.sh http://localhost:8080
```

Create the first administrator. The password (12 characters or more) is read from the terminal without echo, never from the command line:

```bash
docker compose -f infrastructure/compose/compose.yaml exec api \
  python -m app.auth.admin create-user --admin --display-name "Alice" alice
```

Then create a vault with `POST /api/v1/vaults` (an administrator only, see [using-the-api.md](../api/using-the-api.md)). With `"directory"` it registers an existing folder under the vault root instead of creating an empty one, which is how you bring in an existing Obsidian vault: copy it into the `opennote_vaults` volume first. The watcher imports it on its first full scan.

## Serving other hosts

Both published ports listen on 127.0.0.1 only, and `web` speaks plain HTTP. To serve other machines, put a TLS proxy (nginx, HAProxy, Caddy, Traefik) on the host in front of `127.0.0.1:8080`. Known gaps, from [setup.md, "Security posture of the default stack"](../development/setup.md#security-posture-of-the-default-stack):

- Behind a proxy the API sees `http`, not `https`, and every client shares the proxy's address and so one per-address rate limit. Raise `OPENNOTE_RATE_LIMIT_PER_IP` to suit.
- Valkey has no password. It is reachable only inside the Compose network.

## Upgrade

```bash
git pull
make up                                                                           # rebuilds changed images, restarts
docker compose -f infrastructure/compose/compose.yaml run --rm api alembic upgrade head
scripts/smoke-test.sh http://localhost:8080
```

Back up before an upgrade that brings a migration (`backend/migrations/versions/`). `make down` stops the stack and keeps the volumes; `docker compose -f infrastructure/compose/compose.yaml down -v` deletes them.

## Health and logs

- `GET /healthz` answers when the process is up; `GET /readyz` also checks the database, Valkey and the vault and history folders. Both are keyless.
- `docker compose -f infrastructure/compose/compose.yaml logs -f api` shows the logs. They never contain passwords or tokens. Every response carries `X-Request-ID`, which the API logs with the request.
- `OPENNOTE_LOG_LEVEL` sets the level (INFO by default).

## Backup and recovery

- Backup and restore of all three volumes: [backup-restore.md](backup.md).
- Rebuilding a lost database from the vault and history: [disaster-recovery.md](disaster-recovery.md).
