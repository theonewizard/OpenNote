# OpenNote Roadmap

Status values: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `TESTING`, `COMPLETED` (design §15.19). Priorities follow design §2.1: P0 initial usable product, P1 feature-complete productivity, P2 advanced. Architecture: [spec](superpowers/specs/2026-10-17-opennote-architecture-design.md). Durations are planning assumptions from design §13 and are not commitments.

Phase order follows design §15.7 with the sync prototype added to Phase 1 ([ADR-0004](architecture/adr/0004-phase-order-and-early-sync-prototype.md)). A phase starts when its predecessor's milestone acceptance criteria pass.

## Phase 0 — Foundation (M0)

Milestone M0: repository builds; backend starts in containers; Apple packages and app targets compile (verified on a macOS CI runner); web compiles; CI runs automated tests; ADRs recorded.

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P0-01 | Architecture spec, ADRs, contracts, sync protocol, testing strategy, threat model, roadmap | — | P0 | Reviewed and approved by Flemming | COMPLETED: merged to `main` in pull requests #1 and #2 (2026-10-17); Flemming started Phase 0 with "go" |
| P0-02 | Repository skeleton: structure per spec §6, `.gitignore`, `.editorconfig`, README, LICENSE (AGPL-3.0, added with the plan), Makefile, `docs/development/versions.md` with resolved latest stable versions | P0-01 | P0 | `make help` lists targets; `git status` clean after `make bootstrap` | COMPLETED: in a fresh clone `make help` listed the targets and `git status --porcelain` was empty after `make bootstrap` (2026-10-18, [status](IMPLEMENTATION_STATUS.md#fresh-clone-check)) |
| P0-03 | Backend skeleton: `.venv`, pinned requirements, FastAPI app factory, settings, JSON logging, `/healthz`, `/readyz`, `/api/v1/meta`, RFC 9457 handler, `assert_routes_authenticated` + `KEYLESS_ROUTES` | P0-02 | P0 | `pytest`, `ruff`, `mypy --strict` pass; startup fails when an unauthenticated route is added (test) | COMPLETED: [backend run](https://github.com/theonewizard/OpenNote/actions/runs/39140717151) (ruff, mypy strict, 104 tests on Python 3.13 and 3.14, the unauthenticated-route test among them) |
| P0-04 | Database configuration: SQLAlchemy 2 engine/session, Alembic with initial migration enabling `vector` and `pg_trgm` | P0-03 | P0 | Migration upgrades and downgrades against PostgreSQL in CI; `/readyz` reports DB state | COMPLETED: [backend run](https://github.com/theonewizard/OpenNote/actions/runs/39140717151) (migration upgrade and downgrade, and the `/readyz` tests, against PostgreSQL 18 with pgvector) |
| P0-05 | Worker skeleton: Dramatiq + Valkey, one no-op health job, graceful SIGTERM | P0-03 | P0 | Integration test enqueues and completes the job against Valkey | COMPLETED: [backend run](https://github.com/theonewizard/OpenNote/actions/runs/39140717151) (the worker tests against Valkey 9.1.2) |
| P0-06 | Web skeleton: Vite + React + TS + Tailwind + shadcn/ui, three-pane placeholder layout, Vitest and Playwright smoke | P0-02 | P0 | `npm run lint`, `typecheck`, `test`, `build` pass; Playwright smoke passes | COMPLETED: [web run](https://github.com/theonewizard/OpenNote/actions/runs/39140716872) |
| P0-07 | Container images (UBI per ADR-0010) and Compose (`compose.yaml`, `compose.dev.yaml`) for api, worker, web, postgres, valkey | P0-03, P0-04, P0-05, P0-06 | P0 | `podman compose up -d` and `docker compose up -d` reach healthy; smoke test passes running as arbitrary UID with read-only root FS | TESTING: the Docker half passes ([containers run](https://github.com/theonewizard/OpenNote/actions/runs/39140716862): healthy stack, smoke tests, arbitrary UID with read-only root FS); `podman compose` has never been run |
| P0-08 | Apple skeleton: five SPM packages with one test each, `project.yml`, macOS and iOS app targets showing an empty SwiftUI shell | P0-02 | P0 | `swift test` per package and `xcodebuild` for macOS + iOS Simulator pass on macOS CI runner; Core/Storage also pass on Linux | COMPLETED: [apple run](https://github.com/theonewizard/OpenNote/actions/runs/39140716926) (macOS with Xcode 27.1, and Linux) |
| P0-09 | CI: GitHub Actions for backend, web, apple, containers, security; branch protection recommendation documented | P0-03…P0-08, P0-12 | P0 | All workflows green on the Phase 0 PR | TESTING: all five workflows are green on the branch's pushes (the runs cited in this table); the Phase 0 pull request's own runs are not observed yet |
| P0-10 | Security baseline: gitleaks, pip-audit, npm audit, Trivy, bandit in CI; `SECURITY.md`; log redaction filter | P0-09 | P0 | Scans run in CI with zero *fixable* critical/high findings (narrowed from "zero critical/high" on 2026-11-01, Flemming's decision; findings without a fix are not counted) | COMPLETED: met by the [security run](https://github.com/theonewizard/OpenNote/actions/runs/39140716878) and the Trivy image scans of the [containers run](https://github.com/theonewizard/OpenNote/actions/runs/39140716862); every Trivy gate runs with `--ignore-unfixed`, which is that criterion, and since 2026-11-01 a report step next to each gate writes the findings without a fix to the run's Summary tab without gating them. The Monday rescan of 2026-10-26 ([containers run](https://github.com/theonewizard/OpenNote/actions/runs/40320960413)) then failed on a fixable CRITICAL in the pinned `ubi-minimal` base of all four images (`ca-certificates`, CVE-2026-114406), which the gate is for; pull request #18 (merged 2026-11-01) moved all four images to the current build of the tag ([IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md#open-items)). gitleaks passes with one reviewed false positive allowlisted in `.gitleaksignore` |
| P0-11 | Kubernetes (kustomize), Helm chart and OpenShift overlay skeletons for api/worker/web | P0-07 | P1 | `helm lint`, `kubeconform` pass; pod security `restricted` profile satisfied | COMPLETED: `manifests` job of the [containers run](https://github.com/theonewizard/OpenNote/actions/runs/39140716862) (`helm lint --strict`, kubeconform at 1.29.0 and `master`, and the render checks: no Secret, `secretKeyRef` or `secretRef`, the `fsGroup` and `fsGroupChangePolicy` counts); `restricted` checked by hand with a throwaway program on k8s.io/pod-security-admission that is not in the repository (0 forbidden in five renders; run by the Task 10 implementer and re-reviewer, and again on `3fab73b`); a repeatable CI check is an [open item](IMPLEMENTATION_STATUS.md#open-items) |
| P0-12 | OpenAPI export + drift check; TypeScript and Swift client generation scripts | P0-03, P0-06, P0-08 | P0 | CI fails when `docs/api/openapi.json` is stale; generated clients compile | COMPLETED: the failing path was observed locally (fresh clone, 2026-10-18: the drift check exits 1 with a stale document) and the passing path in CI (`openapi drift` job of the [backend run](https://github.com/theonewizard/OpenNote/actions/runs/39140717151)); the clients compile in the web and apple runs |

## Phase 1 — Vault storage engine + sync prototype (M1)

Milestone M1: corpus round-trips byte-identically; external changes detected; renames keep identity; sync simulation invariants hold over 10,000 seeds.

Task-level plan: [Phase 1 plan](superpowers/plans/2026-11-01-phase-1-storage-sync-plan.md) (decisions D9–D11 taken 2026-11-01: PostgreSQL for the prototype, Python 3.14 floor, one-week time box).

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P1-01 | Vault registry and `.opennote/config.json` (create, discover, open existing Obsidian vault without writing) | P0-04 | P0 | Opening an existing vault writes nothing (checked by tree hash) | TESTING: `test_open_existing_vault_writes_nothing` (tree digest of paths, bytes, modes and mtimes) passes locally; CI run on the Phase 1 pull request pending |
| P1-02 | Byte-preserving note reader/writer: BOM, encodings, line endings, frontmatter split | P1-01 | P0 | Corpus round-trip is byte-identical | TESTING: `tests/compatibility/test_corpus_roundtrip.py` byte-identical for every corpus case locally; CI run pending |
| P1-03 | Round-trip YAML metadata editor (tags, aliases, `opennote:`) | P1-02 | P0 | Edits change only the target node; invalid YAML refused safely | TESTING: `tests/unit/notes/test_frontmatter.py` (only the edited key's lines change; invalid YAML raises `FrontmatterInvalid`, body stays editable) passes locally; CI run pending |
| P1-04 | Path rules: NFC, case-fold collisions, forbidden names, containment | P1-01 | P0 | Traversal fuzz corpus rejected; `meta/path-rules` served | TESTING: `tests/unit/vaults/test_paths.py` and `test_fsio_containment.py` (Hypothesis traversal fuzz, symlink escapes) and `test_path_rules_endpoint.py` pass locally; CI run pending |
| P1-05 | Identity registry and rename detection | P1-02, P1-11 | P0 | External rename keeps identity; no `id` written on open | TESTING: `tests/integration/test_identity.py` (external rename keeps the file id, no `id` written) passes locally; CI run pending |
| P1-06 | Link, embed and tag extraction; Obsidian link resolution | P1-02 | P0 | Corpus `expected.json` matches | TESTING: `tests/compatibility/test_corpus_extraction.py` matches every `expected.json` locally; CI run pending |
| P1-07 | Atomic writes with external-change guard | P1-02 | P0 | Crash-injection test leaves either old or new bytes, never partial; concurrent external edit is not clobbered | TESTING: `tests/unit/vaults/test_atomic_write.py` (crash injection at each step leaves old or new bytes; a concurrent external save is preserved) passes locally; a real power loss is not tested; CI run pending |
| P1-08 | Watcher (watchdog) + reconciliation scan + loop suppression | P1-07 | P0 | External create/edit/move/delete detected within 2 s; watcher overflow recovered by scan | TESTING: `tests/integration/test_watch.py` (create, edit, move, delete seen within 2 s; overflow and a dead observer recovered by a scan) passed 20 of 20 consecutive local runs; CI run pending |
| P1-09 | Attachment handling (classification, hashing, size limits) | P1-04 | P0 | Attachments indexed; bytes never modified | TESTING: `tests/unit/vaults/test_scan.py` and the index tests (attachments classified, hashed in 1 MiB chunks, never written) pass locally; CI run pending |
| P1-10 | Compatibility corpus and property-based tests | P1-02 | P0 | Corpus cases from testing strategy §3 present and passing | TESTING: the corpus cases of testing strategy §3 are in `tests/compatibility/` and pass locally, with Hypothesis property tests in the unit suite; CI run pending |
| P1-11 | Index schema (files, notes, tags, links) rebuildable from the vault | P0-04 | P0 | Drop + rebuild gives identical index | TESTING: `tests/integration/test_index_rebuild.py` (drop and rebuild of the derived tables gives an identical index) passes locally; CI run pending |
| P1-12 | Sync protocol prototype (commit path, merge, conflicts, tombstones, pull/push) + simulation harness | P1-05, P1-07, P1-13 | P0 | Invariants I1–I6 hold over 10,000 seeds | TESTING: 10,000 seeds (0 to 9,999) run locally by `make sync-sim SEEDS=10000`: zero violations over seeds 0 to 9,999 on `4673673` (224 tests passed, 1 h 11 min wall); 500 seeds run in every backend CI job; the first nightly 10,000-seed run waits for the merge to `main` |
| P1-13 | History store (content-addressed objects + JSONL log) | P1-02 | P0 | Every commit retrievable; metadata rebuildable from log | TESTING: `tests/unit/sync/test_history.py` and the commit tests (every revision readable from history; the log matches the `revisions` rows) pass locally; CI run pending |

## Phase 2 — Backend API (M2)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P2-01 | API infrastructure: problem details, ETag/If-Match, idempotency keys, cursor pagination, request IDs | P0-03 | P0 | Convention tests for 412/428/idempotent replay | NOT_STARTED |
| P2-02 | Auth: OAuth 2.0 code + PKCE, local login (Argon2id), OIDC upstream, refresh rotation, devices, PATs, web cookie + CSRF | P2-01 | P0 | Auth matrix tests; revocation works; no route without auth | NOT_STARTED |
| P2-03 | Vault endpoints + ACL roles | P2-02, P1-01 | P0 | Authorization matrix tests | NOT_STARTED |
| P2-04 | Note endpoints (list, create, metadata, content, move, metadata edit, delete) on the sync commit path | P2-03, P1-12 | P0 | Stale writes rejected; bytes preserved through API | NOT_STARTED |
| P2-05 | Folder endpoints | P2-04 | P0 | Folder move is one batch of revisions | NOT_STARTED |
| P2-06 | Attachment endpoints (upload, range download, type sniffing) | P2-03, P1-09 | P0 | Upload validation tests; Range works | NOT_STARTED |
| P2-07 | Tags endpoint | P2-04 | P0 | Counts match corpus | NOT_STARTED |
| P2-08 | Search: grammar parser, PostgreSQL FTS + trigram, vault scoping | P2-04 | P0 | Grammar tests; p95 < 500 ms on 100k-note fixture | NOT_STARTED |
| P2-09 | Audit log and rate limiting | P2-02 | P0 | Events recorded; 429 with headers | NOT_STARTED |
| P2-10 | OpenAPI completeness, Schemathesis contract tests, generated clients | P2-04…P2-08, P0-12 | P0 | Schemathesis passes; clients compile | NOT_STARTED |

## Phase 3 — Web application (M3)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P3-01 | Login/logout UI | P2-02 | P0 | Playwright login flow | NOT_STARTED |
| P3-02 | Three-pane layout, notebook (folder) navigation | P2-05 | P0 | Matches design §13 Phase 3 layout | NOT_STARTED |
| P3-03 | Note list (sort, favorites, archive) | P2-04 | P0 | Playwright | NOT_STARTED |
| P3-04 | CodeMirror 6 editor with live preview and wiki-links | P2-04 | P0 | Corpus notes open and save byte-identically through UI | NOT_STARTED |
| P3-05 | Tags UI | P2-07 | P0 | — | NOT_STARTED |
| P3-06 | Search UI with grammar hints | P2-08 | P0 | — | NOT_STARTED |
| P3-07 | Attachments: upload, image/PDF preview, embeds | P2-06 | P0 | — | NOT_STARTED |
| P3-08 | IndexedDB cache and outbox (offline read/edit) | P3-04 | P0 | Offline edit survives reload and syncs when online | NOT_STARTED |
| P3-09 | Settings, vault management | P2-03 | P0 | — | NOT_STARTED |
| P3-10 | Responsive layout and PWA shell | P3-02 | P0 | Usable at 375 px width; installable | NOT_STARTED |

## Phase 4 — Apple applications (M4)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P4-01 | `OpenNoteCore` parsing parity with Python on the corpus | P1-10 | P0 | Same `expected.json` results | NOT_STARTED |
| P4-02 | `OpenNoteStorage`: local vault, atomic coordinated writes, SQLite state | P4-01 | P0 | Local save < 100 ms; round-trip tests | NOT_STARTED |
| P4-03 | `OpenNoteAPI`: generated client, auth via ASWebAuthenticationSession, Keychain | P2-10 | P0 | Login on macOS and iOS | NOT_STARTED |
| P4-04 | `OpenNoteEditor`: TextKit 2 Markdown editor with live styling | P4-02 | P0 | Corpus edits preserve bytes | NOT_STARTED |
| P4-05 | macOS app: windows, menus, shortcuts, drag and drop, user-chosen vault folder | P4-02, P4-04 | P0 | XCUITest smoke | NOT_STARTED |
| P4-06 | iOS app: app-container vault exposed in Files, camera attachments | P4-02, P4-04 | P0 | XCUITest smoke | NOT_STARTED |
| P4-07 | iPadOS: split view, keyboard, Pencil-friendly interactions | P4-06 | P0 | XCUITest on iPad | NOT_STARTED |
| P4-08 | Share extension, quick capture, notifications | P4-05, P4-06 | P1 | Manual + UI test | NOT_STARTED |

## Phase 5 — Synchronization (M5 = MVP)

Milestone M5: design §15.17 criteria 1–9 hold; offline iPhone edit syncs; concurrent macOS edit not overwritten; direct Obsidian edits propagate.

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P5-01 | Production sync endpoints (changes, snapshot, push, blobs, events) from the P1-12 prototype | P1-12, P2-04 | P0 | Simulation + contract tests | NOT_STARTED |
| P5-02 | Resumable chunked blob upload | P5-01 | P0 | Interrupted 500 MB upload resumes | NOT_STARTED |
| P5-03 | Swift sync engine (outbox, loop, watcher integration) | P5-01, P4-02 | P0 | Cross-client e2e | NOT_STARTED |
| P5-04 | Web sync engine | P5-01, P3-08 | P0 | Cross-client e2e | NOT_STARTED |
| P5-05 | Conflict list and resolution UI (all clients) | P5-03, P5-04 | P0 | Conflicts visible and resolvable | NOT_STARTED |
| P5-06 | Version history browse, diff, restore, deleted-note recovery | P1-13, P5-01 | P0 | Restore any revision | NOT_STARTED |
| P5-07 | Tombstone retention and history GC per D6 | P5-01 | P0 | GC never removes newest or conflict-referenced revisions | NOT_STARTED |
| P5-08 | Detection of competing sync tools (iCloud/Dropbox/Obsidian Sync) | P5-03 | P1 | Warning shown | NOT_STARTED |
| P5-09 | Cross-client end-to-end sync suite | P5-03, P5-04 | P0 | Nightly green | NOT_STARTED |
| P5-10 | Device management UI and sync status indicator | P5-03, P5-04 | P0 | — | NOT_STARTED |

## Phase 6 — Productivity (M6)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P6-01 | Task extraction and central task view, edits round-trip to the note | M5 | P1 | Toggling a task changes one character in the note | NOT_STARTED |
| P6-02 | Recurring tasks and reminders | P6-01 | P1 | — | NOT_STARTED |
| P6-03 | Calendar integration (CalDAV server-side, EventKit on Apple) | P6-01 | P1 | — | NOT_STARTED |
| P6-04 | Web clipper (browser extension + share sheet) | M5 | P1 | — | NOT_STARTED |
| P6-05 | Templates | M5 | P1 | — | NOT_STARTED |
| P6-06 | Document scanning (VisionKit) and OCR (Vision on device, Tesseract server-side) into search | M5 | P1 | Scanned text searchable | NOT_STARTED |
| P6-07 | Saved searches | P2-08 | P1 | — | NOT_STARTED |
| P6-08 | Backlinks panel and knowledge graph | P1-06 | P1/P2 | — | NOT_STARTED |
| P6-09 | Optional link update on rename (batch, undoable) | P1-06 | P1 | — | NOT_STARTED |
| P6-10 | Email-to-note; Evernote ENEX import | M5 | P2 | — | NOT_STARTED |

## Phase 7 — AI (M7)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P7-01 | AI provider abstraction (Ollama, OpenAI-compatible, faster-whisper), off by default | M5 | P2 | Core works with AI disabled/absent | NOT_STARTED |
| P7-02 | Embedding pipeline (chunking, pgvector, incremental on change) | P7-01 | P2 | Index updates after edits | NOT_STARTED |
| P7-03 | Hybrid semantic search | P7-02, P2-08 | P2 | Results cite notes; vault-scoped | NOT_STARTED |
| P7-04 | AI assistant with citations and injection defenses | P7-03 | P2 | Red-team cases pass | NOT_STARTED |
| P7-05 | Auto-tagging and classification suggestions | P7-01 | P2 | Suggestions only; no unapproved writes | NOT_STARTED |
| P7-06 | Summarization | P7-01 | P2 | — | NOT_STARTED |
| P7-07 | Transcription and meeting notes | P7-01 | P2 | — | NOT_STARTED |
| P7-08 | Action-item extraction into tasks (with approval) | P7-07, P6-01 | P2 | — | NOT_STARTED |

## Phase 8 — Production hardening (M8)

| ID | Description | Depends on | Prio | Acceptance criteria | Status |
|---|---|---|---|---|---|
| P8-01 | Performance validation at 100k notes against §15.14 targets | M5 | P0 | Benchmarks recorded on reference hardware | NOT_STARTED |
| P8-02 | Security testing (external review, DAST) | M5 | P0 | No known critical findings | NOT_STARTED |
| P8-03 | Accessibility review (VoiceOver, keyboard, WCAG 2.2 AA web) | M5 | P0 | — | NOT_STARTED |
| P8-04 | Backup and restore (vault, history, DB; encrypted) | M5 | P0 | Restore drill succeeds | NOT_STARTED |
| P8-05 | Disaster recovery test, including DB rebuild from vault + history log | P8-04 | P0 | — | NOT_STARTED |
| P8-06 | OpenShift production deployment (Helm, Routes, restricted SCC) | P0-11 | P0 | Deploys on OpenShift 4.16+ | NOT_STARTED |
| P8-07 | User, operator and API documentation | — | P0 | — | NOT_STARTED |
| P8-08 | Release automation, image signing, app notarization/TestFlight | — | P0 | — | NOT_STARTED |
| P8-09 | Beta program | P8-01…P8-08 | P0 | — | NOT_STARTED |
