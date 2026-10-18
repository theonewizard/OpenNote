# OpenNote

Self-hosted, local-first note-taking with Evernote-style productivity on top of Obsidian-compatible Markdown vaults. Clients for macOS, iOS, iPadOS and the web; backend in Red Hat UBI containers.

**Status:** Phase 0 (foundation) is implemented and pre-release: the skeletons and CI exist, product features do not yet, and nothing is deployed.

| Start here | |
|---|---|
| Design document (source) | [docs/design/2026-10-17-opennote-design-document.md](docs/design/2026-10-17-opennote-design-document.md) |
| Architecture specification | [docs/superpowers/specs/2026-10-17-opennote-architecture-design.md](docs/superpowers/specs/2026-10-17-opennote-architecture-design.md) |
| Roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |
| Implementation status | [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) |
| Architecture decisions | [docs/architecture/adr/](docs/architecture/adr/README.md) |
| Rules for AI-assisted development | [CLAUDE.md](CLAUDE.md) |
| Development setup | [docs/development/setup.md](docs/development/setup.md) |
| Kubernetes and OpenShift | [docs/deployment/kubernetes.md](docs/deployment/kubernetes.md) |
| Tool versions | [docs/development/versions.md](docs/development/versions.md) |

## Repository layout

Layout (the Phase 0 skeletons; later phases fill them in). The full planned tree is in the [architecture specification](docs/superpowers/specs/2026-10-17-opennote-architecture-design.md) §6.

| Directory | Contents |
|---|---|
| `backend/` | FastAPI API and Dramatiq worker (Python, one image, two process types) |
| `web/` | React + TypeScript web app (Vite) |
| `apple/` | Swift packages and XcodeGen spec for the macOS and iOS/iPadOS apps |
| `infrastructure/` | UBI Containerfiles, Docker Compose, Kubernetes, Helm and OpenShift |
| `scripts/` | OpenAPI export and client generation, smoke test |
| `.github/workflows/` | CI: backend, web, apple, containers, security |
| `docs/` | Design, architecture, API contract, development and security documentation |

## Quick start

Prerequisites and details: [docs/development/setup.md](docs/development/setup.md).

```bash
make bootstrap                 # .venv + backend requirements, npm ci in web/
make up-deps                   # PostgreSQL and Valkey for development
make lint typecheck test       # backend and web checks
```

| Target | Does |
|---|---|
| `make help` | List all targets |
| `make bootstrap` | Create `.venv`, install backend dev requirements, run `npm ci` in `web/` |
| `make lint` / `make typecheck` / `make test` | ruff, mypy, pytest for the backend; lint, typecheck, test scripts for the web app |
| `make build` | Production build of the web app |
| `make up-deps` | Start PostgreSQL and Valkey only |
| `make up` | Start the full stack with Docker Compose (`COMPOSE="podman compose"` for Podman, which is supported by design but untested; only Docker has been exercised) |
| `make down` | Stop the full stack and the `up-deps` services |
| `make openapi` | Regenerate the OpenAPI document and the TypeScript and Swift clients |
| `make constraints` | Regenerate `backend/constraints.txt` from a clean install of `requirements.txt` |
| `make apple-project` | Generate the Xcode project with XcodeGen (macOS) |

## Licence

[GNU Affero General Public License v3.0](LICENSE).
