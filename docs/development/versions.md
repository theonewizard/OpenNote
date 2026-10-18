# Tool Versions

Resolved 2026-10-17 for Phase 0 (`CLAUDE.md` §1.8: latest stable release; design §6 versions are floors). The Phase 0 tasks pinned these versions in `backend/requirements*.txt`, `web/package.json`, Containerfiles and CI, except where a peer constraint recorded here says otherwise. Re-check a row before upgrading it.

How to read the rows:

- Where the authoritative source is blocked from the container Phase 0 was resolved in, the row says "Not verified from this environment", names the authoritative URL that would be checked, and then the fallback source that was actually read.
- Digests are the multi-platform index digest of the tag on the check date, read from the Docker Hub tag API. Tags such as `9.8` or `18.6` are rebuilt and move; Containerfiles pin `tag@digest`.
- Docker Hub tag dates are image build dates, not release dates, so image-only rows show "—" under "Released".

## Runtimes, services and base images

| Tool | Version | Released | Digest | Source | Checked |
|---|---|---|---|---|---|
| Python (upstream, latest stable) | 3.15.0 | — | `python:3.15.0` `sha256:e748956ccf3f50c9555f236753bbcd5f430d3937e665d3bd6922dd0e6e591a24` | Not verified from this environment: https://www.python.org/downloads/ is blocked. Read instead: the official image tag `3.15.0` (= `latest`), https://hub.docker.com/v2/repositories/library/python/tags/3.15.0, corroborated by the CentOS Stream c11s commit "Update to Python 3.15.0" (https://gitlab.com/redhat/centos-stream/rpms/python3.15) | 2026-10-17 |
| UBI Python 3.14 image | `registry.access.redhat.com/ubi9/python-314` | — | exists (CI probe, run below); digest not verified from this environment | CI probe https://github.com/theonewizard/OpenNote/actions/runs/39071433587 (`docker manifest inspect` of `:latest`). See [Python decision](#python-decision) | 2026-10-17 |
| UBI Python 3.12 image | `registry.access.redhat.com/ubi9/python-312` | — | exists (CI probe, run below); digest not verified from this environment | As above | 2026-10-17 |
| PostgreSQL | 18.6 | — | `postgres:18.6` `sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336` | Not verified from this environment: https://www.postgresql.org/support/versioning/ is blocked. Read instead: https://hub.docker.com/v2/repositories/library/postgres/tags?page_size=100 (`latest` = `18` = `18.6`; 19 is at `19rc1`) | 2026-10-17 |
| pgvector | 0.8.7 | 2026-10-01 | `pgvector/pgvector:0.8.7-pg18` `sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11` | Not verified from this environment: https://github.com/pgvector/pgvector/tags is blocked. Read instead: the upstream changelog https://raw.githubusercontent.com/pgvector/pgvector/master/CHANGELOG.md ("0.8.7 (2026-10-01)") and https://hub.docker.com/v2/repositories/pgvector/pgvector/tags?page_size=100 (`pg18` = `0.8.7-pg18`; no newer version in any of the 201 tags) | 2026-10-17 |
| Valkey | 9.1.2 | 2026-08-31 | `valkey/valkey:9.1.2` `sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd` | Not verified from this environment: https://github.com/valkey-io/valkey/releases is blocked. Read instead: the upstream release notes https://raw.githubusercontent.com/valkey-io/valkey/9.1/00-RELEASENOTES ("Valkey 9.1.2 - Released Mon 31 August 2026"; the 9.2 branch is at 9.2.0-rc1) and https://hub.docker.com/v2/repositories/valkey/valkey/tags?page_size=100 (`latest` = `9.1.2`) | 2026-10-17 |
| Node.js | v26.12.0 | 2026-10-14 | — | https://nodejs.org/dist/index.json (newest release; moved from v24.22.0 "Krypton" on 2026-10-18). Its `lts` field is still `false`: per https://raw.githubusercontent.com/nodejs/Release/main/schedule.json v26 enters Active LTS on 2026-10-28 and v24 enters Maintenance on 2026-10-20. Pinned in the root `.nvmrc`, which the workflows read with `actions/setup-node`'s `node-version-file`; `web/package.json` declares `engines` `node >=26.12.0 <27`, `npm >=11` | 2026-10-18 |
| npm | 11.20.0, the npm bundled with Node.js 26.12.0 | 2026-09-22 | — | https://nodejs.org/dist/index.json (`npm` field of v26.12.0). Chosen on purpose: the bundled npm is what `make bootstrap` and CI get without a second install. Newer release not adopted: npm `latest` 12.2.0 (2026-09-30, engines `node ^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`), https://registry.npmjs.org/npm | 2026-10-18 |
| UBI 9 minimal | `registry.access.redhat.com/ubi9/ubi-minimal:9.8` (RHEL 9.8) | — | `sha256:c4c285d42941ebb2bd4da878479008e1e4536bb599aad1dbe568f89de9053661` | Not verified from this environment: https://registry.access.redhat.com/v2/ubi9/ubi-minimal/tags/list is blocked. Read instead: Docker Hub's Red Hat mirror https://hub.docker.com/v2/repositories/redhat/ubi9-minimal/tags/9.8. The CI probe pulled the Red Hat registry tag with the same digest | 2026-10-17 |
| UBI 9 | `registry.access.redhat.com/ubi9/ubi:9.8` | — | `sha256:16e9e43d99e181463513cc84a514859b1abb9460f1c4d9e208da4b4e51cd5cc3` (Docker Hub mirror) | Not verified from this environment: https://registry.access.redhat.com/v2/ubi9/ubi/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi9/tags/9.8 | 2026-10-17 |
| UBI 10 minimal | `registry.access.redhat.com/ubi10/ubi-minimal:10.2` (RHEL 10.2) | — | `sha256:552f8cc1ddb0bc9e411065c78499aa4dbc2c4ea9bd057aa0e6e44940db13acb5` | Not verified from this environment: https://registry.access.redhat.com/v2/ubi10/ubi-minimal/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi10-minimal/tags/10.2. The CI probe pulled the Red Hat registry tag with the same digest | 2026-10-17 |
| UBI 10 | `registry.access.redhat.com/ubi10/ubi:10.2` | — | `sha256:a75ad754aa048d808dd3260243452f8c9a665831d0493b4c9d92f0c88fe2f8c3` (Docker Hub mirror) | Not verified from this environment: https://registry.access.redhat.com/v2/ubi10/ubi/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi10/tags/10.2 | 2026-10-17 |
| Node.js builder image (web) | `node:26.12.0-trixie-slim` (Debian 13) | — | `sha256:0d1e33586362bb9e608c4e751e7a9e7edb55c9ac11461ed5666af696cc461dd4` | https://hub.docker.com/v2/repositories/library/node/tags/26.12.0-trixie-slim. Used only as the builder stage of `opennote-web`, because it is exactly the release in `.nvmrc` (no UBI Node.js image can be checked from here); only the static build output reaches the UBI runtime image. `26.12.0-slim` is the same image (same index digest on the check date) | 2026-10-18 |
| nginx (web runtime) | 1.26.3, module stream `nginx:1.26` of RHEL 9.8, installed in `ubi9/ubi-minimal:9.8` | — | — (RPM, not pinned; the base image is) | Not verified from this environment: the UBI repositories (https://cdn-ubi.redhat.com) are blocked. Read instead: CentOS Stream https://gitlab.com/redhat/centos-stream/rpms/nginx, branches `stream-nginx-1.22`, `-1.24` and `-1.26-rhel-9.8.0` (spec at 1.26.3; a 1.30 stream exists only for RHEL 9.10). Red Hat publishes `ubi9/nginx-126` on registry.access.redhat.com, so the stream should be in the UBI repositories; the image build verifies it (installed: [Packages the image builds installed](#packages-the-image-builds-installed)). Gap: upstream stable is 1.30.6 (Docker Hub `nginx:stable` = `1.30.6`, https://hub.docker.com/v2/repositories/library/nginx/tags/stable; nginx.org is blocked) | 2026-10-18 |
| PostgreSQL and pgvector RPMs (PGDG) | `postgresql18-server-18.6`, `postgresql18-contrib-18.6`, `pgvector_18-0.8.7` | — | — | Not verified from this environment: the PGDG repository https://download.postgresql.org/pub/repos/yum/18/redhat/rhel-9-x86_64/ and its key https://download.postgresql.org/pub/repos/yum/keys/PGDG-RPM-GPG-KEY-RHEL are blocked. Package names, paths and the repository layout are PGDG's long-standing ones, the versions those of the PostgreSQL and pgvector rows above; the `opennote-postgres` image build verifies them (installed, and the repository key's fingerprint: [Packages the image builds installed](#packages-the-image-builds-installed)). RHEL 9.8 has its own `postgresql:18` stream (18.1 with pgvector 0.8.7; https://gitlab.com/redhat/centos-stream/rpms/postgresql and https://gitlab.com/redhat/centos-stream/rpms/pgvector, branches `stream-postgresql-18-rhel-9.8.0`), but Red Hat publishes its PostgreSQL images only on registry.redhat.io, which suggests the server is not in the UBI repositories (ADR-0010) | 2026-10-18 |
| Valkey source release | 9.1.2, https://github.com/valkey-io/valkey/archive/refs/tags/9.1.2.tar.gz | 2026-08-31 | archive `sha256:19c23908e7d57e8d91ef85b41f5646307582f10f4f0fb999bbf89ed24ec9c983` | Not verified from this environment: the archive download is blocked. The checksum is the same in the upstream image project's https://raw.githubusercontent.com/valkey-io/valkey-container/mainline/versions.json and in Homebrew's https://raw.githubusercontent.com/Homebrew/homebrew-core/main/Formula/v/valkey.rb; the `opennote-valkey` build checks it. Built from source because RHEL 9 packages Valkey 8.1.10 (CentOS Stream https://gitlab.com/redhat/centos-stream/rpms/valkey, branch c9s) | 2026-10-18 |

## Backend (PyPI)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| fastapi | 0.143.3 | 2026-10-16 | https://pypi.org/pypi/fastapi/json | 2026-10-17 |
| uvicorn | 0.54.0 | 2026-09-25 | https://pypi.org/pypi/uvicorn/json. Pinned as `uvicorn[standard]==0.54.0`: the extra installs httptools, python-dotenv, PyYAML, uvloop, watchfiles and websockets | 2026-10-17 |
| pydantic | 2.14.1 | 2026-10-11 | https://pypi.org/pypi/pydantic/json | 2026-10-17 |
| pydantic-settings | 2.16.0 | 2026-10-14 | https://pypi.org/pypi/pydantic-settings/json | 2026-10-17 |
| SQLAlchemy | 2.1.5 | 2026-10-16 | https://pypi.org/pypi/sqlalchemy/json. Pinned as `sqlalchemy[asyncio]==2.1.5`: the extra installs greenlet | 2026-10-17 |
| alembic | 1.20.0 | 2026-09-11 | https://pypi.org/pypi/alembic/json | 2026-10-17 |
| psycopg | 3.3.6 | 2026-09-18 | https://pypi.org/pypi/psycopg/json. Pinned as `psycopg[binary]==3.3.6`: the extra installs `psycopg-binary` 3.3.6, so local venvs and the image need no libpq build | 2026-10-17 |
| redis (redis-py) | 8.1.0 | 2026-07-30 | https://pypi.org/pypi/redis/json. The Valkey client (Valkey speaks RESP): the readiness check and Dramatiq's Redis broker; one client library for both | 2026-10-17 |
| dramatiq | 2.2.1 | 2026-09-02 | https://pypi.org/pypi/dramatiq/json. Pinned as `dramatiq[redis]==2.2.1`: the extra requires `redis>=4.0,<9.0`, which the redis pin satisfies. Maintenance re-checked for ADR-0009: five releases between 2025-11-18 (2.0.0) and 2026-09-02 (2.2.1), changelog https://raw.githubusercontent.com/Bogdanp/dramatiq/master/docs/source/changelog.rst | 2026-10-18 |
| pytest | 9.1.1 | 2026-06-19 | https://pypi.org/pypi/pytest/json | 2026-10-17 |
| ruff | 0.17.1 | 2026-10-15 | https://pypi.org/pypi/ruff/json | 2026-10-17 |
| mypy | 2.4.0 | 2026-10-01 | https://pypi.org/pypi/mypy/json | 2026-10-17 |
| starlette | 1.8.0 | 2026-10-13 | https://pypi.org/pypi/starlette/json. Imported directly by the backend, so pinned explicitly; the version fastapi 0.143.3 resolves | 2026-10-17 |
| httpx2 | 2.13.1 | 2026-09-23 | https://pypi.org/pypi/httpx2/json. Test client behind Starlette's `TestClient`; Starlette 1.8.0 deprecates `httpx` there in favour of `httpx2` (https://github.com/pydantic/httpx2) | 2026-10-17 |
| pip-audit | 2.10.1 | 2026-06-10 | https://pypi.org/pypi/pip-audit/json. Audits both requirements files and `backend/constraints.txt` against the PyPI vulnerability data in `security.yml` | 2026-10-18 |
| bandit | 1.9.4 | 2026-02-25 | https://pypi.org/pypi/bandit/json. `bandit -r backend/app` in `security.yml`, alongside ruff's `S` rules | 2026-10-18 |
| pre-commit | 4.7.0 | 2026-10-12 | https://pypi.org/pypi/pre-commit/json. Runs the optional local hooks in `.pre-commit-config.yaml` | 2026-10-18 |

None of these excludes Python 3.13 or 3.14 through `requires-python` (highest floor: `>=3.11`, SQLAlchemy, pydantic-settings, starlette and pre-commit).

`backend/constraints.txt` pins every package a clean install of `backend/requirements.txt` brings in, transitive dependencies included; the api image, `make bootstrap` and the backend CI jobs install with `-c backend/constraints.txt`. Regenerate it with `make constraints` whenever `requirements.txt` changes, a Dependabot pull request included (otherwise the `-c` install fails on the old pin): the target installs `backend/requirements.txt` with `--only-binary=:all:`, as the api image does, into a throwaway `.venv-constraints`, writes the file's header with the date and interpreter and the output of `pip freeze` below it, and removes the environment. `make constraints PYTHON=python3.14` uses the image's Python; 3.13 freezes the same set. The `constraints` check in `make bootstrap` and the backend workflow fails with `backend/constraints.txt is stale: run make constraints` when a pin disagrees. `make constraints` resolves `requirements.txt` only, so it cannot clear a `requirements-dev.txt` bump that needs a newer version of a package the runtime set shares: raise that pin by hand in `backend/constraints.txt`, or bump the runtime requirement that brings it in and run `make constraints`.

The pins in the requirement files and the constraints are name and version only, without hashes: pip does not check what it downloads against a recorded hash. `pip-compile --generate-hashes` (with pip's `--require-hashes`) is a Phase 1 candidate.

## Web (npm)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| react, react-dom | 19.3.1 | 2026-10-14 | https://registry.npmjs.org/react | 2026-10-17 |
| vite | 8.3.4 | 2026-10-08 | https://registry.npmjs.org/vite | 2026-10-17 |
| @vitejs/plugin-react | 6.1.2 | 2026-10-05 | https://registry.npmjs.org/@vitejs%2fplugin-react | 2026-10-17 |
| typescript | 5.9.3 | 2025-09-30 | https://registry.npmjs.org/typescript. Newest release `npm ci` accepts with openapi-typescript 7.13.0 (peer `^5.x`) and typescript-eslint 8.71.2 (peer `<6.1.0`). Checked 2026-10-18 on Node.js 26.12.0: with 7.0.2 (latest, 2026-07-08; the native compiler, which ships no `lib/typescript.js`) `tsc -b`, vitest and `vite build` pass, but `npm run lint` stops with "typescript-eslint does not support TS 7.0" and openapi-typescript crashes on `ts.factory`. With 6.0.3 (the newest release typescript-eslint accepts) every check passes and the generated `schema.d.ts` is byte-identical, but `npm ci` fails with `ERESOLVE` on openapi-typescript's peer (`npm install typescript@6.0.3` only warns). Neither tool has a newer line (typescript-eslint `canary` 8.71.3-alpha.13, openapi-typescript `next` 7.0.0-rc.1) | 2026-10-18 |
| typescript-eslint | 8.71.2 | 2026-10-12 | https://registry.npmjs.org/typescript-eslint | 2026-10-17 |
| eslint | 10.13.0 | 2026-10-16 | https://registry.npmjs.org/eslint | 2026-10-17 |
| tailwindcss | 4.3.3 | 2026-07-16 | https://registry.npmjs.org/tailwindcss | 2026-10-17 |
| @tailwindcss/vite | 4.3.3 | 2026-07-16 | https://registry.npmjs.org/@tailwindcss%2fvite | 2026-10-17 |
| shadcn (shadcn/ui CLI) | 4.22.0 | 2026-10-16 | https://registry.npmjs.org/shadcn. Run with `npx shadcn@4.22.0` only; not a dependency of `web/`. As a dependency it brought seven high `npm audit --audit-level=high` advisories (braces <= 3.0.3, GHSA-vfj7-8cjw-p6xm, no fixed release; via micromatch, fast-glob, @shadcn/registry and ts-morph), so a `shadcn add` that re-adds the package must be checked against them | 2026-10-17 |
| vitest | 5.0.5 | 2026-10-15 | https://registry.npmjs.org/vitest | 2026-10-17 |
| @playwright/test | 1.64.1 | 2026-10-14 | https://registry.npmjs.org/@playwright%2ftest | 2026-10-17 |
| openapi-typescript | 7.13.0 | 2026-02-11 | https://registry.npmjs.org/openapi-typescript | 2026-10-17 |
| @eslint/js | 10.0.1 | 2026-02-06 | https://registry.npmjs.org/@eslint%2fjs | 2026-10-18 |
| eslint-plugin-react-hooks | 7.1.1 | 2026-04-17 | https://registry.npmjs.org/eslint-plugin-react-hooks | 2026-10-18 |
| eslint-plugin-react-refresh | 0.5.7 | 2026-09-14 | https://registry.npmjs.org/eslint-plugin-react-refresh | 2026-10-18 |
| globals | 17.13.0 | 2026-10-01 | https://registry.npmjs.org/globals | 2026-10-18 |
| @types/react, @types/react-dom | 19.3.0 | 2026-09-09 | https://registry.npmjs.org/@types%2freact | 2026-10-18 |
| @types/node | 26.6.5 | 2026-10-09 | https://registry.npmjs.org/@types%2fnode. `latest`, matching the Node.js 26 runtime | 2026-10-18 |
| jsdom | 30.1.3 | 2026-10-15 | https://registry.npmjs.org/jsdom. Vitest's DOM environment (chosen over happy-dom); engines `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0` | 2026-10-18 |
| @testing-library/react | 16.3.3 | 2026-08-27 | https://registry.npmjs.org/@testing-library%2freact | 2026-10-18 |
| @testing-library/dom | 10.4.2 | 2026-09-13 | https://registry.npmjs.org/@testing-library%2fdom. Peer of @testing-library/react and @testing-library/jest-dom, so pinned explicitly | 2026-10-18 |
| @testing-library/jest-dom | 7.0.1 | 2026-08-09 | https://registry.npmjs.org/@testing-library%2fjest-dom | 2026-10-18 |
| @base-ui/react | 1.9.0 | 2026-10-09 | https://registry.npmjs.org/@base-ui%2freact. Primitive library of the shadcn `base` base (button.tsx) | 2026-10-18 |
| class-variance-authority | 0.7.1 | 2024-11-26 | https://registry.npmjs.org/class-variance-authority. Declared by the shadcn base-nova init item | 2026-10-18 |
| clsx | 2.1.1 | 2024-04-23 | https://registry.npmjs.org/clsx. With tailwind-merge, behind `cn` in `src/lib/utils.ts` | 2026-10-18 |
| tailwind-merge | 3.7.0 | 2026-09-12 | https://registry.npmjs.org/tailwind-merge | 2026-10-18 |

All rows except typescript are the `latest` dist-tag.

### Known peer constraints

- openapi-typescript 7.13.0: peer `typescript ^5.x`.
- typescript-eslint 8.71.2: peers `typescript >=4.8.4 <6.1.0` and `eslint ^8.57.0 || ^9.0.0 || ^10.0.0`.
- @vitejs/plugin-react 6.1.2: peer `vite ^8.0.0`. @tailwindcss/vite 4.3.3: peer `vite ^5.2.0 || ^6 || ^7 || ^8`. vitest 5.0.5: peer `vite ^6.4.0 || ^7.0.0 || ^8.0.0`.
- react-dom 19.3.1: peer `react ^19.3.1`.
- Node.js engines: vitest 5.0.5 needs `^22.12.0 || ^24.0.0 || >=26.0.0`, eslint 10.13.0 needs `^20.19.0 || ^22.13.0 || >=24`; Node.js 26.12.0 satisfies both.
- The whole set above resolves on Node.js 26.12.0 and npm 11.20.0 (checked 2026-10-18: `npm ci` installs the committed lock without a peer warning, one copy each of typescript and vite). With typescript 6.0.3 or 7.0.2 `npm ci` and `npm install --package-lock-only` fail with `ERESOLVE` (`peer typescript@"^5.x" from openapi-typescript@7.13.0`). `--legacy-peer-deps`, `--force` and `overrides` are not used.
- Revisit TypeScript when both openapi-typescript and typescript-eslint accept 6.x or 7.x.

### shadcn/ui files

`web/components.json`, `web/src/components/ui/button.tsx` and the theme in `web/src/index.css` come from `npx shadcn@4.22.0 init -b base -p nova --no-monorepo` followed by `npx shadcn@4.22.0 add button` (checked 2026-10-18). ui.shadcn.com is blocked from the Phase 0 environment, so the CLI ran with `REGISTRY_URL` pointing at a local mirror of the registry built from https://github.com/shadcn-ui/ui at commit `d2fba50ee5b9113008b5bb908563527b7efd2f27`:

- `apps/v4/public/r/styles/base-nova/*` and `styles/new-york-v4/*` were built with that commit's `apps/v4/scripts/build-registry.mts --registry <style>`. The commit's `packages/shadcn` is version 4.22.0, so the npm 4.22.0 package stood in for it.
- The `/init` response was produced with the commit's `apps/v4/app/(app)/(create)/init/route.ts` logic (`parseDesignSystemConfig`, `buildRegistryBase`, `registryItemSchema`) for the query the CLI sent.
- The CLI ran in a scratch copy of `web/`, and its files were copied into `web/`.

Changes from the CLI output:

- `src/lib/utils.ts` is the classic `cn` (clsx + tailwind-merge) from the same commit's `apps/v4/public/r/styles/new-york/utils.json`, not the generated `export { cn } from "cn"`; `button.tsx` imports `cn` from `@/lib/utils` instead of the `cn` package.
- `src/index.css` drops the Geist font (`@fontsource-variable/geist` and its `--font-sans` override, so the system font stack applies) and the `tw-animate-css` and `shadcn/tailwind.css` imports (nothing uses their variants, utilities or animations). It restricts Tailwind's source scan with `@import "tailwindcss" source("../src")`, is indented with two spaces and ends with a newline.
- The packages `shadcn`, `cn`, `tw-animate-css`, `lucide-react` and `@fontsource-variable/geist` that `init` added are not installed.

When a component needs `shadcn/tailwind.css` (its `data-open` and similar variants), vendor that file as `web/src/styles/shadcn.css` with its upstream path and commit recorded here, rather than adding the `shadcn` package. Re-running the two commands against ui.shadcn.com from an unrestricted network should reproduce `components.json`, `button.tsx` (apart from the `cn` import and the blank line before it) and the theme variables.

## Apple

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Xcode | 27.1 (27A9275) | 2026-10-15 | https://developer.apple.com/news/releases/rss/releases.rss (27.2 is in beta). Requires macOS Tahoe 26.6 or later (release notes below) | 2026-10-17 |
| Swift in Xcode 27.1 | 6.4 | 2026-10-15 | Xcode 27.1 release notes, https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes ("Xcode 27.1 includes Swift 6.4"; the patch level is not stated). https://www.swift.org/api/v1/install/releases.json maps 6.4.0 to Xcode 27.0 | 2026-10-17 |
| Swift standalone toolchain (Linux) | 6.4.1 | 2026-10-12 | https://www.swift.org/api/v1/install/releases.json (`xcode_release: false`: not shipped in an Xcode). Linux image `swift:6.4.1` `sha256:6fbd5978b56a5a9ff05a48f8f678079fc45be496ecda15b4e74e8944fab857be`, https://hub.docker.com/v2/repositories/library/swift/tags/6.4.1 | 2026-10-17 |
| XcodeGen | 2.46.0 | — | `git ls-remote --tags https://github.com/yonaskolb/XcodeGen.git` lists 2.46.0 as the newest tag, as do the newest released heading in https://raw.githubusercontent.com/yonaskolb/XcodeGen/master/CHANGELOG.md and the tag in Homebrew's formula https://raw.githubusercontent.com/Homebrew/homebrew-core/main/Formula/x/xcodegen.rb. No release date: https://github.com/yonaskolb/XcodeGen/releases/latest is blocked from this environment. The `xcode27_0` project format is listed only under the unreleased "Next Version", so `apple/project.yml` keeps 2.46.0's default format, `xcode16_0` (https://raw.githubusercontent.com/yonaskolb/XcodeGen/2.46.0/Docs/ProjectSpec.md). Not verifiable from this environment; the macOS CI job generates the `xcode16_0` project with Homebrew's XcodeGen and builds both schemes with Xcode 27.1 (https://github.com/theonewizard/OpenNote/actions/runs/39112872275) | 2026-10-18 |
| swift-crypto | 5.0.1 | 2026-10-09 (date of the tagged commit) | `git ls-remote --tags https://github.com/apple/swift-crypto.git` (5.0.1 is the newest release tag, commit `1c80d3aff53fedc445b60692980cb4f19a618657`; the release page https://github.com/apple/swift-crypto/releases/tag/5.0.1 is blocked from this environment) and its manifest https://raw.githubusercontent.com/apple/swift-crypto/5.0.1/Package.swift (`swift-tools-version:6.2`; depends on swift-asn1 `from: "1.2.0"`, which SwiftPM resolves). Pinned `exact: "5.0.1"` in `apple/Packages/OpenNoteCore/Package.swift` and linked on Linux only, where CryptoKit does not exist; Apple platforms use CryptoKit. The committed `Package.resolved` files (Phase 0 Task 9, the first CI resolution) pin it and swift-asn1 1.7.3 (`3b6410f7dee09eb33cdd26260c5fd47fda19b0e2`); the Linux CI job builds it in the `swift:6.4.1` image and runs `OpenNoteCore`'s tests (https://github.com/theonewizard/OpenNote/actions/runs/39112872275) | 2026-10-18 |
| swift-openapi-generator | 1.14.1 | 2026-10-13 (date of the tagged commit) | `git ls-remote --tags https://github.com/apple/swift-openapi-generator.git` (1.14.1 is the newest release tag, commit `bf578ce357a0d2aa07af9de41b083cc2c986a498`; the release page https://github.com/apple/swift-openapi-generator/releases/tag/1.14.1 is blocked from this environment) and its manifest https://raw.githubusercontent.com/apple/swift-openapi-generator/1.14.1/Package.swift (`swift-tools-version:6.2`; requires swift-openapi-runtime `from: "1.13.0"`. Build plugin `OpenAPIGenerator`; its README lists the plugin as supported on macOS 10.15+, Linux and Windows). Pinned `exact: "1.14.1"` in `apple/Packages/OpenNoteAPI/Package.swift`. Not compiled from this environment (no Swift toolchain); the macOS CI job builds it and runs its plugin with Xcode 27.1 (https://github.com/theonewizard/OpenNote/actions/runs/39112872275). Its direct and transitive dependencies resolve to OpenAPIKit 6.4.0, Yams 6.2.2, swift-algorithms 1.2.1, swift-argument-parser 1.8.2 and swift-numerics 1.1.1, pinned in the committed `Package.resolved` files | 2026-10-18 |
| swift-openapi-runtime | 1.13.1 | 2026-10-15 (date of the tagged commit) | `git ls-remote --tags https://github.com/apple/swift-openapi-runtime.git` (1.13.1 is the newest release tag, commit `ad7a252e215870ea2de9cf8605ff9336b004183a`; the release page https://github.com/apple/swift-openapi-runtime/releases/tag/1.13.1 is blocked from this environment) and its manifest https://raw.githubusercontent.com/apple/swift-openapi-runtime/1.13.1/Package.swift (`swift-tools-version:6.2`; depends on swift-http-types `from: "1.7.0"`, which SwiftPM resolves). Pinned `exact: "1.13.1"` in `apple/Packages/OpenNoteAPI/Package.swift`. Not compiled from this environment (no Swift toolchain); the macOS CI job builds it with Xcode 27.1 (https://github.com/theonewizard/OpenNote/actions/runs/39112872275). swift-http-types resolves to 1.8.0, pinned in the committed `Package.resolved` files | 2026-10-18 |

## Infrastructure tooling

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Helm | v4.3.1 | 2026-10-15 | Not verified from this environment: https://github.com/helm/helm/releases and https://get.helm.sh are blocked. Read instead: the Go module proxy, https://proxy.golang.org/helm.sh/helm/v4/@latest (v3 line: v3.22.1) | 2026-10-17 |
| kustomize | v5.8.3 | 2026-10-08 | Not verified from this environment: https://github.com/kubernetes-sigs/kustomize/releases is blocked. Read instead: https://proxy.golang.org/sigs.k8s.io/kustomize/kustomize/v5/@latest (tag `kustomize/v5.8.3`). Renders the kustomizations locally; CI uses `kubectl kustomize` (see Tools the actions install) | 2026-10-18 |
| Docker Compose | v5.6.0 | 2026-10-02 | Not verified from this environment: https://github.com/docker/compose/releases is blocked. Read instead: https://proxy.golang.org/github.com/docker/compose/v5/@latest (no v6 module) | 2026-10-17 |
| Podman | v6.1.4 | 2026-10-12 | Not verified from this environment: https://github.com/containers/podman/releases is blocked. Read instead: https://proxy.golang.org/go.podman.io/podman/v6/@latest (no v7 module at go.podman.io) | 2026-10-17 |

## Continuous integration

### GitHub Actions

Every `uses:` in `.github/workflows/` names the full commit SHA of a release tag, with the tag as a comment; Dependabot's `github-actions` updates keep them current. Each SHA was resolved with `git ls-remote --tags https://github.com/<owner>/<repo>` (the commit the tag points to; every tag below is lightweight) and checked to lie on the repository's default branch, except where a row says otherwise. Release pages on github.com are blocked from this environment, so "Released" is the date of the tagged commit.

| Action | Version | Commit | Released | Checked |
|---|---|---|---|---|
| actions/checkout | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` | 2026-07-17 | 2026-10-18 |
| actions/setup-python | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` | 2026-07-19 | 2026-10-18 |
| actions/setup-node | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` | 2026-10-07 | 2026-10-18 |
| aquasecurity/setup-trivy | v0.3.1 | `81e514348e19b6112ce2a7e3ecbafe19c1e1f567` (lightweight tag; the action's own steps pin `actions/checkout` and `actions/cache` by SHA, and the Trivy install script to a commit of aquasecurity/trivy) | 2026-06-03 | 2026-10-18 |
| azure/setup-helm | v5.0.1 | `9bc31f4ebc9c6b171d7bfbaa5d006ae7abdb4310` (lightweight tag). Unlike the rows above, the commit is not on `main` but on the release branch `releases/v5.0.1`: a "build" commit of the action's release workflow that adds only the compiled `lib/index.js` on top of `main`'s `95ecf4967d92f8074e91c548e394f8ac547da403` ("Bump version to 5.0.1"). It downloads Helm from https://get.helm.sh without checking a checksum | 2026-06-23 | 2026-10-18 |
| gitleaks/gitleaks-action | v3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e`. Free for repositories of a personal account, which this is (the run log says "[theonewizard] is an individual user. No license key is required."); a repository of an organisation needs a `GITLEAKS_LICENSE` secret | 2026-05-30 | 2026-10-18 |

### Tools the actions install

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Trivy | v0.76.0 | 2026-10-14 | Installed by setup-trivy (its `version` input, once in `containers.yml` and once in `security.yml`; the default would be `latest`); the workflows then run `trivy image` and `trivy fs` directly. `git ls-remote --tags https://github.com/aquasecurity/trivy` (commit `531360e5d2a88e732373f1614ba99a38738538b8`), the same as https://proxy.golang.org/github.com/aquasecurity/trivy/@v/v0.76.0.info | 2026-10-18 |
| gitleaks | 8.30.1 | 2026-03-12 (tagged commit) | Set with `GITLEAKS_VERSION` in `security.yml`; gitleaks-action v3.0.0 defaults to 8.24.3. `git ls-remote --tags https://github.com/gitleaks/gitleaks`: the tag points to `83d9cd684c87d95d656c1458ef04895a7f1cbd8e`, which is on no branch and changes only `.goreleaser.yml` on top of `8d1f98c7967eb1e79cb44ac6241a124e145d2165` (2026-02-21), the commit the Go module proxy recorded for v8.30.1 (https://proxy.golang.org/github.com/zricethezav/gitleaks/v8/@latest). The tag was moved once to fix the release build; the source is the same | 2026-10-18 |
| Helm | v4.3.1 | 2026-10-15 | Installed by setup-helm (its `version` input, in the `manifests` job of `containers.yml`; the runner image's own Helm is 3.22.0); the job prints `helm version`. See the Helm row under Infrastructure tooling. First green run: https://github.com/theonewizard/OpenNote/actions/runs/39119290990 (commit `cb66c10`) | 2026-10-18 |
| kubeconform | v0.8.0 | 2026-06-04 (tagged commit) | Runs as the image `ghcr.io/yannh/kubeconform:v0.8.0@sha256:faffaf43f95aa6425306e1ab8d6fcad72acb9049158f38e574c085ea1ec0f64e` (the multi-platform index; linux/amd64 is `sha256:5103f6f5e89061728aad4ad5a250627dd0fc9b2a92eb876f3762677a4222f9e0`), read from the ghcr.io registry API. The release downloads on github.com, and with them the tarballs' checksums, are blocked from this environment. `git ls-remote --tags https://github.com/yannh/kubeconform`: v0.8.0 is the newest tag, commit `02374e583d700721f57300fae78e11acd27ee539` on `master`, the same as https://proxy.golang.org/github.com/yannh/kubeconform/@v/v0.8.0.info. Updated by hand: Dependabot does not update images named in workflows. First green run: https://github.com/theonewizard/OpenNote/actions/runs/39119290990 (56 of 56 resources valid) | 2026-10-18 |
| kubectl (`kubectl kustomize`) | the runner image's: 1.37.1 on image 20261012.334.1 | — | Not pinned; the `manifests` job prints `kubectl version --client`, which includes its kustomize version, and that output is the record: the runner image is whatever `ubuntu-latest` resolves to, and GitHub moves that label to Ubuntu 26 from 2026-10-19 (an annotation of run 39119290990), so the README cited is the Ubuntu 24.04 one of the check date. https://raw.githubusercontent.com/actions/runner-images/main/images/ubuntu/Ubuntu2404-Readme.md | 2026-10-18 |
| Kubernetes JSON schemas | 1.29.0 (the chart's `kubeVersion` floor) and `master` | — | kubeconform's default location, https://github.com/yannh/kubernetes-json-schema (branch `master`, not pinned) | 2026-10-18 |
| OpenShift Route schema | `openshift/v4.15-strict/route_route.openshift.io_v1.json` at datreeio/CRDs-catalog commit `501527ab9c40c827144c8f45945b25a023e344ce` | — | The newest OpenShift schema set in the catalog (it has v4.11 and v4.15); the commit was `HEAD` of `main` on the check date (`git ls-remote`) and is pinned in the job's `OPENSHIFT_SCHEMAS`. Updated by hand. First green run: https://github.com/theonewizard/OpenNote/actions/runs/39119290990 | 2026-10-18 |
| XcodeGen on the macOS runner | newest Homebrew formula (not pinned) | — | `brew install xcodegen` in `apple.yml`; the job prints `xcodegen --version`. `apple/project.yml` requires 2.46.0 or newer (XcodeGen row above) | 2026-10-18 |

### CI runners

| Label | Image | Source | Checked |
|---|---|---|---|
| `ubuntu-latest` | Ubuntu 24.04 (x64) on the check date; GitHub moves the label to Ubuntu 26 from 2026-10-19 (an annotation of run 39119290990) | https://raw.githubusercontent.com/actions/runner-images/main/README.md | 2026-10-18 |
| `xcode-27` | macOS 27.0.1, arm64, image 20261012.0260.1, a public preview. Xcode 27.1 (27A9275) is at `/Applications/Xcode_27.1.app` (a link to `Xcode_27.1_Release_Candidate.app`, the same build as the release); the image default is 27.0 and 27.2 is a beta, so `apple.yml` selects 27.1 explicitly. Simulator runtimes: iOS 27.0 only | https://raw.githubusercontent.com/actions/runner-images/main/images/macos/xcode-27-arm64-Readme.md. `macos-latest` and `macos-26` carry Xcode 26.x only (https://raw.githubusercontent.com/actions/runner-images/main/images/macos/macos-26-arm64-Readme.md) | 2026-10-18 |

The service and job containers are the pgvector, Valkey and Swift images of the rows above, by tag and digest.

### Packages the image builds installed

The containers workflow prints what the images actually installed (`rpm -q` in each image, `valkey-server --version`). Run https://github.com/theonewizard/OpenNote/actions/runs/39112872256 (2026-10-18, commit `736ca1c`; the first build, run 39111658293, installed the same versions) built every image from its planned base, so no fallback of ADR-0010 was needed.

| Image | Package | Installed (x86_64) |
|---|---|---|
| `opennote-api` (also the worker) | `python3.14` (UBI 9.8 AppStream) | `3.14.8-1.el9_8` |
| `opennote-web` | `nginx-core` (module stream `nginx:1.26`, UBI 9.8 AppStream) | `2:1.26.3-9.module+el9.8.0+24845+a897661e.4` |
| `opennote-postgres` | `postgresql18-server`, `postgresql18-contrib` (PGDG) | `18.6-1PGDG.rhel9.8` |
| `opennote-postgres` | `pgvector_18` (PGDG) | `0.8.7-1PGDG.rhel9.8` |
| `opennote-postgres` | PGDG signing key | `gpg-pubkey-08b40d20-6581afc1`, "PostgreSQL RPM Repository", fingerprint `D4BF 08AE 67A0 B4C7 A1DB  CCD2 40BC A2B4 08B4 0D20` (created 2023-12-19, no expiry); the whole decoded key (1774 bytes) has SHA-256 `0f206e45758cfc3d926aab50fd1d4f2f13571a26dc1393097c8db91fec0ef3bd`. The Containerfile imports the key only if both match; run https://github.com/theonewizard/OpenNote/actions/runs/39116135741 printed the digest it computed, which matched |
| `opennote-valkey` | Valkey, built from the 9.1.2 source release | `9.1.2`, jemalloc 5.3.0 |

### pre-commit hooks

`.pre-commit-config.yaml` pins each hook repository to the commit its tag pointed to on the check date (`git ls-remote --tags`), with the tag in a `# frozen:` comment.

| Hook repository | Version | Commit | Released | Checked |
|---|---|---|---|---|
| pre-commit/pre-commit-hooks | v6.0.0 | `3e8a8703264a2f4a69428a0aa4dcb512790b2c8c` | 2025-08-09 | 2026-10-18 |
| astral-sh/ruff-pre-commit | v0.17.1 (ruff 0.17.1, as in `requirements-dev.txt`) | `38bfb07c0c64c304f47eb52090f8288150c77730` | 2026-10-15 | 2026-10-18 |
| gitleaks/gitleaks | v8.30.1 (see Tools the actions install) | `83d9cd684c87d95d656c1458ef04895a7f1cbd8e` | 2026-03-12 | 2026-10-18 |

## Python decision

The [architecture specification](../superpowers/specs/2026-10-17-opennote-architecture-design.md) (§11) requires that the container base offer the latest stable Python; otherwise the newest UBI-available Python is used and the gap is recorded here.

**Verified.** A CI probe, run https://github.com/theonewizard/OpenNote/actions/runs/39071433587 on 2026-10-17, ran `docker manifest inspect registry.access.redhat.com/<image>:latest`:

- `ubi9/python-314` and `ubi9/python-312` exist.
- `ubi9/python-313`, `ubi10/python-312`, `ubi10/python-313` and `ubi10/python-314` do not exist.

The same run pulled `ubi9/ubi-minimal:9.8` (RHEL 9.8) and `ubi10/ubi-minimal:10.2` (RHEL 10.2) with the digests recorded above; neither image has `python3` installed.

**Verified since (Phase 0 Task 9).** The containers workflow's image build installs `python3.14` 3.14.8-1.el9_8 with `microdnf` in `ubi9/ubi-minimal:9.8`, the API and worker image ([Packages the image builds installed](#packages-the-image-builds-installed)).

**Gap.** The runtime Python (3.14) is one minor release behind the latest stable release (3.15.0).

- Not probed: the `python-315` images (`ubi9/python-315`, `ubi10/python-315`) and the `-minimal` images sclorg upstream builds (among them `ubi9/python-314-minimal`, `ubi10/python-312-minimal` and `ubi10/python-314-minimal`).
