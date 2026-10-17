# Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A monorepo where the backend, worker, web app and Apple packages build and test, the backend stack starts healthy in UBI containers under Docker Compose and Podman, and CI enforces all of it (milestone M0).

**Architecture:** Modular-monolith FastAPI backend (one image, `api` and `worker` process types), PostgreSQL + pgvector, Valkey, React/Vite web app served by nginx, five local Swift packages plus XcodeGen-generated macOS/iOS app targets. No product features: only skeletons, health, configuration, deny-by-default auth wiring and the tooling around them.

**Tech Stack:** Python (latest stable available on UBI, ≥ 3.13), FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2, Alembic, psycopg 3, Dramatiq, pytest; React, TypeScript, Vite, Tailwind CSS, shadcn/ui, Vitest, Playwright; Swift 6, SwiftPM, XcodeGen; Red Hat UBI, Docker Compose, Podman, Helm, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-17-opennote-architecture-design.md` (with ADRs and contracts it links). Repository rules: `CLAUDE.md`.

## Global Constraints

- Use the latest stable version of every tool and library (`CLAUDE.md` §1.8); design §6 versions are floors. Record resolved versions in `docs/development/versions.md`.
- Python only via the repository-root `.venv` (`.venv/bin/python|pip|pytest`, `CLAUDE.md` §3); deps pinned with `==` in `backend/requirements.txt` and `backend/requirements-dev.txt` (ADR-0014).
- Use npm with a committed `package-lock.json` for `web/` (`CLAUDE.md` §4).
- Every route depends on `get_current_principal` or `get_api_key`, except paths in `KEYLESS_ROUTES`; `assert_routes_authenticated(app)` runs at startup in `backend/app/api/main.py` (`CLAUDE.md` §12).
- Errors are RFC 9457 `application/problem+json` with generic `detail`; exceptions are logged, never returned (`CLAUDE.md` §13).
- Containers: UBI bases from `registry.access.redhat.com`, non-root UID 1001 group 0, arbitrary-UID safe, read-only root FS, graceful SIGTERM, health checks, no secrets (`CLAUDE.md` §5, ADR-0010).
- Nothing generated is committed: `.venv/`, `node_modules/`, `__pycache__/`, `.vite/`, `apple/OpenNote.xcodeproj`, `.worktrees/`, `.env`, coverage output (`CLAUDE.md` §21).
- Work on `feature/phase-0-foundation` in `.worktrees/foundation/`; squash merge after CI is green.
- Run the `ponytail-audit` review before the PR is marked ready (`CLAUDE.md` §28).

## Review Focus

- Settings with a missing or malformed `OPENNOTE_DATABASE_URL`: process must exit with a clear one-line error, not a stack trace containing the URL (password leak). Test in Task 2.
- `/readyz` when PostgreSQL or Valkey is down: must return 503 quickly (timeout ≤ 2 s per dependency), not hang the probe. Test in Task 3.
- Container started with a random UID (`--user 1000870000:0`) and read-only root FS: must start and pass health. Test in Task 6.
- A new router added without an auth dependency: app startup must fail. Test in Task 2.
- `SIGTERM` during a running worker job: worker finishes or requeues the job and exits within the grace period. Test in Task 4.

---

### Task 1: Repository skeleton and version resolution (P0-02)

**Files:**
- Create: `.gitignore`, `.editorconfig`, `Makefile`, `README.md` (replace one-line stub), `docs/development/versions.md`, `docs/development/setup.md`, empty package directories per spec §6 with `.gitkeep` only where a directory must exist before code lands
- Create: `docs/design/` (already holds the design document)

- [ ] **Step 1:** Resolve latest stable versions of Python (and the newest offered by a UBI Python image), PostgreSQL, pgvector, Valkey, Node LTS, React, Vite, TypeScript, Tailwind, Swift/Xcode, XcodeGen, UBI 9/10 image tags; write the table to `docs/development/versions.md` with source URL and date per row.
- [ ] **Step 2:** Write `.gitignore` covering every entry in `CLAUDE.md` §21 plus `.venv/`, `node_modules/`, `apple/OpenNote.xcodeproj/`, `apple/.build/`, `**/.build/`, `.worktrees/`, `playwright-report/`, `test-results/`, `htmlcov/`, `.coverage`.
- [ ] **Step 3:** Write `Makefile` targets: `help`, `bootstrap` (venv + pip install, `npm ci`), `lint`, `typecheck`, `test`, `build`, `up`, `down`, `openapi`, `apple-project`. Each target delegates to the subproject; no logic beyond that.
- [ ] **Step 4:** Verify: `make help` prints all targets. (`make bootstrap` is verified in Task 11, once the requirements files and `package-lock.json` exist.)
- [ ] **Step 5:** Commit `chore: repository skeleton and resolved tool versions`.

### Task 2: Backend application skeleton (P0-03)

**Files:**
- Create: `backend/pyproject.toml`, `backend/requirements.txt`, `backend/requirements-dev.txt`
- Create: `backend/app/__init__.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`, `backend/app/core/problems.py`, `backend/app/auth/dependencies.py`, `backend/app/api/main.py`, `backend/app/api/health.py`, `backend/app/api/meta.py`
- Create: empty module packages `backend/app/{vaults,notes,attachments,search,sync,tasks,calendar,ai,workers}/__init__.py`
- Test: `backend/tests/unit/test_config.py`, `test_problems.py`, `test_route_auth.py`, `test_health.py`, `test_meta.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings, prefix `OPENNOTE_`, fields `database_url: PostgresDsn`, `valkey_url: RedisDsn`, `vault_root: Path`, `history_root: Path`, `log_level: str = "INFO"`, `environment: Literal["development","test","production"]`; each secret also readable from `<NAME>_FILE`); `get_settings() -> Settings` (cached).
- Produces: `create_app(settings: Settings | None = None) -> FastAPI` in `app/api/main.py`, which mounts every router in the module-level list `ROUTERS: list[APIRouter]` and then runs the auth guard.
- Produces: `KEYLESS_ROUTES: frozenset[tuple[str, str]]` of `(method, path)`; `assert_routes_authenticated(app: FastAPI) -> None` raising `RuntimeError` naming each offending route.
- Produces: `get_current_principal(...) -> Principal` and `get_api_key(...) -> Principal` in `app/auth/dependencies.py`; in Phase 0 both raise a 401 problem (no auth backend yet), which is the correct deny-by-default behaviour.
- Produces: `problem_response(status: int, title: str, type_slug: str, detail: str | None = None, instance: str | None = None) -> JSONResponse`; exception handlers for `HTTPException`, `RequestValidationError` and `Exception` (logs with request ID, returns generic 500).

