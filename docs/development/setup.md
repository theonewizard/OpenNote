# Local Development Setup

How to set up a working copy and run the checks CI runs. Describes the repository as it stands at the end of Phase 0. Exact tool versions are in [versions.md](versions.md).

## Prerequisites

| Tool | Needed for |
|---|---|
| Git, GNU Make | everything |
| Python 3.13 or 3.14 (the versions CI tests) | backend, worker |
| Node.js 24 LTS with npm (`web/.npmrc` sets `engine-strict`, so npm refuses to install with a Node.js or npm outside `web/package.json`'s `engines`) | web app |
| Docker with Compose, or Podman with `podman compose` (supported by design but untested; only Docker has been exercised) | PostgreSQL and Valkey for integration tests; the full stack |
| macOS with Xcode and XcodeGen | Apple apps only |

If `python3` on your machine is another version, pass a suitable interpreter: `make bootstrap PYTHON=python3.13`.

## 1. Install dependencies

```bash
make bootstrap
```

This creates `.venv` at the repository root (`python3 -m venv .venv`), upgrades pip, checks with `pip install --dry-run` that `backend/constraints.txt` agrees with both requirements files (it stops with `backend/constraints.txt is stale: run make constraints` otherwise), installs `backend/requirements-dev.txt` (which includes `backend/requirements.txt`) into it with `-c backend/constraints.txt`, which pins every transitive dependency of the runtime requirements, and runs `npm ci` in `web/`. Python packages are only ever installed into `.venv` (`CLAUDE.md` §3); run tools as `.venv/bin/python`, `.venv/bin/pytest` and so on.

## 2. Configure the environment

Compose reads its variables from `infrastructure/compose/.env`. Create it from the template, which holds placeholders only:

```bash
cp infrastructure/compose/.env.example infrastructure/compose/.env
```

`.env` is git-ignored and must never be committed; put real secrets only there or in your secret store.

The backend reads settings from `OPENNOTE_`-prefixed environment variables. Each secret (`OPENNOTE_DATABASE_URL`, `OPENNOTE_VALKEY_URL`) can instead be read from a file named by `<NAME>_FILE`, of at most 64 KiB; an empty plain variable counts as unset, so the file is read.

| Variable | Form |
|---|---|
| `OPENNOTE_DATABASE_URL` | `postgresql+psycopg://<user>:<password>@<host>:5432/<database>` |
| `OPENNOTE_VALKEY_URL` | `redis://<host>:6379/0` |
| `OPENNOTE_VAULT_ROOT`, `OPENNOTE_HISTORY_ROOT` | writable directories |
| `OPENNOTE_LOG_LEVEL` | default `INFO` |
| `OPENNOTE_ENVIRONMENT` | `development`, `test` or `production`; default `production` |

The database URL uses SQLAlchemy's `postgresql+psycopg://` scheme (psycopg 3); Valkey speaks the Redis protocol, so its URL uses `redis://`.

## 3. Start PostgreSQL and Valkey

```bash
make up-deps
```

Starts only the `postgres` (with pgvector) and `valkey` services of `infrastructure/compose/compose.dev.yaml` on `127.0.0.1:5432` and `127.0.0.1:6379`. The first run builds the images.

- On its first start PostgreSQL creates the databases `opennote` and `opennote_test`, each with the `vector` and `pg_trgm` extensions, owned by the superuser `opennote` with password `opennote` (throwaway placeholders).
- Integration tests read `OPENNOTE_TEST_DATABASE_URL` and `OPENNOTE_TEST_VALKEY_URL`, whose defaults point at these services, so nothing needs to be set when you use `make up-deps`.
- The test database's name must end in `_test` (default `opennote_test`): the migration tests upgrade it and downgrade it to base, dropping the `vector` and `pg_trgm` extensions, so the integration tests refuse to run against any other database.
- The test Valkey database defaults to 1 (`redis://127.0.0.1:6379/1`) and must not be 0, the dev stack's: the worker tests delete the ping keys and the broker's default-queue, ack and heartbeat keys in it.
- Use `COMPOSE="podman compose"` with any Compose target to use Podman (untested; only Docker has been exercised).

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

Apple packages are tested with `swift test --package-path apple/Packages/<Package>`.

The web app's Playwright tests (`npm run test:e2e` in `web/`, section 9) build the app and serve it on port 4173 with `--strictPort`, never reusing a server already there, so only one e2e run per host at a time. `OPENNOTE_PW_EXECUTABLE`, read by `web/playwright.config.ts`, points Playwright at a Chromium already installed instead of the build `npx playwright install chromium` downloads.

## 5. Run the worker

With the variables of section 2 set and Valkey running:

```bash
cd backend && ../.venv/bin/python -m app.workers
```

It validates every `OPENNOTE_*` setting at start and, if any is missing or invalid, exits with one line naming the fields; it uses `OPENNOTE_VALKEY_URL` and `OPENNOTE_LOG_LEVEL`. One worker process with four threads takes jobs from Valkey and logs JSON lines on stdout. On SIGTERM or Ctrl-C it lets running jobs finish, waiting at most 50 s, then exits. Do not point it at the test Valkey database (section 3): the worker tests' jobs and key cleanup would collide with it.

### Run the API without containers

With `make up-deps` running and the variables of section 2 set (for its services, `postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote` and `redis://127.0.0.1:6379/0`), start the API as the api image does, then smoke-test it from the repository root in another shell:

```bash
cd backend && ../.venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --no-access-log \
  --log-config ../infrastructure/containers/api/logging.json
scripts/smoke-test.sh --api-only http://127.0.0.1:8000
```

The Phase 0 endpoints need no migration: `/readyz` checks only that PostgreSQL and Valkey answer and that the two directories are writable. The API serves no `/docs`, `/redoc` or `/openapi.json` (404); the contract is `docs/api/openapi.json` (section 8).

## 6. Run the full stack

With `infrastructure/compose/.env` created (section 2) and Docker or Podman running (only Docker has been exercised; Podman is supported by design and untested):

```bash
make up                                      # builds the images, then starts the stack
scripts/smoke-test.sh http://localhost:8080
make down
```

`make up` rebuilds the images (unchanged layers come from the build cache), starts `infrastructure/compose/compose.yaml` (web, api, worker, postgres, valkey) and waits until every service with a health check is healthy. The web app is on http://localhost:8080 and forwards `/api/`, `/healthz` and `/readyz` to the API, which is also on http://localhost:8000 (`scripts/smoke-test.sh --api-only http://localhost:8000`). The web container looks the API up at `api:8000` through the nameservers in its `/etc/resolv.conf`; `OPENNOTE_API_UPSTREAM` (host[:port]) names another upstream, such as a fully qualified service name on Kubernetes. Both ports listen on 127.0.0.1 only. Every container runs as a non-root user with a read-only root filesystem.

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
- nginx's error log (stderr, level warn) includes the request line, query string and all, when a proxied request fails. The OpenNote API takes credentials only in headers, never in query strings, so no token appears there.
- nginx sets `X-Forwarded-Proto` from its own connection and rate-limits `/healthz` and `/readyz` per client address. Both assume `web` is the edge: behind a TLS proxy the API is told `http` although the client used HTTPS, and all clients share the proxy's address and so one rate limit, until a trusted-proxy configuration exists.

## 7. Build the Apple apps

On macOS with Xcode 27.1 and XcodeGen 2.46.0 or newer, installed with `brew install xcodegen`:

```bash
swift test --package-path apple/Packages/OpenNoteCore      # and each other package in apple/Packages/
make apple-project                                         # writes apple/OpenNote.xcodeproj
xcodebuild -project apple/OpenNote.xcodeproj -scheme OpenNote-macOS -destination 'platform=macOS' -skipPackagePluginValidation build
xcodebuild -project apple/OpenNote.xcodeproj -scheme OpenNote-iOS -destination 'generic/platform=iOS Simulator' -skipPackagePluginValidation build
```

`-skipPackagePluginValidation` lets `xcodebuild` run swift-openapi-generator's build plugin in `OpenNoteAPI` (section 8). Without it the build fails with `"OpenAPIGenerator" is disabled` (the generator's FAQ); in the Xcode IDE the same error offers "Enable Plugin", then "Trust & Enable". `swift build` and `swift test` run the plugin without either.

