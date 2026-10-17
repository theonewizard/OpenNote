# Tool Versions

Resolved 2026-10-17 for Phase 0 (`CLAUDE.md` §1.8: latest stable release; design §6 versions are floors). Later tasks pin these exact versions in `backend/requirements*.txt`, `web/package.json`, Containerfiles and CI. Re-check a row before upgrading it.

Docker Hub tag dates are image build dates, not release dates, so those rows show "—" under "Released". "Not verified from this environment" means the authoritative source is blocked from the Claude Code container used for Phase 0; the row names the source that was used instead, or the URL to check.

## Runtimes, services and base images

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Python (upstream, latest stable) | 3.15.0 | — | python.org is blocked from this environment. Read from the official Docker image tags: https://hub.docker.com/v2/repositories/library/python/tags?page_size=100 (`latest` = `3.15.0`; also CentOS Stream c11s "Update to Python 3.15.0", https://gitlab.com/redhat/centos-stream/rpms/python3.15) | 2026-10-17 |
| Python on UBI (newest verified) | 3.12 (default `python3` on UBI 10) | — | https://gitlab.com/redhat/centos-stream/rpms/python3.12 (branches c9s, c10s); https://gitlab.com/redhat/centos-stream/rpms/python3.13 does not exist. UBI repositories themselves are not verified from this environment (see [Python gap](#python-gap)) | 2026-10-17 |
| Python, local development | 3.13.16 | — | `/usr/bin/python3 --version` in the Phase 0 container | 2026-10-17 |
| PostgreSQL | 18.6 | — | postgresql.org is blocked from this environment. Read from https://hub.docker.com/v2/repositories/library/postgres/tags?page_size=100 (`latest` = `18` = `18.6`; 19 is at `19rc1`) | 2026-10-17 |
| pgvector | 0.8.7 | — | github.com is blocked from this environment. Read from https://hub.docker.com/v2/repositories/pgvector/pgvector/tags?page_size=100 (`pg18` = `0.8.7-pg18`; no newer version in any of the 201 tags) | 2026-10-17 |
| Valkey | 9.1.2 | — | github.com is blocked from this environment. Read from https://hub.docker.com/v2/repositories/valkey/valkey/tags?page_size=100 (`latest` = `9.1.2`; `9.2` points at `9.2.0-rc1`, a pre-release) | 2026-10-17 |
| Node.js (LTS) | v24.22.0 "Krypton" (npm 11.19.1) | 2026-10-14 | https://nodejs.org/dist/index.json (current release v26.12.0 is not LTS) | 2026-10-17 |
| UBI 9 minimal | `ubi9-minimal:9.8` | — | registry.access.redhat.com is blocked from this environment. Read from Docker Hub's Red Hat mirror: https://hub.docker.com/v2/repositories/redhat/ubi9-minimal/tags | 2026-10-17 |
| UBI 9 | `ubi9:9.8` | — | As above: https://hub.docker.com/v2/repositories/redhat/ubi9/tags | 2026-10-17 |
| UBI 10 minimal | `ubi10-minimal:10.2` | — | As above: https://hub.docker.com/v2/repositories/redhat/ubi10-minimal/tags | 2026-10-17 |
| UBI 10 | `ubi10:10.2` | — | As above: https://hub.docker.com/v2/repositories/redhat/ubi10/tags | 2026-10-17 |

## Backend (PyPI)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| fastapi | 0.143.3 | 2026-10-16 | https://pypi.org/pypi/fastapi/json | 2026-10-17 |
| uvicorn | 0.54.0 | 2026-09-25 | https://pypi.org/pypi/uvicorn/json | 2026-10-17 |
| pydantic | 2.14.1 | 2026-10-11 | https://pypi.org/pypi/pydantic/json | 2026-10-17 |
| pydantic-settings | 2.16.0 | 2026-10-14 | https://pypi.org/pypi/pydantic-settings/json | 2026-10-17 |
| SQLAlchemy | 2.1.5 | 2026-10-16 | https://pypi.org/pypi/sqlalchemy/json | 2026-10-17 |
| alembic | 1.20.0 | 2026-09-11 | https://pypi.org/pypi/alembic/json | 2026-10-17 |
| psycopg | 3.3.6 | 2026-09-18 | https://pypi.org/pypi/psycopg/json | 2026-10-17 |
| dramatiq | 2.2.1 | 2026-09-02 | https://pypi.org/pypi/dramatiq/json | 2026-10-17 |
| pytest | 9.1.1 | 2026-06-19 | https://pypi.org/pypi/pytest/json | 2026-10-17 |
| ruff | 0.17.1 | 2026-10-15 | https://pypi.org/pypi/ruff/json | 2026-10-17 |
| mypy | 2.4.0 | 2026-10-01 | https://pypi.org/pypi/mypy/json | 2026-10-17 |