- [ ] **Step 1: Write failing tests**

```python
def test_unauthenticated_route_fails_startup(monkeypatch):
    rogue = APIRouter()
    @rogue.get("/api/v1/oops")
    def oops(): return {}
    monkeypatch.setattr(main, "ROUTERS", [*main.ROUTERS, rogue])
    with pytest.raises(RuntimeError, match="/api/v1/oops"):
        create_app(test_settings())

def test_keyless_routes_are_exactly_the_documented_set():
    assert {p for _, p in KEYLESS_ROUTES} == {"/healthz", "/readyz", "/api/v1/meta"}

def test_unhandled_exception_returns_generic_problem(client_with_failing_route):
    r = client_with_failing_route.get("/api/v1/boom", headers=auth)
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    assert "Traceback" not in r.text and "boom-secret" not in r.text

def test_invalid_database_url_message_does_not_leak_password(monkeypatch):
    monkeypatch.setenv("OPENNOTE_DATABASE_URL", "postgresql://u:hunter2@/")  # malformed host
    with pytest.raises(SettingsError) as e: load_settings()
    assert "hunter2" not in str(e.value)

def test_meta_reports_versions(client):
    assert client.get("/api/v1/meta").json() == {
        "server_version": app_version(), "api_versions": ["v1"],
        "sync_protocol_versions": [1], "login_methods": []}
```

(`/api/v1/meta/path-rules` joins `KEYLESS_ROUTES` in P1-04 and the OAuth/OIDC routes from the API contract §2 in P2-02, each when the route exists.)

- [ ] **Step 2:** Run `.venv/bin/pytest backend/tests/unit -q`; expected: failures for missing modules.
- [ ] **Step 3:** Implement the interfaces above. `create_app` mounts routers, installs handlers, adds request-ID middleware, and calls `assert_routes_authenticated` before returning. JSON logs via stdlib `logging` with a formatter and a redaction filter for `authorization`, `cookie`, `token`, `password` keys.
- [ ] **Step 4:** Run `.venv/bin/pytest backend -q`, `.venv/bin/ruff check backend`, `.venv/bin/ruff format --check backend`, `.venv/bin/mypy backend/app`; expected: all pass.
- [ ] **Step 5:** Commit `feat(backend): app skeleton with deny-by-default routes and problem details`.

### Task 3: Database configuration and readiness (P0-04)

**Files:**
- Create: `backend/app/core/db.py`, `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/0001_extensions.py`
- Modify: `backend/app/api/health.py`
- Test: `backend/tests/integration/test_migrations.py`, `backend/tests/integration/test_readyz.py`

