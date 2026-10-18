#!/usr/bin/env bash
# Regenerate the API clients from docs/api/openapi.json (scripts/gen-openapi.sh writes it):
#   web/src/api/schema.d.ts   TypeScript types, from web/'s pinned openapi-typescript
#   apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.yaml
#                             the document as YAML; swift-openapi-generator's build plugin
#                             generates the Swift client from it when the package builds
# Needs .venv and web/node_modules (make bootstrap). Deterministic and offline: the output
# depends only on the input, and npx --no-install never downloads. Runs from any directory.
set -euo pipefail

cd "$(dirname "$0")/.."
root="$PWD"

types="$(mktemp)"
trap 'rm -f "$types"' EXIT
(cd web && npx --no-install openapi-typescript "$root/docs/api/openapi.json" \
  --alphabetize --output "$types")
{
  echo "// Generated from docs/api/openapi.json by scripts/gen-clients.sh (make openapi)."
  echo "// Do not edit: change the backend, then regenerate. CI fails when this file is stale."
  cat "$types"
} >web/src/api/schema.d.ts

# -I: isolated mode, so nothing in the working directory shadows the yaml module.
.venv/bin/python -I - <<'PY'
import json

import yaml

with open("docs/api/openapi.json", encoding="utf-8") as file:
    document = json.load(file)
text = yaml.safe_dump(document, sort_keys=True)
with open(
    "apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.yaml", "w", encoding="utf-8"
) as file:
    file.write("# Generated from docs/api/openapi.json by scripts/gen-clients.sh")
    file.write(" (make openapi). Do not edit.\n")
    file.write(text)
PY
