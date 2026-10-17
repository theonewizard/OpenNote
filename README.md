# OpenNote

Self-hosted, local-first note-taking with Evernote-style productivity on top of Obsidian-compatible Markdown vaults. Clients for macOS, iOS, iPadOS and the web; backend in Red Hat UBI containers.

**Status:** planning. No application code yet.

| Start here | |
|---|---|
| Design document (source) | [docs/design/2026-10-17-opennote-design-document.md](docs/design/2026-10-17-opennote-design-document.md) |
| Architecture specification | [docs/superpowers/specs/2026-10-17-opennote-architecture-design.md](docs/superpowers/specs/2026-10-17-opennote-architecture-design.md) |
| Roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |
| Implementation status | [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) |
| Architecture decisions | [docs/architecture/adr/](docs/architecture/adr/README.md) |
| Rules for AI-assisted development | [CLAUDE.md](CLAUDE.md) |
| Development setup | [docs/development/setup.md](docs/development/setup.md) |
| Tool versions | [docs/development/versions.md](docs/development/versions.md) |

## Repository layout

Planned layout ([architecture specification](docs/superpowers/specs/2026-10-17-opennote-architecture-design.md) §6); Phase 0 creates the skeletons.

| Directory | Contents |
|---|---|
| `backend/` | FastAPI API and Dramatiq worker (Python, one image, two process types) |
| `web/` | React + TypeScript web app (Vite) |
| `apple/` | Swift packages and XcodeGen spec for the macOS and iOS/iPadOS apps |
| `infrastructure/` | UBI Containerfiles, Docker Compose, Kubernetes, Helm and OpenShift |
| `scripts/` | OpenAPI export and client generation, smoke test |
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
| `make up` / `make down` | Start or stop the full stack with Docker Compose (`COMPOSE="podman compose"` for Podman) |
| `make openapi` | Regenerate the OpenAPI document and the TypeScript and Swift clients |
| `make apple-project` | Generate the Xcode project with XcodeGen (macOS) |

## Licence

[GNU Affero General Public License v3.0](LICENSE).
