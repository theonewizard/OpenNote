#!/usr/bin/env bash
# Check that every place that carries OpenNote's version carries the same one, and, given a
# version (a release tag without its leading v), that it is that one (docs/development/release.md).
#
#   scripts/check-version.sh          # all places agree; prints the version
#   scripts/check-version.sh 0.2.0    # all places say 0.2.0
#
# Exits 0 when they agree, 1 naming each place that differs, 2 for bad usage.
set -euo pipefail
cd "$(dirname "$0")/.."

(($# <= 1)) || { echo "usage: $0 [version]" >&2; exit 2; }
want=${1:-}
[[ -z $want || $want =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a version: $want" >&2; exit 2; }

# place <name> <value>: one place and the version found there.
names=() values=()
place() {
  names+=("$1")
  values+=("$2")
}
# first <ERE with one group> <file>: the group of the first matching line, empty if none.
first() {
  sed -n -E "s/$1/\\1/p" "$2" | head -n 1
}

place backend/app/__init__.py "$(first '^__version__ = "([^"]+)"$' backend/app/__init__.py)"
place "Chart.yaml version" "$(first '^version: "?([^"]+)"?$' infrastructure/helm/opennote/Chart.yaml)"
place "Chart.yaml appVersion" "$(first '^appVersion: "?([^"]+)"?$' infrastructure/helm/opennote/Chart.yaml)"
place apple/project.yml "$(first '^ *MARKETING_VERSION: "?([^"]+)"?$' apple/project.yml)"
place OpenNoteCore.version "$(first '^ *public static let version = "([^"]+)"' \
  apple/Packages/OpenNoteCore/Sources/OpenNoteCore/OpenNoteCore.swift)"
place docs/api/openapi.json "$(first '^    "version": "([^"]+)"' docs/api/openapi.json)"
place "OpenNoteAPI openapi.json" "$(first '^    "version": "([^"]+)"' \
  apple/Packages/OpenNoteAPI/Sources/OpenNoteAPI/openapi.json)"
for file in infrastructure/kubernetes/base/*.yaml; do
  while IFS= read -r tag; do
    place "$file image tag" "$tag"
  done < <(sed -n -E 's|^ *image: ghcr\.io/theonewizard/opennote-[a-z]+:(.+)$|\1|p' "$file")
done

expected=${want:-${values[0]}}
status=0
for i in "${!names[@]}"; do
  if [[ ${values[i]} != "$expected" ]]; then
    echo "${names[i]}: '${values[i]}', want '$expected'" >&2
    status=1
  fi
done
((status == 0)) && echo "$expected"
exit "$status"