`apple/project.yml` defines the app targets `OpenNote-macOS` (macOS 15 or later) and `OpenNote-iOS` (iOS and iPadOS 18 or later), each with a scheme of the same name, sharing `apple/Apps/Shared` and linking the five local packages `OpenNoteCore`, `OpenNoteStorage`, `OpenNoteAPI`, `OpenNoteSync` and `OpenNoteEditor`.

- Code signing is off (`CODE_SIGNING_ALLOWED: NO`, no development team), so these builds need no Apple developer account; running on a device needs signing, which the project does not set up yet.
- The generated project and the `Info.plist` files XcodeGen writes into `apple/Apps/macOS/` and `apple/Apps/iOS/` are git-ignored.
- Each package's `Package.resolved` is committed: the files are the first resolution in CI (the macOS job; the Linux job resolved `OpenNoteCore` and `OpenNoteStorage` to identical files), and both Apple CI jobs fail when `swift test` resolves to anything else. After changing a dependency, commit the `Package.resolved` files that `swift test` rewrites. The Xcode app builds resolve the package graph again, into a `Package.resolved` inside the git-ignored `apple/OpenNote.xcodeproj`, which the drift check cannot see; the committed per-package files pin what `swift test` resolves.
- `OpenNoteCore` and `OpenNoteStorage` use no Apple-only frameworks, so `swift test` runs them on Linux as well with the Swift 6.4.1 toolchain, where `OpenNoteCore` takes SHA-256 from swift-crypto instead of CryptoKit; the Linux job of the Apple CI workflow runs both in the `swift:6.4.1` image.

