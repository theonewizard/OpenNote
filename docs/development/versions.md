# Tool Versions

Resolved 2026-10-17 for Phase 0 (`CLAUDE.md` §1.8: latest stable release; design §6 versions are floors). Later tasks pin these versions in `backend/requirements*.txt`, `web/package.json`, Containerfiles and CI unless a peer constraint recorded here says otherwise. Re-check a row before upgrading it.

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
| Node.js (LTS) | v24.22.0 "Krypton" | 2026-10-14 | — | https://nodejs.org/dist/index.json (current release v26.12.0 is not LTS). Pinned in the root `.nvmrc`; `web/package.json` declares `engines` `node >=24.22.0 <25`, `npm >=11` | 2026-10-17 |
| npm | 11.19.1, the npm bundled with Node.js 24.22.0 | 2026-08-26 | — | https://nodejs.org/dist/index.json (`npm` field of v24.22.0). Chosen on purpose: the bundled npm is what `make bootstrap` and CI get without a second install. Newer release not adopted: npm `latest` 12.2.0 (2026-09-30, engines `node ^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`), https://registry.npmjs.org/npm | 2026-10-17 |
| UBI 9 minimal | `registry.access.redhat.com/ubi9/ubi-minimal:9.8` (RHEL 9.8) | — | `sha256:c4c285d42941ebb2bd4da878479008e1e4536bb599aad1dbe568f89de9053661` | Not verified from this environment: https://registry.access.redhat.com/v2/ubi9/ubi-minimal/tags/list is blocked. Read instead: Docker Hub's Red Hat mirror https://hub.docker.com/v2/repositories/redhat/ubi9-minimal/tags/9.8. The CI probe pulled the Red Hat registry tag with the same digest | 2026-10-17 |
| UBI 9 | `registry.access.redhat.com/ubi9/ubi:9.8` | — | `sha256:16e9e43d99e181463513cc84a514859b1abb9460f1c4d9e208da4b4e51cd5cc3` (Docker Hub mirror) | Not verified from this environment: https://registry.access.redhat.com/v2/ubi9/ubi/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi9/tags/9.8 | 2026-10-17 |
| UBI 10 minimal | `registry.access.redhat.com/ubi10/ubi-minimal:10.2` (RHEL 10.2) | — | `sha256:552f8cc1ddb0bc9e411065c78499aa4dbc2c4ea9bd057aa0e6e44940db13acb5` | Not verified from this environment: https://registry.access.redhat.com/v2/ubi10/ubi-minimal/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi10-minimal/tags/10.2. The CI probe pulled the Red Hat registry tag with the same digest | 2026-10-17 |
| UBI 10 | `registry.access.redhat.com/ubi10/ubi:10.2` | — | `sha256:a75ad754aa048d808dd3260243452f8c9a665831d0493b4c9d92f0c88fe2f8c3` (Docker Hub mirror) | Not verified from this environment: https://registry.access.redhat.com/v2/ubi10/ubi/tags/list is blocked. Read instead: https://hub.docker.com/v2/repositories/redhat/ubi10/tags/10.2 | 2026-10-17 |
| Node.js builder image (web) | `node:24.22.0-trixie-slim` (Debian 13) | — | `sha256:7f486cabe892bff8fef04c0f7da8dba84a560be3e4e2740b7a86afc57ebec315` | https://hub.docker.com/v2/repositories/library/node/tags/24.22.0-trixie-slim. Used only as the builder stage of `opennote-web`, because it is exactly the release in `.nvmrc` (no UBI Node.js image can be checked from here); only the static build output reaches the UBI runtime image. `24.22.0-slim` is the bookworm variant (`sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5`) | 2026-10-18 |
| nginx (web runtime) | 1.26.3, module stream `nginx:1.26` of RHEL 9.8, installed in `ubi9/ubi-minimal:9.8` | — | — (RPM, not pinned; the base image is) | Not verified from this environment: the UBI repositories (https://cdn-ubi.redhat.com) are blocked. Read instead: CentOS Stream https://gitlab.com/redhat/centos-stream/rpms/nginx, branches `stream-nginx-1.22`, `-1.24` and `-1.26-rhel-9.8.0` (spec at 1.26.3; a 1.30 stream exists only for RHEL 9.10). Red Hat publishes `ubi9/nginx-126` on registry.access.redhat.com, so the stream should be in the UBI repositories; the image build verifies it. Gap: upstream stable is 1.30.6 (Docker Hub `nginx:stable` = `1.30.6`, https://hub.docker.com/v2/repositories/library/nginx/tags/stable; nginx.org is blocked) | 2026-10-18 |
| PostgreSQL and pgvector RPMs (PGDG) | `postgresql18-server-18.6`, `postgresql18-contrib-18.6`, `pgvector_18-0.8.7` | — | — | Not verified from this environment: the PGDG repository https://download.postgresql.org/pub/repos/yum/18/redhat/rhel-9-x86_64/ and its key https://download.postgresql.org/pub/repos/yum/keys/PGDG-RPM-GPG-KEY-RHEL are blocked. Package names, paths and the repository layout are PGDG's long-standing ones, the versions those of the PostgreSQL and pgvector rows above; the `opennote-postgres` image build verifies them. RHEL 9.8 has its own `postgresql:18` stream (18.1 with pgvector 0.8.7; https://gitlab.com/redhat/centos-stream/rpms/postgresql and https://gitlab.com/redhat/centos-stream/rpms/pgvector, branches `stream-postgresql-18-rhel-9.8.0`), but Red Hat publishes its PostgreSQL images only on registry.redhat.io, which suggests the server is not in the UBI repositories (ADR-0010) | 2026-10-18 |
| Valkey source release | 9.1.2, https://github.com/valkey-io/valkey/archive/refs/tags/9.1.2.tar.gz | 2026-08-31 | archive `sha256:19c23908e7d57e8d91ef85b41f5646307582f10f4f0fb999bbf89ed24ec9c983` | Not verified from this environment: the archive download is blocked. The checksum is the same in the upstream image project's https://raw.githubusercontent.com/valkey-io/valkey-container/mainline/versions.json and in Homebrew's https://raw.githubusercontent.com/Homebrew/homebrew-core/main/Formula/v/valkey.rb; the `opennote-valkey` build checks it. Built from source because RHEL 9 packages Valkey 8.1.10 (CentOS Stream https://gitlab.com/redhat/centos-stream/rpms/valkey, branch c9s) | 2026-10-18 |

## Backend (PyPI)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| fastapi | 0.143.3 | 2026-10-16 | https://pypi.org/pypi/fastapi/json | 2026-10-17 |
| uvicorn | 0.54.0 | 2026-09-25 | https://pypi.org/pypi/uvicorn/json | 2026-10-17 |
| pydantic | 2.14.1 | 2026-10-11 | https://pypi.org/pypi/pydantic/json | 2026-10-17 |
| pydantic-settings | 2.16.0 | 2026-10-14 | https://pypi.org/pypi/pydantic-settings/json | 2026-10-17 |
| SQLAlchemy | 2.1.5 | 2026-10-16 | https://pypi.org/pypi/sqlalchemy/json | 2026-10-17 |
| alembic | 1.20.0 | 2026-09-11 | https://pypi.org/pypi/alembic/json | 2026-10-17 |
| psycopg | 3.3.6 | 2026-09-18 | https://pypi.org/pypi/psycopg/json. Pinned as `psycopg[binary]==3.3.6`: the extra installs `psycopg-binary` 3.3.6, so local venvs and the image need no libpq build | 2026-10-17 |
| redis (redis-py) | 8.1.0 | 2026-07-30 | https://pypi.org/pypi/redis/json. The Valkey client (Valkey speaks RESP): the readiness check and Dramatiq's Redis broker; one client library for both | 2026-10-17 |
| dramatiq | 2.2.1 | 2026-09-02 | https://pypi.org/pypi/dramatiq/json. Pinned as `dramatiq[redis]==2.2.1`: the extra requires `redis>=4.0,<9.0`, which the redis pin satisfies. Maintenance re-checked for ADR-0009: five releases between 2025-11-18 (2.0.0) and 2026-09-02 (2.2.1), changelog https://raw.githubusercontent.com/Bogdanp/dramatiq/master/docs/source/changelog.rst | 2026-10-18 |
| pytest | 9.1.1 | 2026-06-19 | https://pypi.org/pypi/pytest/json | 2026-10-17 |
| ruff | 0.17.1 | 2026-10-15 | https://pypi.org/pypi/ruff/json | 2026-10-17 |
| mypy | 2.4.0 | 2026-10-01 | https://pypi.org/pypi/mypy/json | 2026-10-17 |
| starlette | 1.8.0 | 2026-10-13 | https://pypi.org/pypi/starlette/json. Imported directly by the backend, so pinned explicitly; the version fastapi 0.143.3 resolves | 2026-10-17 |
| httpx2 | 2.13.1 | 2026-09-23 | https://pypi.org/pypi/httpx2/json. Test client behind Starlette's `TestClient`; Starlette 1.8.0 deprecates `httpx` there in favour of `httpx2` (https://github.com/pydantic/httpx2) | 2026-10-17 |

None of these excludes Python 3.13 or 3.14 through `requires-python` (highest floor: `>=3.11`, SQLAlchemy and pydantic-settings).

## Web (npm)

| Package | Version | Released | Source | Checked |
|---|---|---|---|---|
| react, react-dom | 19.3.1 | 2026-10-14 | https://registry.npmjs.org/react | 2026-10-17 |
| vite | 8.3.4 | 2026-10-08 | https://registry.npmjs.org/vite | 2026-10-17 |
| @vitejs/plugin-react | 6.1.2 | 2026-10-05 | https://registry.npmjs.org/@vitejs%2fplugin-react | 2026-10-17 |
| typescript | 5.9.3 | 2025-09-30 | https://registry.npmjs.org/typescript. Newest release accepted by both openapi-typescript and typescript-eslint (see peer constraints). Latest stable is 7.0.2 (2026-07-08); not adoptable yet because openapi-typescript 7.13.0 requires `^5.x` and typescript-eslint 8.71.2 requires `<6.1.0`. create-vite 9.2.1 scaffolds `~6.0.2`; `web/` pins 5.9.3 for the same reason | 2026-10-17 |
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
| @types/node | 24.19.2 | 2026-10-09 | https://registry.npmjs.org/@types%2fnode. Newest 24.x, matching the Node.js 24 LTS runtime; `latest` 26.6.5 describes Node.js 26 | 2026-10-18 |
| jsdom | 30.1.3 | 2026-10-15 | https://registry.npmjs.org/jsdom. Vitest's DOM environment (chosen over happy-dom); engines `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0` | 2026-10-18 |
| @testing-library/react | 16.3.3 | 2026-08-27 | https://registry.npmjs.org/@testing-library%2freact | 2026-10-18 |
| @testing-library/dom | 10.4.2 | 2026-09-13 | https://registry.npmjs.org/@testing-library%2fdom. Peer of @testing-library/react and @testing-library/jest-dom, so pinned explicitly | 2026-10-18 |
| @testing-library/jest-dom | 7.0.1 | 2026-08-09 | https://registry.npmjs.org/@testing-library%2fjest-dom | 2026-10-18 |
| @base-ui/react | 1.9.0 | 2026-10-09 | https://registry.npmjs.org/@base-ui%2freact. Primitive library of the shadcn `base` base (button.tsx) | 2026-10-18 |
| class-variance-authority | 0.7.1 | 2024-11-26 | https://registry.npmjs.org/class-variance-authority. Declared by the shadcn base-nova init item | 2026-10-18 |
| clsx | 2.1.1 | 2024-04-23 | https://registry.npmjs.org/clsx. With tailwind-merge, behind `cn` in `src/lib/utils.ts` | 2026-10-18 |
| tailwind-merge | 3.7.0 | 2026-09-12 | https://registry.npmjs.org/tailwind-merge | 2026-10-18 |

All rows except typescript and @types/node are the `latest` dist-tag.

### Known peer constraints

- openapi-typescript 7.13.0: peer `typescript ^5.x`.
- typescript-eslint 8.71.2: peers `typescript >=4.8.4 <6.1.0` and `eslint ^8.57.0 || ^9.0.0 || ^10.0.0`.
- @vitejs/plugin-react 6.1.2: peer `vite ^8.0.0`. @tailwindcss/vite 4.3.3: peer `vite ^5.2.0 || ^6 || ^7 || ^8`. vitest 5.0.5: peer `vite ^6.4.0 || ^7.0.0 || ^8.0.0`.
- react-dom 19.3.1: peer `react ^19.3.1`.
- Node.js engines: vitest 5.0.5 needs `^22.12.0 || ^24.0.0 || >=26.0.0`, eslint 10.13.0 needs `^20.19.0 || ^22.13.0 || >=24`; Node.js 24.22.0 satisfies both.
- The whole set above resolves with `npm install --package-lock-only` on Node.js 24.22.0 and npm 11.19.1 (checked 2026-10-17, one copy each of typescript and vite). With typescript 7.0.2 it fails with `ERESOLVE` (`peer typescript@"^5.x" from openapi-typescript@7.13.0`). `--legacy-peer-deps`, `--force` and `overrides` are not used.
- Revisit TypeScript when both openapi-typescript and typescript-eslint accept 6.x or 7.x.

### shadcn/ui files

`web/components.json`, `web/src/components/ui/button.tsx` and the theme in `web/src/index.css` come from `npx shadcn@4.22.0 init -b base -p nova --no-monorepo` followed by `npx shadcn@4.22.0 add button` (checked 2026-10-18). ui.shadcn.com is blocked from the Phase 0 environment, so the CLI ran with `REGISTRY_URL` pointing at a local mirror of the registry built from https://github.com/shadcn-ui/ui at commit `d2fba50ee5b9113008b5bb908563527b7efd2f27`:

- `apps/v4/public/r/styles/base-nova/*` and `styles/new-york-v4/*` were built with that commit's `apps/v4/scripts/build-registry.mts --registry <style>`. The commit's `packages/shadcn` is version 4.22.0, so the npm 4.22.0 package stood in for it.
- The `/init` response was produced with the commit's `apps/v4/app/(app)/(create)/init/route.ts` logic (`parseDesignSystemConfig`, `buildRegistryBase`, `registryItemSchema`) for the query the CLI sent.
- The CLI ran in a scratch copy of `web/`, and its files were copied into `web/`.

Changes from the CLI output:

- `src/lib/utils.ts` is the classic `cn` (clsx + tailwind-merge) from the same commit's `apps/v4/public/r/styles/new-york/utils.json`, not the generated `export { cn } from "cn"`; `button.tsx` imports `cn` from `@/lib/utils` instead of the `cn` package.
- `src/index.css` drops the Geist font (`@fontsource-variable/geist` and its `--font-sans` override, so the system font stack applies) and the `tw-animate-css` and `shadcn/tailwind.css` imports (nothing uses their variants, utilities or animations). It restricts Tailwind's source scan with `@import "tailwindcss" source("../src")` and is indented with two spaces.
- The packages `shadcn`, `cn`, `tw-animate-css`, `lucide-react` and `@fontsource-variable/geist` that `init` added are not installed.

When a component needs `shadcn/tailwind.css` (its `data-open` and similar variants), vendor that file as `web/src/styles/shadcn.css` with its upstream path and commit recorded here, rather than adding the `shadcn` package. Re-running the two commands against ui.shadcn.com from an unrestricted network should reproduce `components.json`, `button.tsx` (apart from the `cn` import) and the theme variables.

## Apple

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Xcode | 27.1 (27A9275) | 2026-10-15 | https://developer.apple.com/news/releases/rss/releases.rss (27.2 is in beta). Requires macOS Tahoe 26.6 or later (release notes below) | 2026-10-17 |
| Swift in Xcode 27.1 | 6.4 | 2026-10-15 | Xcode 27.1 release notes, https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes ("Xcode 27.1 includes Swift 6.4"; the patch level is not stated). https://www.swift.org/api/v1/install/releases.json maps 6.4.0 to Xcode 27.0 | 2026-10-17 |
| Swift standalone toolchain (Linux) | 6.4.1 | 2026-10-12 | https://www.swift.org/api/v1/install/releases.json (`xcode_release: false`: not shipped in an Xcode). Linux image `swift:6.4.1` `sha256:6fbd5978b56a5a9ff05a48f8f678079fc45be496ecda15b4e74e8944fab857be`, https://hub.docker.com/v2/repositories/library/swift/tags/6.4.1 | 2026-10-17 |
| XcodeGen | 2.46.0 | — | `git ls-remote --tags https://github.com/yonaskolb/XcodeGen.git` lists 2.46.0 as the newest tag, as do the newest released heading in https://raw.githubusercontent.com/yonaskolb/XcodeGen/master/CHANGELOG.md and the tag in Homebrew's formula https://raw.githubusercontent.com/Homebrew/homebrew-core/main/Formula/x/xcodegen.rb. No release date: https://github.com/yonaskolb/XcodeGen/releases/latest is blocked from this environment. The `xcode27_0` project format is listed only under the unreleased "Next Version", so `apple/project.yml` keeps 2.46.0's default format, `xcode16_0` (https://raw.githubusercontent.com/yonaskolb/XcodeGen/2.46.0/Docs/ProjectSpec.md). Not verified from this environment: that Xcode 27.1 opens the `xcode16_0` format; the macOS CI build is the first check | 2026-10-18 |
| swift-crypto | 5.0.1 | 2026-10-09 (date of the tagged commit) | `git ls-remote --tags https://github.com/apple/swift-crypto.git` (5.0.1 is the newest release tag, commit `1c80d3aff53fedc445b60692980cb4f19a618657`; the release page https://github.com/apple/swift-crypto/releases/tag/5.0.1 is blocked from this environment) and its manifest https://raw.githubusercontent.com/apple/swift-crypto/5.0.1/Package.swift (`swift-tools-version:6.2`; depends on swift-asn1 `from: "1.2.0"`, which SwiftPM resolves). Pinned `exact: "5.0.1"` in `apple/Packages/OpenNoteCore/Package.swift` and linked on Linux only, where CryptoKit does not exist; Apple platforms use CryptoKit. No `Package.resolved` is committed | 2026-10-18 |

## Infrastructure tooling

| Tool | Version | Released | Source | Checked |
|---|---|---|---|---|
| Helm | v4.3.1 | 2026-10-15 | Not verified from this environment: https://github.com/helm/helm/releases and https://get.helm.sh are blocked. Read instead: the Go module proxy, https://proxy.golang.org/helm.sh/helm/v4/@latest (v3 line: v3.22.1) | 2026-10-17 |
| Docker Compose | v5.6.0 | 2026-10-02 | Not verified from this environment: https://github.com/docker/compose/releases is blocked. Read instead: https://proxy.golang.org/github.com/docker/compose/v5/@latest (no v6 module) | 2026-10-17 |
| Podman | v6.1.4 | 2026-10-12 | Not verified from this environment: https://github.com/containers/podman/releases is blocked. Read instead: https://proxy.golang.org/go.podman.io/podman/v6/@latest (no v7 module at go.podman.io) | 2026-10-17 |

## Python decision

The [architecture specification](../superpowers/specs/2026-10-17-opennote-architecture-design.md) (§11) requires that the container base offer the latest stable Python; otherwise the newest UBI-available Python is used and the gap is recorded here.

**Verified.** A CI probe, run https://github.com/theonewizard/OpenNote/actions/runs/39071433587 on 2026-10-17, ran `docker manifest inspect registry.access.redhat.com/<image>:latest`:

- `ubi9/python-314` and `ubi9/python-312` exist.
- `ubi9/python-313`, `ubi10/python-312`, `ubi10/python-313` and `ubi10/python-314` do not exist.

The same run pulled `ubi9/ubi-minimal:9.8` (RHEL 9.8) and `ubi10/ubi-minimal:10.2` (RHEL 10.2) with the digests recorded above; neither image has `python3` installed.

**Inferred, not verified.** That the `python3.14` RPM installs with `microdnf` in `ubi9/ubi-minimal:9.8` is inferred from the existence of the `ubi9/python-314` image. The probe's `microdnf repoquery --available "python3*"` printed nothing in either minimal image (probably the wrong command form for microdnf), so it settles nothing.

**Evidence only (CentOS Stream, the upstream of RHEL).**

- `python3.12`: branches c8s, c9s and c10s at 3.12.15 (https://gitlab.com/redhat/centos-stream/rpms/python3.12). It is the main `python3` of c10s: its spec builds the main package when 3.12 is the distribution default, and c10s sets `%__default_python3_version 3.12` (https://gitlab.com/redhat/centos-stream/rpms/python-rpm-macros/-/raw/c10s/macros.python-srpm).
- `python3.14`: the "Python 3.14 stack in RHEL" (imported 2025-11-25), an AppStream component built as the separate `python3.14` package (`%bcond main_python 0`), branches c9s and c10s at 3.14.8 since 2026-10-12. https://gitlab.com/redhat/centos-stream/rpms/python3.14
- `python3.13`: no python3.13 project is visible to an anonymous GitLab API lookup (https://gitlab.com/api/v4/projects/redhat%2Fcentos-stream%2Frpms%2Fpython3.13 answers "404 Project Not Found", which GitLab also returns for private projects).
- `python3.15`: live only on c11s; its c10s branch is retired. https://gitlab.com/redhat/centos-stream/rpms/python3.15

**Unknowns and the checks that settle them.**

- Is `python3.14` installable in `ubi9/ubi-minimal:9.8`? Run `microdnf install -y python3.14` in that image in CI; the Task 6 image build does exactly this.
- Tags and digest of `ubi9/python-314`: https://catalog.redhat.com/software/containers/ubi9/python-314 and https://registry.access.redhat.com/v2/ubi9/python-314/tags/list (both blocked from this environment).
- Python 3.15 images, not probed: `ubi9/python-315` (https://registry.access.redhat.com/v2/ubi9/python-315/tags/list) and `ubi10/python-315` (https://registry.access.redhat.com/v2/ubi10/python-315/tags/list).
- Minimal Python images, not probed: sclorg upstream builds, among others, `ubi9/python-314-minimal`, `ubi10/python-312-minimal` and `ubi10/python-314-minimal` (https://raw.githubusercontent.com/sclorg/s2i-python-container/master/3.14-minimal/Dockerfile.rhel9, `3.14-minimal/Dockerfile.rhel10`, `3.12-minimal/Dockerfile.rhel10`). Check https://registry.access.redhat.com/v2/ubi9/python-314-minimal/tags/list, https://registry.access.redhat.com/v2/ubi10/python-312-minimal/tags/list and https://registry.access.redhat.com/v2/ubi10/python-314-minimal/tags/list.

**Decision.**

- Python 3.14 on UBI 9 is the newest of the probed UBI Python images (3.12 to 3.14). The probe found no `ubi10/python-312`, `-313` or `-314` image; the `-minimal` variants that sclorg upstream builds (among them `ubi9/python-314-minimal`, `ubi10/python-312-minimal`, `ubi10/python-314-minimal`) and any `python-315` image were not probed. UBI 10 is not used for Python images (see the runtime image and floor bullets below).
- The API and worker runtime image is `registry.access.redhat.com/ubi9/ubi-minimal:9.8` plus `microdnf install python3.14`, verified by the CI image build in Task 6. If that package is absent, the runtime base becomes `registry.access.redhat.com/ubi9/python-314`. `ubi9/python-314-minimal` is a candidate fallback to probe in Task 6 (not probed).
- The backend declares `requires-python = ">=3.13"` (the design floor). CI tests Python 3.13 and 3.14. Local development uses Python 3.13 or 3.14.
- Gap: the runtime Python (3.14) is one minor release behind the latest stable release (3.15.0). CentOS Stream has no live python3.15 branch for c9s or c10s (evidence only; `ubi9/python-315` and `ubi10/python-315` were not probed).
