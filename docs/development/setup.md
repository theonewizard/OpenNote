# Local Development Setup

How to set up a working copy and run the checks CI runs. Describes the repository as it stands at the end of Phase 0; parts that a later Phase 0 task adds are marked "added in Phase 0 Task N" (see the [Phase 0 plan](../superpowers/plans/2026-10-17-phase-0-foundation-plan.md)). Exact tool versions are in [versions.md](versions.md).

## Prerequisites

| Tool | Needed for |
|---|---|
| Git, GNU Make | everything |
| Python 3.13 or 3.14 (the versions CI tests) | backend, worker |
| Node.js 24 LTS with npm | web app |
| Docker with Compose, or Podman with `podman compose` | PostgreSQL and Valkey for integration tests; the full stack |
| macOS with Xcode and XcodeGen | Apple apps only |

If `python3` on your machine is another version, pass a suitable interpreter: `make bootstrap PYTHON=python3.13`.

## 1. Install dependencies

```bash
make bootstrap
```

This creates `.venv` at the repository root (`python3 -m venv .venv`), upgrades pip, installs `backend/requirements-dev.txt` (which includes `backend/requirements.txt`) into it, and runs `npm ci` in `web/`. Python packages are only ever installed into `.venv` (`CLAUDE.md` §3); run tools as `.venv/bin/python`, `.venv/bin/pytest` and so on. The requirements files are added in Phase 0 Task 2, `web/package-lock.json` in Task 5.

## 2. Configure the environment

Compose reads its variables from `infrastructure/compose/.env`. Create it from the template, which holds placeholders only (added in Phase 0 Task 6):

```bash
cp infrastructure/compose/.env.example infrastructure/compose/.env
```

`.env` is git-ignored and must never be committed; put real secrets only there or in your secret store.

The backend reads settings from `OPENNOTE_`-prefixed environment variables (added in Phase 0 Task 2). Each secret can instead be read from a file named by `<NAME>_FILE`.

| Variable | Form |
|---|---|
| `OPENNOTE_DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:5432/<database>` |
| `OPENNOTE_VALKEY_URL` | `redis://<host>:6379/0` |
| `OPENNOTE_VAULT_ROOT`, `OPENNOTE_HISTORY_ROOT` | writable directories |
| `OPENNOTE_LOG_LEVEL` | default `INFO` |
| `OPENNOTE_ENVIRONMENT` | `development`, `test` or `production` |

The database URL uses SQLAlchemy's `postgresql+psycopg://` scheme (psycopg 3); Valkey speaks the Redis protocol, so its URL uses `redis://`.

## 3. Start PostgreSQL and Valkey

```bash
make up-deps
```

Starts only the `postgres` (with pgvector) and `valkey` services of `infrastructure/compose/compose.dev.yaml` (added in Phase 0 Task 6) on `127.0.0.1:5432` and `127.0.0.1:6379`. The first run builds the images. On its first start PostgreSQL creates the databases `opennote` and `opennote_test`, each with the `vector` and `pg_trgm` extensions, owned by the superuser `opennote` with password `opennote` (throwaway placeholders). Integration tests read `OPENNOTE_TEST_DATABASE_URL` and `OPENNOTE_TEST_VALKEY_URL`, whose defaults point at these services, so nothing needs to be set when you use `make up-deps` (added in Phase 0 Task 3). The test database's name must end in `_test` (default `opennote_test`): the migration tests upgrade it and downgrade it to base, dropping the `vector` and `pg_trgm` extensions, so the integration tests refuse to run against any other database. The test Valkey database defaults to 1 (`redis://127.0.0.1:6379/1`) and must not be 0, the dev stack's: the worker tests delete the ping keys and the broker's default-queue, ack and heartbeat keys in it (added in Phase 0 Task 4). Use `COMPOSE="podman compose"` with any Compose target to use Podman.

## 4. Lint, type-check, test

```bash
make lint typecheck test
```

