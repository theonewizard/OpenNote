#!/usr/bin/env bash
# Is the next TypeScript major usable yet? The web workflow runs this with every build
# (job "TypeScript upgrade check"); it never fails the build.
#
# While typescript-eslint or openapi-typescript (their newest releases) do not accept the
# newest TypeScript in their peer range, it prints a notice and stops. Once both do, it
# installs the three newest versions, runs lint, typecheck, unit tests, build and the client
# generator against them, and reports the outcome as a warning, so the upgrade is noticed the
# first time it can be made. package.json and package-lock.json are restored afterwards;
# node_modules is not, so run npm ci after a local run. Needs web/node_modules and the npm registry.
set -euo pipefail

cd "$(dirname "$0")/../web"

note() { echo "::$1 title=TypeScript upgrade check::$2"; }
satisfies() { node -e 'process.exit(require("semver").satisfies(process.argv[1], process.argv[2]) ? 0 : 1)' "$1" "$2"; }

current=$(node -p 'const p = require("./package.json"); p.devDependencies?.typescript ?? p.dependencies.typescript')
latest=$(npm view typescript@latest version)
if [[ ${latest%%.*} == "${current%%.*}" ]]; then
  note notice "TypeScript $current is on the newest major (latest $latest)"
  exit 0
fi

declare -A newest
blocked=()
for pkg in typescript-eslint openapi-typescript; do
  newest[$pkg]=$(npm view "$pkg@latest" version)
  range=$(npm view "$pkg@latest" peerDependencies.typescript)
  satisfies "$latest" "$range" || blocked+=("$pkg ${newest[$pkg]} peers typescript $range")
done
if ((${#blocked[@]})); then
  printf -v list '%s; ' "${blocked[@]}"
  note notice "TypeScript $latest not adoptable yet: ${list%; }"
  exit 0
fi

saved=$(mktemp -d)
types=$(mktemp)
cp package.json package-lock.json "$saved/"
trap 'cp "$saved"/package.json "$saved"/package-lock.json . && rm -rf "$saved" "$types"' EXIT

npm pkg set "devDependencies.typescript=$latest" \
  "devDependencies.typescript-eslint=${newest[typescript-eslint]}" \
  "devDependencies.openapi-typescript=${newest[openapi-typescript]}"
# The override only exists to stretch openapi-typescript's peer range over TypeScript 6.
npm pkg delete overrides
failed=()
npm install --no-audit --no-fund || failed+=("npm install")
if ((${#failed[@]} == 0)); then
  npm run lint || failed+=(lint)
  npm run typecheck || failed+=(typecheck)
  npm test || failed+=("unit tests")
  npm run build || failed+=(build)
  node_modules/.bin/openapi-typescript ../docs/api/openapi.json --alphabetize --output "$types" ||
    failed+=("client generation")
fi

with="typescript-eslint ${newest[typescript-eslint]} and openapi-typescript ${newest[openapi-typescript]}"
if ((${#failed[@]})); then
  printf -v list '%s, ' "${failed[@]}"
  note warning "Both peers accept TypeScript $latest, but with $with these fail: ${list%, }"
else
  note warning "TypeScript $latest is ready: lint, typecheck, tests, build and client generation pass with $with. Bump all three together and drop the overrides entry."
fi