**Interfaces:**
- Consumes: `Settings.database_url`, `Settings.valkey_url`.
- Produces: `engine_from_settings(s: Settings) -> AsyncEngine`, `session_scope() -> AsyncIterator[AsyncSession]`; `check_database(timeout: float = 2.0) -> bool`, `check_valkey(timeout: float = 2.0) -> bool`.
- Migration `0001` creates extensions `vector` and `pg_trgm`; downgrade drops them.

- [ ] **Step 1: Write failing tests**

```python
def test_upgrade_then_downgrade_roundtrip(pg_url):
    alembic_upgrade(pg_url, "head"); assert extensions(pg_url) >= {"vector", "pg_trgm"}
    alembic_downgrade(pg_url, "base"); assert not extensions(pg_url) & {"vector", "pg_trgm"}

async def test_readyz_503_within_3s_when_db_unreachable(client_with_dead_db):
    t = time.monotonic(); r = await client_with_dead_db.get("/readyz")
    assert r.status_code == 503 and time.monotonic() - t < 3
    assert r.json() == {"status": "fail"}

async def test_readyz_200_when_all_up(client): assert (await client.get("/readyz")).json() == {"status": "ok"}
```

- [ ] **Step 2:** Run against PostgreSQL + Valkey from `infrastructure/compose/compose.dev.yaml` (`make up-deps`); expected: FAIL.
- [ ] **Step 3:** Implement with SQLAlchemy async + psycopg 3; readiness checks run concurrently with `asyncio.wait_for`. `/readyz` also checks `vault_root` and `history_root` are writable directories.
- [ ] **Step 4:** Run `.venv/bin/pytest backend/tests/integration -q`; expected: PASS.
- [ ] **Step 5:** Commit `feat(backend): database engine, alembic baseline, readiness checks`.

### Task 4: Worker skeleton (P0-05)

**Files:**
- Create: `backend/app/workers/broker.py`, `backend/app/workers/jobs.py`, `backend/app/workers/__main__.py`
- Test: `backend/tests/integration/test_worker.py`

**Interfaces:**
- Produces: `broker_from_settings(s: Settings) -> dramatiq.Broker`; actor `ping(token: str) -> None` that records `token` in Valkey key `opennote:ping:<token>` with 60 s TTL; entrypoint `python -m app.workers`.

- [ ] **Step 1: Write failing tests**

```python
def test_ping_job_completes(worker, valkey):
    ping.send("t1"); worker.join()
    assert valkey.get("opennote:ping:t1") == b"1"

def test_sigterm_during_job_exits_within_grace(worker_process, valkey):
    worker_process.enqueue_slow_job("t2", seconds=2)
    assert worker_process.wait_job_started("t2", timeout=10)   # start barrier
    worker_process.sigterm()
    assert worker_process.wait(timeout=10) == 0
    assert valkey.get("opennote:ping:t2") == b"1" or job_is_queued("t2")
```

- [ ] **Step 2:** Run; expected: FAIL.
- [ ] **Step 3:** Implement; re-check Dramatiq maintenance status first (ADR-0009). If it is unmaintained, stop and record a superseding ADR before choosing another library.
- [ ] **Step 4:** Run `.venv/bin/pytest backend/tests/integration/test_worker.py -q`; expected: PASS.
- [ ] **Step 5:** Commit `feat(worker): dramatiq worker with valkey broker and graceful shutdown`.

### Task 5: Web skeleton (P0-06)

**Files:**
- Create: `web/` via `npm create vite@latest` (React + TS template), then `web/src/app/App.tsx`, `web/src/app/Layout.tsx` (three panes: navigation, note list, editor placeholder, status bar), `web/src/lib/utils.ts` (`cn`), `web/components.json` (shadcn), Tailwind config per current Tailwind major
- Test: `web/tests/unit/Layout.test.tsx`, `web/tests/e2e/smoke.spec.ts`, `web/playwright.config.ts`

**Interfaces:**
- Produces: npm scripts `dev`, `build`, `preview`, `lint`, `typecheck`, `test`, `test:e2e`.
- Produces: `<Layout />` with landmark roles `navigation`, `region` (aria-label "Note list"), `main`, `contentinfo` (status text "Not connected").

- [ ] **Step 1: Write failing tests**

```tsx
it("renders the three panes and status bar", () => {
  render(<Layout />);
  expect(screen.getByRole("navigation")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Note list" })).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("contentinfo")).toHaveTextContent("Not connected");
});
```
```ts
test("app loads at phone width without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 }); await page.goto("/");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  expect(overflow).toBe(false);
});
```