## 8. API contract

`docs/api/openapi.json` is generated from the backend and committed, together with the TypeScript types generated from it and a copy of it in the Swift package. A change to a route, parameter or payload regenerates all three in the same change (`CLAUDE.md` §14):

```bash
make openapi        # scripts/gen-openapi.sh, then scripts/gen-clients.sh
```

| File | Written by | From |
|---|---|---|
| `docs/api/openapi.json` | `scripts/gen-openapi.sh` | `create_app().openapi()` with placeholder settings (no service is contacted), keys sorted |
| `web/src/api/schema.d.ts` | `scripts/gen-clients.sh` | `openapi.json`, through `openapi-typescript` (`web/` devDependency, `--alphabetize`) |
| `apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.json` | `scripts/gen-clients.sh` | a byte-identical copy of `docs/api/openapi.json` (generated, do not edit; JSON carries no comment to say so); swift-openapi-generator's build plugin turns it into the Swift client on every build, as `openapi-generator-config.yaml` beside it says |

Both scripts need `make bootstrap` (`.venv` for the export, `web/node_modules` for the types), use no network, run from any directory and write the same bytes every time. The export stops with an error, writing nothing, when two operations share an operationId. Each operationId is the endpoint function's name (`healthz`, `readyz`, `get_meta`), so name an endpoint function after the client method it becomes. Its docstring is the operation's public description in the OpenAPI document and the generated clients, so write it for API users and keep implementation notes in `#` comments. Every operation documents a `default` response of type `application/problem+json` (`ProblemDetails`, RFC 9457). The web app has the generated types only: a fetch wrapper and the Zod schemas for query parameters arrive with the first endpoint that has them.

CI runs this drift check; run it before pushing an API change:

```bash
scripts/gen-openapi.sh && scripts/gen-clients.sh && git diff --exit-code docs/api/openapi.json web/src/api/schema.d.ts apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.json
```

It exits 1 and prints the difference when a committed file no longer matches the backend.

## 9. Continuous integration

