#!/usr/bin/env bash
# Export the backend's OpenAPI document to docs/api/openapi.json with sorted keys, a
# two-space indent and a trailing newline, so every run writes the same bytes and CI can
# diff it (docs/development/setup.md, "API contract"). Needs the repository's .venv
# (make bootstrap); contacts no service and no network. Runs from any directory.
set -euo pipefail

cd "$(dirname "$0")/../backend"

# create_app() does no I/O, so these placeholders only satisfy the settings validation.
# They cannot reach anything: .invalid hosts never resolve (RFC 6761) and the paths do not
# exist. They override any OPENNOTE_* in the environment.
export OPENNOTE_DATABASE_URL="postgresql+psycopg://opennote:opennote@postgres.invalid:5432/opennote"
export OPENNOTE_VALKEY_URL="redis://valkey.invalid:6379/0"
export OPENNOTE_VAULT_ROOT="/nonexistent/opennote/vaults"
export OPENNOTE_HISTORY_ROOT="/nonexistent/opennote/history"
export OPENNOTE_LOG_LEVEL="WARNING"
export OPENNOTE_ENVIRONMENT="development"

../.venv/bin/python - <<'PY'
import json
import sys

from app.api.main import create_app
from app.api.openapi import duplicate_operation_ids

document = create_app().openapi()
# FastAPI only warns about these; a generated client cannot have two methods of one name.
if duplicates := duplicate_operation_ids(document):
    sys.exit("gen-openapi.sh: duplicate operationIds, rename the endpoint functions: "
             + ", ".join(duplicates))
with open("../docs/api/openapi.json", "w", encoding="utf-8") as file:
    json.dump(document, file, indent=2, sort_keys=True)
    file.write("\n")
PY
