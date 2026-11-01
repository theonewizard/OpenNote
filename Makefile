# Single entry point for development tasks. Each target delegates to the
# subproject or tool that owns the work; see docs/development/setup.md.

PYTHON ?= python3
COMPOSE ?= docker compose
COMPOSE_DIR := infrastructure/compose
SEEDS ?= 500
SEED_START ?= 0

.DEFAULT_GOAL := help
.PHONY: help bootstrap constraints lint typecheck test sync-sim build up up-deps down openapi apple-project

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Create .venv, install backend dev requirements, run npm ci in web/
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install --dry-run --quiet -c backend/constraints.txt -r backend/requirements.txt \
		-r backend/requirements-dev.txt || { echo "backend/constraints.txt is stale: run make constraints"; exit 1; }
	.venv/bin/pip install -c backend/constraints.txt -r backend/requirements-dev.txt
	cd web && npm ci

constraints: ## Regenerate backend/constraints.txt from a clean install of requirements.txt
	rm -rf .venv-constraints
	$(PYTHON) -m venv .venv-constraints
	.venv-constraints/bin/pip install --quiet --disable-pip-version-check --only-binary=:all: \
		-r backend/requirements.txt
	{ printf '%s\n' \
		'# Every package a clean install of requirements.txt brings in, pinned exactly: the runtime' \
		'# dependencies and their transitive dependencies (ADR-0014). The api image, `make bootstrap`' \
		'# and the backend CI jobs install with `-c backend/constraints.txt`, so a transitive' \
		'# dependency cannot change between installs. pip-audit audits this file in CI.' \
		'#' \
		"# Generated $$(date -u +%F) by \`make constraints\` with $$(.venv-constraints/bin/python -V) (pip $$(.venv-constraints/bin/pip -V | cut -d' ' -f2)): \`pip freeze\`" \
		'# in a new virtual environment after `pip install --only-binary=:all: -r requirements.txt`.' \
		'# Run `make constraints` whenever requirements.txt changes, a Dependabot pull request' \
		'# included (docs/development/versions.md, "Backend (PyPI)").'; \
		.venv-constraints/bin/pip freeze; } > backend/constraints.txt
	rm -rf .venv-constraints

lint: ## Lint and format-check backend and web
	cd backend && ../.venv/bin/ruff check .
	cd backend && ../.venv/bin/ruff format --check .
	cd web && npm run lint

typecheck: ## Type-check backend (mypy) and web (tsc)
	cd backend && ../.venv/bin/mypy app
	cd web && npm run typecheck

test: ## Run backend and web tests
	cd backend && ../.venv/bin/pytest -q
	cd web && npm test

sync-sim: ## Run the seeded sync simulation alone (SEEDS=10000 for the milestone run, SEED_START=N)
	cd backend && SYNC_SIM_SEEDS=$(SEEDS) SYNC_SIM_SEED_START=$(SEED_START) ../.venv/bin/pytest -q -m sync_sim tests/integration/sync_sim

build: ## Production build of the web app
	cd web && npm run build

up: ## Start the full stack (COMPOSE="podman compose" for Podman, untested)
	$(COMPOSE) -f $(COMPOSE_DIR)/compose.yaml up -d --wait --build

up-deps: ## Start only PostgreSQL and Valkey for local development
	$(COMPOSE) -f $(COMPOSE_DIR)/compose.dev.yaml up -d --wait postgres valkey

down: ## Stop the full stack and the up-deps services
	$(COMPOSE) -f $(COMPOSE_DIR)/compose.yaml down
	$(COMPOSE) -f $(COMPOSE_DIR)/compose.dev.yaml down

openapi: ## Regenerate docs/api/openapi.json and the TypeScript and Swift clients
	scripts/gen-openapi.sh
	scripts/gen-clients.sh

apple-project: ## Generate the Xcode project from apple/project.yml (macOS)
	xcodegen generate --spec apple/project.yml