GitHub Actions runs five workflows from `.github/workflows/` on every pull request, on pushes to `main`, `feature/**`, `fix/**`, `security/**` and `docs/**`, and on demand. They need no secrets beyond the `GITHUB_TOKEN` GitHub provides, with read-only permissions. The pinned actions, tools and runner images are in [versions.md](versions.md#continuous-integration). A newer push to a branch cancels that branch's running workflows; a run on `main` or from the schedule is never cancelled once it has started (GitHub still replaces a queued, not yet started run of the same workflow and branch with a newer one). A pull request from a `feature/**`, `fix/**`, `security/**` or `docs/**` branch runs every workflow twice, once for the push and once for the pull request: CI on a branch before its pull request exists is worth the extra minutes.

| Workflow | Runs | Locally |
|---|---|---|
| `backend` | A `constraints` job runs the constraints check of `make bootstrap` (section 1) on Python 3.14. The backend lines of `make bootstrap`, `make lint` and `make typecheck`, and `pytest` (unit and integration), on Python 3.13 and 3.14, against PostgreSQL 18 with pgvector and Valkey service containers; a separate job runs `make bootstrap`, `make openapi` and the drift check of section 8 | `make up-deps`, then `make lint typecheck test` |
| `web` | `npm ci`, `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, then the Playwright tests in Chromium | In `web/`: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`, then `npx playwright install chromium` once and `npm run test:e2e` |
| `apple` | On macOS with Xcode 27.1: `swift test` for each package, `xcodegen generate` and unsigned builds of both schemes. On Linux, in the Swift 6.4.1 image: `swift test` for `OpenNoteCore` and `OpenNoteStorage`. Both jobs fail when `swift test` changes or adds a `Package.resolved` file | Section 7 |
| `containers` | Builds the images, starts the full stack with migrations and runs both smoke tests, checks the migration and that the worker is running and was never restarted, stops the stack and starts it again with the same checks, runs the api image and the full stack (worker check included) as an arbitrary UID in group 0, starts the dev stack and checks the test database's extensions, then scans each image with Trivy (HIGH and CRITICAL with a fix fail the job); also every Monday at 06:00 UTC, so the images are rebuilt and rescanned at least weekly. A failing scan fails the run; nothing rebuilds automatically. A second job, `manifests`, runs `helm lint --strict` on three chart variants and renders them, the kustomize base and the OpenShift overlay, at Kubernetes 1.29.0 (the chart's floor; a 1.28.9 render must fail), checks the renders for what kubeconform cannot see (no Secret, `secretKeyRef` or `secretRef`; `fsGroup`, `fsGroupChangePolicy` and a read-only root filesystem on the pods, and no service account token; web's API upstream), then validates them with kubeconform | Section 6; `manifests`: [docs/deployment/kubernetes.md, "Validation"](../deployment/kubernetes.md#validation) |
| `security` | gitleaks over the pushed or pull-request commits (gitleaks-action scans a push's commits as the push event lists them, at most 20, and a pull request's first 30 commits; the whole history on demand and in the Monday run on `main`), `pip-audit --strict` over both requirements files and `backend/constraints.txt`, `bandit -r backend/app`, `npm audit --audit-level=high` in `web/`, and a Trivy scan of the repository for vulnerable dependencies, misconfigurations and secrets; also every Monday at 06:00 UTC | `.venv/bin/pip-audit -r backend/requirements.txt -r backend/requirements-dev.txt -r backend/constraints.txt --strict`, `.venv/bin/bandit -r backend/app -q`, `cd web && npm audit --audit-level=high` |

The workflows upload no artefacts: findings, drift diffs and installed versions are in the job logs. A gitleaks finding that is not a secret is recorded by its fingerprint in `.gitleaksignore`, with the reason.

Dependabot (`.github/dependabot.yml`) proposes updates every Monday, minor and patch updates grouped into one pull request per ecosystem and majors one by one, with its default `dependencies` label, for the pip requirements in `backend/`, the npm packages in `web/`, the GitHub Actions, the base images of the four Containerfiles and the five Swift packages. Whoever merges a Dependabot pull request updates the versions.md rows it changes and, for a pip bump, runs `make constraints` in the same change: Dependabot edits the requirements files only, and the `constraints` check fails until `backend/constraints.txt` agrees with them. It does not update the following, which are updated by hand together with their versions.md rows:

- the service and job container images in the workflows (the pgvector, Valkey and Swift images; its github-actions updater skips `services:`, `container:` and `docker://` images);
- the Trivy and gitleaks versions the workflows install;
- the kubeconform image, the Helm release set in setup-helm's `version` input, the CRD-catalog commit and the Kubernetes schema versions of the `manifests` job;
- the pre-commit hook revs and the Node.js release in `.nvmrc`;
- the packages and source releases installed inside the Containerfiles.

Optional local hooks run checks on each commit: large files, merge-conflict markers, YAML syntax, final newlines, trailing whitespace, private keys, ruff on `backend/`, and gitleaks on the staged changes (`.pre-commit-config.yaml`):

```bash
.venv/bin/pre-commit install          # once per clone
.venv/bin/pre-commit run --all-files  # every file, not only the staged ones
```

## Other targets

`make help` lists every target with a one-line description; `make up` and `make down` are described in section 6, `make apple-project` in section 7 and `make openapi` in section 8.
