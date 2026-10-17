# Single entry point for development tasks. Each target delegates to the
# subproject or tool that owns the work; see docs/development/setup.md.

PYTHON ?= python3
COMPOSE ?= docker compose
COMPOSE_DIR := infrastructure/compose

.DEFAULT_GOAL := help
.PHONY: help bootstrap lint typecheck test build up up-deps down openapi apple-project

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Create .venv, install backend dev requirements, run npm ci in web/
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r backend/requirements-dev.txt
	cd web && npm ci

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

build: ## Production build of the web app
	cd web && npm run build

up: ## Start the full stack (COMPOSE="podman compose" for Podman)
	$(COMPOSE) -f $(COMPOSE_DIR)/compose.yaml up -d --wait

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