| Target | Runs |
|---|---|
| `lint` | `ruff check` and `ruff format --check` in `backend/`; `npm run lint` in `web/` |
| `typecheck` | `mypy app` in `backend/`; `npm run typecheck` in `web/` |
| `test` | `pytest` in `backend/` (unit and integration, so `make up-deps` first); `npm test` in `web/` |
| `build` | `npm run build` in `web/` |

Apple packages are tested with `swift test --package-path apple/Packages/<Package>` (added in Phase 0 Task 7).

## 5. Run the worker

With the variables of section 2 set and Valkey running (added in Phase 0 Task 4):

```bash
cd backend && ../.venv/bin/python -m app.workers
```

It validates every `OPENNOTE_*` setting at start and, if any is missing or invalid, exits with one line naming the fields; it uses `OPENNOTE_VALKEY_URL` and `OPENNOTE_LOG_LEVEL`. One worker process with four threads takes jobs from Valkey and logs JSON lines on stdout. On SIGTERM or Ctrl-C it lets running jobs finish, waiting at most 50 s, then exits. Do not point it at the test Valkey database (section 3): the worker tests' jobs and key cleanup would collide with it.

## 6. Run the full stack

With `infrastructure/compose/.env` created (section 2) and Docker or Podman running (added in Phase 0 Task 6):

```bash
make up                                      # builds the images, then starts the stack
scripts/smoke-test.sh http://localhost:8080
make down
```

`make up` rebuilds the images (unchanged layers come from the build cache), starts `infrastructure/compose/compose.yaml` (web, api, worker, postgres, valkey) and waits until every service with a health check is healthy. The web app is on http://localhost:8080 and forwards `/api/`, `/healthz` and `/readyz` to the API, which is also on http://localhost:8000 (`scripts/smoke-test.sh --api-only http://localhost:8000`). Both ports listen on 127.0.0.1 only. Every container runs as a non-root user with a read-only root filesystem.

- Migrations are not applied on start by default. Apply them deliberately with `docker compose -f infrastructure/compose/compose.yaml run --rm api alembic upgrade head`. `OPENNOTE_MIGRATE_ON_START=true make up`, or that line in `.env`, makes the API run `alembic upgrade head` first instead; enable it for one API instance only.
- The worker has no health check. When stopped it gets 60 s: it lets running jobs finish for up to 50 s, and a job still running after that is delivered again later (at-least-once).
- Valkey keeps nothing on disk, so restarting it loses queued jobs.
- Data lives in the volumes `opennote_vaults`, `opennote_history` and `opennote_pgdata`, which `make down` keeps (`docker compose -f infrastructure/compose/compose.yaml down -v` deletes them). PostgreSQL reads `POSTGRES_*` only when it initialises an empty volume, so a password changed in `.env` later must also be changed in the database.

### Security posture of the default stack

The stack is set up for local use. Before it serves anyone else, know what it does not do yet:

- The API and the worker connect to PostgreSQL as the cluster's superuser (`POSTGRES_USER`) until a dedicated application role lands in Phase 1.
- Valkey has no password. It is reachable only from the other containers, because compose.yaml publishes no port for it.
- All five services share one Compose network, so each container can reach every other one.
- `web` serves plain HTTP. Anything beyond local use needs a TLS proxy in front of it, with real secrets in `.env`.
- nginx sets `X-Forwarded-Proto` from its own connection and rate-limits `/healthz` and `/readyz` per client address. Both assume `web` is the edge: behind a TLS proxy the API is told `http` although the client used HTTPS, and all clients share the proxy's address and so one rate limit, until a trusted-proxy configuration exists.

## Other targets

| Target | What it does |
|---|---|
| `make up` | Start the full stack from `infrastructure/compose/compose.yaml` (web on port 8080, API on 8000; added in Phase 0 Task 6) |
| `make down` | Stop the full stack and the `up-deps` services |
| `make openapi` | Regenerate `docs/api/openapi.json` and the TypeScript and Swift clients (added in Phase 0 Task 8); required in the same change as any API change (`CLAUDE.md` §14) |
| `make apple-project` | Generate `apple/OpenNote.xcodeproj` from `apple/project.yml` with XcodeGen (macOS only; added in Phase 0 Task 7). The generated project is git-ignored |
| `make help` | List all targets |
