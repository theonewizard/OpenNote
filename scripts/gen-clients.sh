#!/usr/bin/env bash
# Regenerate the API clients from docs/api/openapi.json (scripts/gen-openapi.sh writes it):
#   web/src/api/schema.d.ts   TypeScript types, from web/'s pinned openapi-typescript
#   apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.json
#                             a byte-identical copy; swift-openapi-generator's build plugin
#                             generates the Swift client from it when the package builds
# Needs web/node_modules (npm ci in web/, part of make bootstrap). Deterministic and
# offline: the output depends only on the input. Runs from any directory.
set -euo pipefail

cd "$(dirname "$0")/.."

generator=web/node_modules/.bin/openapi-typescript
if [[ ! -x "$generator" ]]; then
  echo "gen-clients.sh: $generator is missing; run npm ci in web/" >&2
  exit 1
fi

types="$(mktemp)"
trap 'rm -f "$types"' EXIT
"$generator" docs/api/openapi.json --alphabetize --output "$types"
{
  echo "// Generated from docs/api/openapi.json by scripts/gen-clients.sh (make openapi)."
  echo "// Do not edit: change the backend, then regenerate. CI fails when this file is stale."
  cat "$types"
} >web/src/api/schema.d.ts

cp docs/api/openapi.json apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.json
