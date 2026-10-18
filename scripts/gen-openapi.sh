#!/usr/bin/env bash
# Export the backend's OpenAPI document to docs/api/openapi.json with sorted keys, a
# two-space indent and a trailing newline, so every run writes the same bytes and CI can
# diff it (docs/development/setup.md, "API contract"). Needs the repository's .venv
# (make bootstrap); contacts no service and no network. Runs from any directory.
set -euo pipefail

cd "$(dirname "$0")/../backend"

# create_app() does no I/O, so these throwaway placeholders only satisfy the settings
# validation; nothing connects to them. They override any OPENNOTE_* in the environment.
export OPENNOTE_DATABASE_URL="postgresql+psycopg://opennote:opennote@127.0.0.1:5432/opennote"
export OPENNOTE_VALKEY_URL="redis://127.0.0.1:6379/0"
export OPENNOTE_VAULT_ROOT="/tmp/opennote/vaults"
export OPENNOTE_HISTORY_ROOT="/tmp/opennote/history"
export OPENNOTE_LOG_LEVEL="WARNING"
export OPENNOTE_ENVIRONMENT="development"

../.venv/bin/python - <<'PY'
import json

from app.api.main import create_app

document = create_app().openapi()
with open("../docs/api/openapi.json", "w", encoding="utf-8") as file:
    json.dump(document, file, indent=2, sort_keys=True)
    file.write("\n")
PY