- [ ] **Step 2:** Run `npm test`; expected: FAIL.
- [ ] **Step 3:** Implement layout with Tailwind; add shadcn `button` only (proves the setup, nothing more).
- [ ] **Step 4:** Run `npm run lint && npm run typecheck && npm test && npm run build && npm run test:e2e`; expected: all pass.
- [ ] **Step 5:** Commit `feat(web): vite react skeleton with three-pane layout`.

### Task 6: Container images and Compose (P0-07)

**Files:**
- Create: `infrastructure/containers/api/Containerfile`, `infrastructure/containers/web/Containerfile`, `infrastructure/containers/web/nginx.conf`, `infrastructure/containers/postgres/Containerfile`, `infrastructure/containers/postgres/entrypoint.sh`, `infrastructure/containers/valkey/Containerfile`
- Create: `infrastructure/compose/compose.yaml`, `infrastructure/compose/compose.dev.yaml`, `infrastructure/compose/.env.example`
- Create: `scripts/smoke-test.sh`
- Test: `scripts/smoke-test.sh` run in CI

**Interfaces:**
- Produces: services `api` (port 8000), `worker`, `web` (port 8080, proxies `/api`, `/healthz`, `/readyz` to `api`), `postgres`, `valkey`; volumes `vaults`, `history`, `pgdata`; `.env.example` with placeholder values only.
- Produces: `scripts/smoke-test.sh <base_url>` exits 0 when `/healthz`, `/readyz` and `/api/v1/meta` return 200 and `GET /` returns the web shell.

- [ ] **Step 1:** Write `scripts/smoke-test.sh` and run it against nothing; expected: non-zero exit.
- [ ] **Step 2:** Write Containerfiles (multi-stage, UBI, versions from `versions.md`), Compose files with health checks, `read_only: true`, `tmpfs` for `/tmp`, `security_opt: no-new-privileges`, `cap_drop: [ALL]`, and an API entrypoint that runs `alembic upgrade head` only when `OPENNOTE_MIGRATE_ON_START=true` (default false in production).
- [ ] **Step 3:** Run `docker compose -f infrastructure/compose/compose.yaml up -d --wait` then `scripts/smoke-test.sh http://localhost:8080`; expected: exit 0. Repeat with `podman compose`.
- [ ] **Step 4:** Run `docker run --rm --user 1000870000:0 --read-only --tmpfs /tmp opennote-api:dev python -c "import app"` and the full stack with `user: "1000870000:0"` override; expected: healthy.
- [ ] **Step 5:** Commit `feat(infra): UBI images and compose stack`.

### Task 7: Apple skeleton (P0-08)

**Files:**
- Create: `apple/Packages/OpenNoteCore/Package.swift`, `Sources/OpenNoteCore/OpenNoteCore.swift`, `Tests/OpenNoteCoreTests/OpenNoteCoreTests.swift`; same shape for `OpenNoteStorage`, `OpenNoteAPI`, `OpenNoteSync`, `OpenNoteEditor`
- Create: `apple/project.yml`, `apple/Apps/macOS/OpenNoteApp.swift`, `apple/Apps/iOS/OpenNoteApp.swift`, `apple/Apps/Shared/RootView.swift`

**Interfaces:**
- Produces: `OpenNoteCore.version: String` and `ContentHash.sha256(_ data: Data) -> String` returning `"sha256:<hex>"` (first real shared rule, matches storage contract §6).
- Package dependencies: Storage → Core; Sync → Core, Storage, API; Editor → Core. Platforms `.macOS(.v15)`, `.iOS(.v18)` (decision D3). Swift tools version = current stable, Swift 6 language mode.

- [ ] **Step 1: Write failing test**

```swift
@Test func sha256MatchesStorageContract() {
    #expect(ContentHash.sha256(Data("hello\n".utf8)) ==
        "sha256:5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03")
}
```

- [ ] **Step 2:** `swift test --package-path apple/Packages/OpenNoteCore`; expected: FAIL (missing symbol).
- [ ] **Step 3:** Implement with CryptoKit on Apple platforms and `swift-crypto` only if Linux builds need it (prefer `#if canImport(CryptoKit)`; if Linux needs a dependency, record it in versions.md).
- [ ] **Step 4:** On macOS: `swift test` for every package; `xcodegen generate --spec apple/project.yml`; `xcodebuild -scheme OpenNote-macOS build` and `xcodebuild -scheme OpenNote-iOS -destination 'generic/platform=iOS Simulator' build`; expected: all succeed. On Linux: Core and Storage `swift test` pass.
- [ ] **Step 5:** Commit `feat(apple): swift packages and xcodegen app targets`.

