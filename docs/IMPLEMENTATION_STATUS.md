# Implementation Status

Last updated: 2026-10-18

## Current phase

**Phase 0 — Foundation, implemented; pre-release.** The work of the [Phase 0 plan](superpowers/plans/2026-10-17-phase-0-foundation-plan.md) is on the branch `feature/phase-0-foundation`, which goes to `main` as one squash-merged pull request. It holds skeletons and tooling only: the API answers `/healthz`, `/readyz` and `/api/v1/meta` and denies every other request (`CLAUDE.md` §12), the worker runs one smoke-test job, and the web and Apple apps show empty shells. Version 0.1.0 is not released, no image is published, and nothing is deployed anywhere. Roadmap items and their evidence: [ROADMAP.md, Phase 0](ROADMAP.md#phase-0--foundation-m0).

## Completed

- P0-01: architecture specification, ADR-0001 to ADR-0017 (all *Proposed*), contracts, sync protocol, testing strategy, threat model and roadmap, merged to `main` with the Phase 0 plan on 2026-10-17.
- P0-02 to P0-12 except P0-07 and P0-09 (below): repository skeleton and versions record ([versions.md](development/versions.md)); backend app, database and migration baseline, readiness checks and worker; web app; Apple packages and app targets; OpenAPI export with generated TypeScript and Swift clients; security baseline; Kubernetes, Helm and OpenShift skeletons ([deployment guide](deployment/kubernetes.md)).
- How to set up a working copy and run every check: [setup.md](development/setup.md).

## In progress

| Item | State | Gap |
|---|---|---|
| P0-07 Container images and Compose | TESTING | `podman compose` has never been run; CI uses Docker |
| P0-09 CI | TESTING | All five workflows are green on the branch's pushes; the Phase 0 pull request's own runs are not observed yet |

## Verified where

"Local" is the Linux container Claude Code works in: Python 3.13.16, Node 24.22.0, PostgreSQL 16 with pgvector 0.6.0 and Valkey 7.2.13, no container engine and no Swift toolchain. "CI" is GitHub Actions; all five workflows are green on commit `3fab73b`: [backend](https://github.com/theonewizard/OpenNote/actions/runs/39122087093), [web](https://github.com/theonewizard/OpenNote/actions/runs/39122087029), [apple](https://github.com/theonewizard/OpenNote/actions/runs/39122087111), [containers](https://github.com/theonewizard/OpenNote/actions/runs/39122087091) (jobs `build, run, scan` and `manifests`) and [security](https://github.com/theonewizard/OpenNote/actions/runs/39122087160). The `manifests` job first ran green on `cb66c10` ([run](https://github.com/theonewizard/OpenNote/actions/runs/39119290990)); earlier runs are cited in [versions.md](development/versions.md).

| Component | Local | CI | Not verified |
|---|---|---|---|
| Backend API and worker (P0-03 to P0-05) | ruff, mypy (strict), and pytest with the integration tests against the local PostgreSQL and Valkey: 102 passed, 2 skipped (they need a directory root cannot write to); the API under uvicorn and the worker with a job and a SIGTERM, run by hand | `backend`: the same checks on Python 3.13.16 and 3.14.8 against PostgreSQL 18.6 with pgvector 0.8.7 and Valkey 9.1.2 service containers, 104 passed on each | — |
| Web app (P0-06) | lint, typecheck, 4 unit tests, production build, 2 Playwright tests in the preinstalled Chromium | `web`: the same, with the Chromium build that matches Playwright | Browsers other than Chromium |
| Container images and Compose (P0-07) | No image built and no stack started. Linted (hadolint, shellcheck, `docker compose config`); the entrypoints and nginx were run against local binaries | `containers`, `build, run, scan`: builds the four images; full stack healthy with migrations, both smoke tests, migration `0001` applied; the api image and the full stack as an arbitrary UID in group 0 with read-only root filesystems; the dev stack with the test database's extensions; Trivy scans of the four images | `podman compose` and Podman builds |
| Apple packages and apps (P0-08) | Nothing compiled. `apple/project.yml` parsed; the Swift files parsed with a tree-sitter grammar | `apple`: on the `xcode-27` runner with Xcode 27.1, `swift test` for all five packages (10 tests), XcodeGen and unsigned builds of `OpenNote-macOS` and `OpenNote-iOS` (Simulator); on Linux in `swift:6.4.1`, `swift test` for `OpenNoteCore` and `OpenNoteStorage`; both jobs check the committed `Package.resolved` files | The apps are built, never launched: no UI test, no signing, no device |
| OpenAPI contract and clients (P0-12) | `make openapi` writes the same bytes every run; the drift check exits 0, and 1 after adding a route | `backend`, `openapi drift`; the TypeScript types type-check in `web`; the Swift client is generated and compiled in `apple` (`OpenNoteAPI`'s `generatedClientExists` test) | — |
| CI and security baseline (P0-09, P0-10) | gitleaks over the whole history, every pre-commit hook, actionlint | `security`: gitleaks, `pip-audit --strict`, bandit, `npm audit --audit-level=high`, Trivy filesystem scan; `containers`: Trivy image scans. Trivy fails on HIGH and CRITICAL findings that have a fix (`--ignore-unfixed`) | Pull-request runs, Dependabot, the Monday schedules and manual (`workflow_dispatch`) runs |
| Kubernetes, Helm and OpenShift (P0-11) | `helm lint --strict` (Helm 4.3.1), the chart's default, OpenShift and Ingress renders and the kustomize base and overlay through kubeconform 0.8.0 at Kubernetes 1.29.0; Pod Security `restricted` with k8s.io/pod-security-admission 0.37.1: 4 pod templates, 0 forbidden, in each of the five renders | `containers`, `manifests`: `helm lint --strict`, the five renders, the invariant checks (no Secret or `secretKeyRef`, `fsGroup` and `fsGroupChangePolicy`, web's API upstream), kubeconform at 1.29.0 and `master` | Rendered and validated only: no cluster has run the manifests ([deployment guide](deployment/kubernetes.md)). Unseen: probes, the migration hook's ordering, the migration against a real database, the worker's drain within its grace period, nginx's graceful stop under the kubelet, `fsGroup` on real RWX storage, OpenShift SCC admission and the Route, the web pod's DNS lookup of the API, `helm uninstall` keeping the volumes |

### Fresh-clone check

On 2026-10-18 a fresh clone of `feature/phase-0-foundation` at `3fab73b` passed, in the local container with the local PostgreSQL and Valkey and the default `OPENNOTE_TEST_*` URLs (Valkey database 1):

| Command | Result |
|---|---|
| `make bootstrap` | exit 0; `git status --porcelain` empty |
| `make lint typecheck test build` | exit 0 (backend 102 passed, 2 skipped as root; web 4 tests; build) |
| `npm run test:e2e` in `web/` | exit 0, 2 passed |
| `make help` | exit 0, lists the 11 targets |
| `scripts/gen-openapi.sh && scripts/gen-clients.sh && git diff --exit-code …` | exit 0; exit 1 with a route added, exit 0 again after removing it |

## Owner actions still open

These are repository settings only the owner can change ([workflow.md](development/workflow.md#repository-settings-the-owner-enables)):

- Enable private vulnerability reporting; `SECURITY.md`'s form needs it.
- Protect `main`: require a pull request and the status checks by their exact names as listed in workflow.md, `manifests` included; block force pushes and deletion.
- Allow squash merges only.

## Open items

- The remote branch `probe/ubi-python`, a throwaway CI probe holding only `.github/workflows/probe.yml`, could not be deleted from the Claude Code environment. Delete it on GitHub; it is never merged.
- `backend/migrations/script.py.mako`, the template `alembic revision` uses, renders files that ruff flags. The first real migration (Phase 1) adds a ruff post-write hook or adapts the template.
- The version 0.1.0 is written in three places, `backend/app/__init__.py`, `OpenNoteCore.version` and `MARKETING_VERSION` in `apple/project.yml`, and no check compares them yet (a `make check-versions` target or a CI step, Phase 1). `web/package.json` is `0.0.0` and carries no version.
- CI has no Pod Security `restricted` check; it was verified locally only (above).
- `podman compose` has never been run (CI uses Docker).
- The `xcode-27` runner label is a public-preview image, and CI installs XcodeGen from Homebrew unpinned; the job's `xcodegen --version` line has not been read from a log.
- Dependabot and the Monday schedules of the containers and security workflows can only run once the workflows are on `main`, so neither has been observed.
- GitHub moves `ubuntu-latest` to Ubuntu 26 from 2026-10-19. The runner tools that are not pinned (the runner image rows and kubectl in [versions.md](development/versions.md#continuous-integration)) need a recheck after the first run on the new image.
- The postgres image imports the PGDG signing key only if its fingerprint and the SHA-256 of the whole decoded key match the pinned values, so a key rotation fails the build until both values are updated (by design).
- The generated Swift client emits over 100 `#UnusedImportAccess` warnings under Swift 6.4 (swift-openapi-generator 1.14.1). They are not errors, but would fail a build that treats warnings as errors.
- gitleaks over the whole history has been run locally, not in CI: CI scans the pushed or pull-request commits, and the whole history only on a manual or scheduled run.

## Known limits

- The worker has no health check (no HTTP endpoint). After a graceful stop, a SIGHUP restart of `python -m app.workers` fails; orchestrators send SIGTERM, which works.
- `/readyz` checks the two data directories in a thread; a hung network mount can leave that thread blocked after the check has timed out.
- The default Compose stack is for local use only: see [setup.md, "Security posture of the default stack"](development/setup.md#security-posture-of-the-default-stack).

## Open architectural decisions

D2–D6 in the [specification §4](superpowers/specs/2026-10-17-opennote-architecture-design.md#4-unresolved-decisions-need-flemming): tenancy, minimum Apple OS, minimum OpenShift/Kubernetes, writing `id` on edit, history retention. Phase 0 uses the defaults of D3 (macOS 15, iOS and iPadOS 18) and D4 (OpenShift 4.16+, Kubernetes 1.29+). D1 (AGPL-3.0), D7 (adapt `CLAUDE.md` §11–§14) and D8 (rename to `CLAUDE.md`) are decided.

## Test status

| Suite | Tests | Where |
|---|---|---|
| Backend (unit and integration) | 104 | Local and CI |
| Web unit (Vitest) | 4 | Local and CI |
| Web end-to-end (Playwright) | 2 | Local and CI |
| Apple (`swift test`, five packages) | 10 | CI only (macOS; `OpenNoteCore` and `OpenNoteStorage` also on Linux) |

## Known defects

None known.

## Next planned work

After the Phase 0 pull request is merged: Phase 1, starting with P1-10 (compatibility corpus) and P1-02 (byte-preserving reader and writer).
