# Implementation Status

Last updated: 2026-11-01

## Current phase

**Phase 1 — Vault storage engine and sync prototype, implemented on `feature/phase-1-storage-sync`; in review.** The work of the [Phase 1 plan](superpowers/plans/2026-11-01-phase-1-storage-sync-plan.md) (P1-01 to P1-13) is a Python library under `backend/app/vaults`, `backend/app/notes` and `backend/app/sync` with migrations `0002` to `0004`: it opens an existing Obsidian vault without writing to it, reads and edits notes byte for byte, writes atomically without clobbering external saves, detects external changes and renames, keeps a rebuildable index and a content-addressed history, and commits, merges and serves changes for a server-side sync prototype checked by a seeded multi-client simulation. The only new HTTP route is the keyless `GET /api/v1/meta/path-rules`; the note and sync endpoints, authentication and the process that runs the watcher are Phase 2. Every P1 row is `TESTING` until its CI run is observed ([ROADMAP.md, Phase 1](ROADMAP.md#phase-1--vault-storage-engine--sync-prototype-m1)).

Phase 0: **Phase 0 — Foundation, implemented; pre-release.** Phase 0, the work of the [Phase 0 plan](superpowers/plans/2026-10-17-phase-0-foundation-plan.md), is delivered as one squash-merged pull request from `feature/phase-0-foundation`. It holds skeletons and tooling only: the API answers `/healthz`, `/readyz` and `/api/v1/meta`; any other path answers 404 and a wrong method 405 (`POST /healthz`), both as `application/problem+json`; and the startup assertion `assert_routes_authenticated` refuses to start the API if a route has no authentication dependency and is not in `KEYLESS_ROUTES` (`CLAUDE.md` §12). The worker runs one smoke-test job, and the web and Apple apps show empty shells. Version 0.1.0 is not released, no image is published, and nothing is deployed anywhere. Roadmap items and their evidence: [ROADMAP.md, Phase 0](ROADMAP.md#phase-0--foundation-m0).

## Completed

- P0-01: architecture specification, ADR-0001 to ADR-0017 (*Accepted* since 2026-11-01), contracts, sync protocol, testing strategy, threat model and roadmap, merged to `main` with the Phase 0 plan on 2026-10-17.
- P0-02 to P0-12 except P0-07 and P0-09 (below): repository skeleton and versions record ([versions.md](development/versions.md)); backend app, database and migration baseline, readiness checks and worker; web app; Apple packages and app targets; OpenAPI export with generated TypeScript and Swift clients; Kubernetes, Helm and OpenShift skeletons ([deployment guide](deployment/kubernetes.md)).
- P0-10 security baseline: closed on 2026-11-01 with the criterion narrowed to zero *fixable* HIGH and CRITICAL findings (Flemming's decision, [ROADMAP.md](ROADMAP.md)); what runs and where is in "Verified where", what the gate does not show is under "Open items".
- How to set up a working copy and run every check: [setup.md](development/setup.md).

## In progress

| Item | State | Gap |
|---|---|---|
| P0-07 Container images and Compose | TESTING | `podman compose` has never been run; CI uses Docker |
| P1-01 to P1-13 storage engine and sync prototype | TESTING | Local runs only so far: backend suite 505 passed, 3 skipped (5 minutes, including 500 seeds); 10,000 simulation seeds zero violations over seeds 0 to 9,999 on `4673673` (224 tests passed, 1 h 11 min wall). The pull request's CI runs and the first nightly 10,000-seed run on `main` are not observed yet |
| P0-09 CI | TESTING | All five workflows are green on the branch's pushes; the Phase 0 pull request's own runs are not observed yet |

## Verified where

"Local" is the Linux container Claude Code works in: Python 3.13.16, Node 26.12.0 (24.22.0 during Phase 0), PostgreSQL 16 with pgvector 0.6.0 and Valkey 7.2.13, no container engine and no Swift toolchain. "CI" is GitHub Actions; all five workflows are green on commit `d9d7ffd`: [backend](https://github.com/theonewizard/OpenNote/actions/runs/39140717151), [web](https://github.com/theonewizard/OpenNote/actions/runs/39140716872), [apple](https://github.com/theonewizard/OpenNote/actions/runs/39140716926), [containers](https://github.com/theonewizard/OpenNote/actions/runs/39140716862) (jobs `build, run, scan` and `manifests`) and [security](https://github.com/theonewizard/OpenNote/actions/runs/39140716878). The `manifests` job first ran green on `cb66c10` ([run](https://github.com/theonewizard/OpenNote/actions/runs/39119290990)); earlier runs are cited in [versions.md](development/versions.md).

| Component | Local | CI | Not verified |
|---|---|---|---|
| Backend API and worker (P0-03 to P0-05) | ruff, mypy (strict), and pytest with the integration tests against the local PostgreSQL and Valkey: 113 passed, 2 skipped (they need a directory root cannot write to); the API under uvicorn and the worker with a job and a SIGTERM, run by hand | `backend`: the same checks on Python 3.13.16 and 3.14.8 against PostgreSQL 18.6 with pgvector 0.8.7 and Valkey 9.1.2 service containers, the same suite on each | — |
| Web app (P0-06) | lint, typecheck, 5 unit tests, production build, 2 Playwright tests in the preinstalled Chromium | `web`: the same, with the Chromium build that matches Playwright | Browsers other than Chromium. The shadcn files were generated against a local mirror of the shadcn registry built from shadcn-ui/ui at `d2fba50` (ui.shadcn.com is blocked here, [versions.md](development/versions.md)); a confirmation run on an unrestricted machine is open |
| Container images and Compose (P0-07) | No image built and no stack started. Linted (hadolint, shellcheck, `docker compose config`); the entrypoints and nginx were run against local binaries | `containers`, `build, run, scan`: builds the four images; full stack healthy with migrations, both smoke tests, the newest migration applied; the api image and the full stack as an arbitrary UID in group 0 with read-only root filesystems; the dev stack with the test database's extensions; Trivy scans of the four images | `podman compose` and Podman builds |
| Apple packages and apps (P0-08) | Nothing compiled. `apple/project.yml` parsed; the Swift files parsed with a tree-sitter grammar | `apple`: on the `xcode-27` runner with Xcode 27.1, `swift test` for all five packages (the job is green; its per-package result lines were not read; the sources hold 10 `@Test` functions, two per package), XcodeGen and unsigned builds of `OpenNote-macOS` and `OpenNote-iOS` (Simulator); on Linux in `swift:6.4.1`, `swift test` for `OpenNoteCore` and `OpenNoteStorage`; both jobs check the committed `Package.resolved` files | The apps are built, never launched: no UI test, no signing, no device |
| OpenAPI contract and clients (P0-12) | `make openapi` writes the same bytes every run; the drift check exits 0, and 1 after adding a route | `backend`, `openapi drift`; the TypeScript types type-check in `web`; the Swift client is generated and compiled in `apple` (`OpenNoteAPI`'s `generatedClientExists` test) | — |
| CI and security baseline (P0-09, P0-10) | gitleaks over the whole history (below, "Open items"), every pre-commit hook; actionlint 1.7.12: four workflows clean, `apple.yml` exits 1 only because actionlint does not know the `xcode-27` runner label (harmless) | `security`: gitleaks, `pip-audit --strict`, bandit, `npm audit --audit-level=high`, Trivy filesystem scan; `containers`: Trivy image scans. Every Trivy step runs with `--ignore-unfixed`: it fails on HIGH and CRITICAL findings that have a fix and does not count unfixed ones, which is the P0-10 criterion since 2026-11-01; since the same day a report step next to each gate writes the HIGH and CRITICAL findings without a fix, with their status, and the accepted risks from `.trivyignore.yaml` to the run's Summary tab without gating them ("Open items") | Manual (`workflow_dispatch`) runs. Pull-request runs (#8, #9), Dependabot and the Monday schedules have been observed since; the containers run of 2026-10-26 is the first red one ("Open items") |
| Kubernetes, Helm and OpenShift (P0-11) | `helm lint --strict` (Helm 4.3.1), the chart's default, OpenShift and Ingress renders and the kustomize base and overlay through kubeconform 0.8.0 at Kubernetes 1.29.0; Pod Security `restricted`, checked by hand (by the Task 10 implementer and re-reviewer, and again on `3fab73b`) with a throwaway Go program on k8s.io/pod-security-admission 0.37.1 that is not in the repository: 4 pod templates, 0 forbidden, in each of the five renders. A repeatable CI check is an open item | `containers`, `manifests`: `helm lint --strict`, the five renders, the invariant checks (no Secret, `secretKeyRef` or `secretRef`, `fsGroup` and `fsGroupChangePolicy`, web's API upstream), kubeconform at 1.29.0 and `master` | Rendered and validated only: no cluster has run the manifests ([deployment guide](deployment/kubernetes.md)). Unseen: probes, the migration hook's ordering, the migration against a real database, the worker's drain within its grace period, nginx's graceful stop under the kubelet, `fsGroup` on real RWX storage, OpenShift SCC admission and the Route, the web pod's DNS lookup of the API, `helm uninstall` keeping the volumes |

### Fresh-clone check

On 2026-10-18 a fresh clone of `feature/phase-0-foundation` at `3fab73b` passed, in the local container with the local PostgreSQL and Valkey and the default `OPENNOTE_TEST_*` URLs (Valkey database 1):

| Command | Result |
|---|---|
| `make bootstrap` | exit 0; `git status --porcelain` empty |
| `make lint typecheck test build` | exit 0 (backend 102 passed, 2 skipped as root; web 4 tests; build) |
| `OPENNOTE_PW_EXECUTABLE=<the preinstalled Chromium> npm run test:e2e` in `web/` (the Chromium build that matches Playwright is not installed in this container, so the variable, which `web/playwright.config.ts` reads, points at the preinstalled one) | exit 0, 2 passed |
| `make help` | exit 0, lists the 11 targets |
| `scripts/gen-openapi.sh && scripts/gen-clients.sh && git diff --exit-code …` | exit 0; exit 1 with a route added, exit 0 again after removing it |

## Owner actions still open

These are repository settings only the owner can change ([workflow.md](development/workflow.md#repository-settings-the-owner-enables)):

- Enable private vulnerability reporting; `SECURITY.md`'s form needs it.
- Protect `main`: require a pull request and the status checks by their exact names as listed in workflow.md, `manifests` included; block force pushes and deletion.
- Allow squash merges only.

## Open items

- Phase 1, from the final review (2026-11-01), decided for later rather than fixed ([record](../.conversations/2026-11-01-phase-1-storage-sync.md), R145):
  - Concurrency: the commit path serializes in PostgreSQL only up to the database step; the log and vault steps run after it. Phase 1 has one caller per vault. Before Phase 2 wires the watcher and HTTP requests to one vault, a per-vault lock must be held through the vault write, or two commits of one file can revert a revision.
  - Crash recovery base (sync protocol §2.3, needs Flemming): when the disk matches neither the previous nor the current revision, recovery merges the disk against the previous revision. That is right after a crash before the vault write, and wrong when the write had completed and the user then edited the note offline (a deletion of lines the last revision added can come back). The fix needs a record of the last written sequence number.
  - Memory: the commit path takes whole blobs, so a 2 GiB attachment is held in memory several times on ingest and commit; streaming is P5-02 (resumable blob upload).
- The remote branch `probe/ubi-python`, a throwaway CI probe one commit ahead of `main` (the whole tree of `main` at `84eefbc` plus `.github/workflows/probe.yml`), could not be deleted from the Claude Code environment. Delete it on GitHub; it is never merged.
- `backend/migrations/script.py.mako`, the template `alembic revision` uses, renders files that ruff flags. The first real migration (Phase 1) adds a ruff post-write hook or adapts the template.
- The version 0.1.0 is written in `backend/app/__init__.py`, `OpenNoteCore.version`, `MARKETING_VERSION` in `apple/project.yml`, `version` and `appVersion` in `infrastructure/helm/opennote/Chart.yaml` and the four image tags in `infrastructure/kubernetes/base/*.yaml`; three Swift tests assert it, and the generated OpenAPI documents (`docs/api/openapi.json` and its Swift copy) carry it. No check compares them yet (a `make check-versions` target or a CI step, Phase 1, covering all of these). `web/package.json` carries the create-vite placeholder 0.0.0.
- CI has no Pod Security `restricted` check; it was verified locally only (above).
- `podman compose` has never been run (CI uses Docker).
- The `xcode-27` runner label is a public-preview image, and CI installs XcodeGen from Homebrew unpinned; the job's `xcodegen --version` line has not been read from a log.
- The Monday rescan of 2026-10-26 ([containers run](https://github.com/theonewizard/OpenNote/actions/runs/40320960413)) failed on a fixable CRITICAL in the pinned `ubi-minimal` base of all four images (`ca-certificates` CVE-2026-114406, fixed in `2026.2.92_v9.0.319-90.3.el9_8`); the `security` run of the same Monday passed. Dependabot's digest bumps #12 to #15 fix it one image each (so each stays red on the other three) and are already a build behind; pull request #18 (merged 2026-11-01) moved all four images to the build the Red Hat catalog lists for the tag (pushed 2026-10-29) and supersedes them. Flemming's point 1 of 2026-11-01 asked for tools that do not hide them. Eight options were compared against their own documentation, every claim re-checked against its source ([record and sources](../.conversations/2026-11-01-phase-0-decisions.md), R114): Trivy itself, GitHub code scanning fed with Trivy's SARIF, Anchore Grype, Google OSV-Scanner, Docker Scout, Snyk Container, Red Hat's own CSAF/VEX and OSV feeds, and Dependabot's grouping. **Recommendation:** stay with Trivy and add, next to each gate, a second run that never fails the job (`--ignore-status fixed --exit-code 0`, `continue-on-error: true`) and writes the HIGH and CRITICAL findings Red Hat has not fixed, with Red Hat's status per finding, to the run's job summary; plus a committed `.trivyignore.yaml` whose entries carry a `statement` and an `expired_at` date and are listed by `--show-suppressed`, applied to the report only so the gate stays exactly as it is. Nothing new to install or grant: no account, token, action, permission or repository setting, and the images stay unpublished. Deferred, not rejected: uploading the SARIF to GitHub code scanning (free for this public repository, a persistent alert list with dismiss reasons, but it needs `security-events: write` and a new pinned action, has no expiry, and the workflows' no-upload rule would go). Rejected: Grype (a second scanner and database; its ignore rules have no expiry), OSV-Scanner (no RPM or UBI coverage for images), Docker Scout and Snyk (an account and a token each). Known limits: the Trivy pages read are the 0.67 snapshots while CI pins 0.76.0, so the flags are confirmed on the first run; a job summary lives as long as the run log (90 days by default), the ledger file is the durable record; the filesystem report is mostly redundant with `pip-audit --strict` and `npm audit`, which already fail on unfixed findings. Flemming chose it on 2026-11-01 ("Trivy report"), and it is in place since that day: a report step before each Trivy gate in `containers` and `security` (`--ignore-status fixed --exit-code 0 --ignorefile .trivyignore.yaml --show-suppressed`, `continue-on-error: true`; a failing Trivy call turns the step red without failing the job), the empty `.trivyignore.yaml` ledger, and the description in [setup.md](development/setup.md#continuous-integration) ([record](../.conversations/2026-11-01-trivy-unfixed-report.md), R117 to R121). The filesystem report's status column is the advisory's (fixed or affected), Red Hat's status appears for the images' RPM packages.
- Dependabot opened one pull request per Containerfile directory for the same base image (#12 to #15) because the docker group filters `update-types: [minor, patch]` and GitHub does not document how a digest-only bump is classified; GitHub documents `group-by: dependency-name` as the way to one pull request per dependency across the listed directories (version updates only). The change is that one key in the docker group of `dependabot.yml`, with the `update-types` filter dropped (R115); made on 2026-11-01 as the `docker-base-images` group (R119). The first base-image bump after that shows whether one pull request results.
- GitHub moves `ubuntu-latest` to Ubuntu 26 from 2026-10-19. The runner tools that are not pinned (the runner image rows and kubectl in [versions.md](development/versions.md#continuous-integration)) need a recheck after the first run on the new image.
- The postgres image imports the PGDG signing key only if its fingerprint and the SHA-256 of the whole decoded key match the pinned values, so a key rotation fails the build until both values are updated (by design).
- The generated Swift client emits over 100 `#UnusedImportAccess` warnings under Swift 6.4 (swift-openapi-generator 1.14.1). They are not errors, but would fail a build that treats warnings as errors.
- gitleaks over the whole history has been run locally, not in CI: gitleaks 8.30.1 (the build of the pre-commit hook) over all refs of the local clone, with the branch at `2cb13d3`, scanned 49 commits (the 48 non-merge commits reachable from `2cb13d3` and one on `feature/architecture-plan`) and found no leaks. One reviewed false positive, prose in the spec's risk table, is allowlisted by fingerprint in `.gitleaksignore`; without that file the same scan reports 1 leak.
- In CI, gitleaks-action scans only a push's commits as the push event lists them (at most 20) and a pull request's first 30 commits, so a longer push or pull request is scanned in part; the whole history is scanned only on a manual run and in the Monday run on `main`. No step covers the rest.
- A 401 from a route that takes an automation token (`get_api_key`, the `X-API-Key` header) carries no `WWW-Authenticate` challenge header; which one it sends is decided in Phase 1, with the real token check.
- Python packages are pinned by name and version only (`backend/requirements*.txt`, `backend/constraints.txt`), without hashes, so pip does not check what it downloads against recorded hashes; `pip-compile --generate-hashes` is a Phase 1 candidate ([versions.md](development/versions.md#backend-pypi)).

## Known limits

- Phase 1's crash tests inject failures between the steps of a write and of a commit (`test_crash_at_each_point_leaves_old_or_new_bytes`, the four commit crash points); a real power loss, and `fsync` behaviour of a given filesystem, is not tested.
- `renameat2(RENAME_EXCHANGE)` closes the check-to-rename window of the external-change guard; filesystems without it (NFS, some RWX volumes) fall back to check-then-rename and log a warning the first time ([deployment guide](deployment/kubernetes.md)).
- Obsidian link resolution compares every link with every path (`app/notes/links.py`), which is fine for the corpus and small vaults and is measured by P8-01's 100k-note vault.
- Each watcher pass rescans the whole vault with a stat cache (only changed files are hashed); per-path rescans are a Phase 2 option.
- The worker has no health check (no HTTP endpoint). After a graceful stop, a SIGHUP restart of `python -m app.workers` fails; orchestrators send SIGTERM, which works.
- `/readyz` checks the two data directories in a thread; a hung network mount can leave that thread blocked after the check has timed out.
- The default Compose stack is for local use only: see [setup.md, "Security posture of the default stack"](development/setup.md#security-posture-of-the-default-stack).

## Open architectural decisions

D2–D6 in the [specification §4](superpowers/specs/2026-10-17-opennote-architecture-design.md#4-unresolved-decisions-need-flemming): tenancy, minimum Apple OS, minimum OpenShift/Kubernetes, writing `id` on edit, history retention. Phase 0 uses the defaults of D3 (macOS 15, iOS and iPadOS 18) and D4 (OpenShift 4.16+, Kubernetes 1.29+). D1 (AGPL-3.0), D7 (adapt `CLAUDE.md` §11–§14) and D8 (rename to `CLAUDE.md`) are decided.

## Test status

| Suite | Tests | Where |
|---|---|---|
| Backend (unit, compatibility and integration) | 505 passed and 3 skipped locally (two read-only-directory tests skip as root; one corpus case is a read-only note with no edit round trip) | Local; CI on the pull request pending |
| Sync simulation (`make sync-sim`) | zero violations over seeds 0 to 9,999 on `4673673` (224 tests passed, 1 h 11 min wall); 500 seeds inside the backend suite | Local; nightly in CI after the merge |
| Web unit (Vitest) | 5 | Local and CI |
| Web end-to-end (Playwright) | 2 | Local and CI |
| Apple (`swift test`, five packages) | 10 `@Test` functions in the sources | CI only (macOS, green, per-package result lines not read; `OpenNoteCore` and `OpenNoteStorage` also on Linux) |

## Known defects

None known.

## Next planned work

Merge Phase 1 after review, observe one nightly 10,000-seed run, then Phase 2 (authentication and the note and vault endpoints on the sync commit path).