### Task 8: OpenAPI export and client generation (P0-12)

**Files:**
- Create: `scripts/gen-openapi.sh`, `scripts/gen-clients.sh`, `docs/api/openapi.json`, `web/src/api/schema.d.ts` (generated, committed so web builds without the backend), `apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.yaml` symlink-free copy + `openapi-generator-config.yaml`
- Test: CI drift step

**Interfaces:**
- Produces: `scripts/gen-openapi.sh` writes `docs/api/openapi.json` from `create_app().openapi()` with sorted keys; `scripts/gen-clients.sh` regenerates TS types and copies the spec to the Swift package.

- [ ] **Step 1:** Run `scripts/gen-openapi.sh && git diff --exit-code docs/api/openapi.json`; expected after first generation and commit: exit 0; after adding a dummy route locally: exit 1 (then remove it).
- [ ] **Step 2:** Run `npm run typecheck` in `web/` and `swift build` in `OpenNoteAPI` on macOS; expected: PASS.
- [ ] **Step 3:** Commit `feat(api): openapi export and generated client types`.

### Task 9: CI and security baseline (P0-09, P0-10)

**Files:**
- Create: `.github/workflows/backend.yml`, `web.yml`, `apple.yml`, `containers.yml`, `security.yml`, `.github/dependabot.yml`, `SECURITY.md`, `.pre-commit-config.yaml`

**Interfaces:**
- `backend.yml`: Ubuntu, services `pgvector` and `valkey`, steps venv → pip install → ruff → mypy → pytest (unit + integration) → OpenAPI drift.
- `web.yml`: Node LTS, `npm ci`, lint, typecheck, test, build, Playwright with Chromium.
- `apple.yml`: `macos-latest`, current stable Xcode, `swift test` per package, XcodeGen, `xcodebuild` macOS + iOS Simulator; `ubuntu-latest` job runs Core/Storage `swift test` in the official Swift container.
- `containers.yml`: build images, Compose up, smoke test, arbitrary-UID run, Trivy image scan.
- `security.yml`: gitleaks, pip-audit, bandit, `npm audit --audit-level=high`, Trivy filesystem scan; weekly schedule as well as on PR.

- [ ] **Step 1:** Push the branch; expected: all five workflows run.
- [ ] **Step 2:** Fix until all workflows are green; never disable a check to get green (`CLAUDE.md` §9).
- [ ] **Step 3:** Commit `ci: workflows for backend, web, apple, containers and security`.

### Task 10: Kubernetes, Helm and OpenShift skeletons (P0-11)

**Files:**
- Create: `infrastructure/kubernetes/base/{kustomization.yaml,api.yaml,worker.yaml,web.yaml,pvc.yaml}`, `infrastructure/helm/opennote/{Chart.yaml,values.yaml,templates/*}`, `infrastructure/openshift/{kustomization.yaml,route.yaml}`

**Interfaces:**
- Pods: `runAsNonRoot: true`, no fixed `runAsUser` (OpenShift assigns), `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`, `readOnlyRootFilesystem: true`, liveness `/healthz`, readiness `/readyz`, resource requests/limits from `values.yaml`. PostgreSQL and Valkey are external dependencies referenced by Secret (in-cluster charts are out of scope for Phase 0).

- [ ] **Step 1:** Run `helm lint infrastructure/helm/opennote` and `helm template … | kubeconform -strict -summary`; expected: PASS. Add both to `containers.yml`.
- [ ] **Step 2:** Run `kustomize build infrastructure/openshift | kubeconform -strict`; expected: PASS (Route schema via OpenShift CRD catalog).
- [ ] **Step 3:** Commit `feat(infra): kubernetes, helm and openshift skeletons`.

### Task 11: Close Phase 0

- [ ] **Step 1:** In a fresh clone run `make bootstrap` and check `git status --porcelain` is empty, then run `make lint typecheck test build` and confirm all CI workflows are green on the PR.
- [ ] **Step 2:** Run the `ponytail-audit` review; apply only findings relevant to this branch.
- [ ] **Step 3:** Update `docs/IMPLEMENTATION_STATUS.md` (what was verified where, including Apple results from CI) and set P0-02…P0-12 to `COMPLETED` in `docs/ROADMAP.md` only for items whose acceptance criteria were observed passing.
- [ ] **Step 4:** Record the session's prompts in `.conversations/`.
- [ ] **Step 5:** Commit `docs: phase 0 status`, open PR, squash merge after review.