All of these support Python 3.12 (highest `requires-python` floor: `>=3.11`, SQLAlchemy and pydantic-settings).

## Web (npm `latest` dist-tag)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| react, react-dom | 19.3.1 | 2026-10-14 | https://registry.npmjs.org/react | 2026-10-17 |
| vite | 8.3.4 | 2026-10-08 | https://registry.npmjs.org/vite | 2026-10-17 |
| typescript | 7.0.2 | 2026-07-08 | https://registry.npmjs.org/typescript | 2026-10-17 |
| tailwindcss | 4.3.3 | 2026-07-16 | https://registry.npmjs.org/tailwindcss | 2026-10-17 |
| shadcn (shadcn/ui CLI) | 4.22.0 | 2026-10-16 | https://registry.npmjs.org/shadcn | 2026-10-17 |
| vitest | 5.0.5 | 2026-10-15 | https://registry.npmjs.org/vitest | 2026-10-17 |
| @playwright/test | 1.64.1 | 2026-10-14 | https://registry.npmjs.org/@playwright%2ftest | 2026-10-17 |
| openapi-typescript | 7.13.0 | 2026-02-11 | https://registry.npmjs.org/openapi-typescript | 2026-10-17 |

## Apple

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Swift | 6.4.1 | 2026-10-12 | https://www.swift.org/api/v1/install/releases.json (swift.org lists 6.4.0 as the toolchain of Xcode 27.0; Linux image `swift:6.4.1` on https://hub.docker.com/v2/repositories/library/swift/tags) | 2026-10-17 |
| Xcode | 27.1 (27A9275) | 2026-10-15 | https://developer.apple.com/news/releases/rss/releases.rss (27.2 is in beta) | 2026-10-17 |
| XcodeGen | 2.46.0 | — | github.com releases are blocked from this environment (https://github.com/yonaskolb/XcodeGen/releases/latest). Read from the newest released heading in https://raw.githubusercontent.com/yonaskolb/XcodeGen/master/CHANGELOG.md and the tag in Homebrew's formula https://raw.githubusercontent.com/Homebrew/homebrew-core/main/Formula/x/xcodegen.rb. The `xcode27_0` project format is listed only under the unreleased "Next Version" | 2026-10-17 |

## Infrastructure tooling

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Helm | v4.3.1 | 2026-10-15 | github.com and get.helm.sh are blocked from this environment. Read from the Go module proxy: https://proxy.golang.org/helm.sh/helm/v4/@latest (v3 line: v3.22.1) | 2026-10-17 |
| Docker Compose | v5.6.0 | 2026-10-02 | https://proxy.golang.org/github.com/docker/compose/v5/@latest (no v6 module) | 2026-10-17 |
| Podman | v6.1.4 | 2026-10-12 | https://proxy.golang.org/go.podman.io/podman/v6/@latest (no v7 module at go.podman.io) | 2026-10-17 |

## Python gap

The [architecture specification](../superpowers/specs/2026-10-17-opennote-architecture-design.md) (§11) requires that the container base offer the latest stable Python; otherwise the newest UBI-available Python is used and the gap is recorded here.

- Latest stable CPython is 3.15.0. The design's floor is 3.13.
- RHEL/UBI does not package 3.15 for RHEL 9 or 10 (the CentOS Stream `python3.15` component is live only on c11s; its c10s branch is retired as a dead package) and has no `python3.13` component at all.
- The newest Python verified as available on UBI is 3.12, the default `python3` of UBI 10. Phase 0 therefore targets Python 3.12 on UBI 10 for the API image (Task 6), the backend declares `requires-python >= 3.12`, and CI tests 3.12 and 3.13. Gap: 3.12 is one minor release below the design floor (3.13) and three below the latest stable release (3.15).
- Open: CentOS Stream packages a "Python 3.14 stack in RHEL" (`python3.14` component, branches c9s and c10s, at 3.14.8 since 2026-10-12: https://gitlab.com/redhat/centos-stream/rpms/python3.14). Whether the UBI 9.8 or UBI 10.2 repositories ship `python3.14` could not be verified from this environment (registry.access.redhat.com, cdn-ubi.redhat.com and catalog.redhat.com are blocked). If they do, 3.14 is the newest UBI-available Python and the image should move to it; check with `microdnf install python3.14` in `ubi10-minimal:10.2` where the Red Hat registry is reachable (CI).
