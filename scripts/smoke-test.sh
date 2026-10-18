#!/usr/bin/env bash
# Smoke-test a running OpenNote stack: the API probes and metadata answer 200 and, unless
# --api-only is given, GET / returns the web shell.
#
#   scripts/smoke-test.sh http://localhost:8080             # full stack, through the web proxy
#   scripts/smoke-test.sh --api-only http://localhost:8000  # the API alone
#
# While the stack starts, each check is retried with backoff; all checks share one
# deadline of about 60 s. Exits 0 when every check passes, otherwise 1 with a line naming
# the failing check (2 for bad usage).
set -euo pipefail

usage() {
  echo "usage: $0 [--api-only] <base_url>" >&2
  exit 2
}

api_only=false
if [[ ${1:-} == --api-only ]]; then
  api_only=true
  shift
fi
[[ $# -eq 1 ]] || usage
base_url=${1%/}
deadline=$((SECONDS + 60))

# check <name> <path> <text the 200 body must contain>
check() {
  local name=$1 path=$2 expected=$3 delay=1 response code
  while :; do
    # The status code goes on a last line of its own, after the body.
    response=$(curl --silent --show-error --max-time 5 --write-out '\n%{http_code}' \
      "$base_url$path" 2>&1) || true
    code=${response##*$'\n'}
    if [[ $code == 200 && $response == *"$expected"* ]]; then
      echo "ok    $name"
      return
    fi
    if ((SECONDS + delay > deadline)); then
      [[ $code != 000 ]] || code="no HTTP response"
      echo "FAIL  $name: GET $base_url$path gave $code, want 200 with $expected" >&2
      exit 1
    fi
    sleep "$delay"
    delay=$((delay < 8 ? delay * 2 : 8))
  done
}

check healthz /healthz '"status":"ok"'
check readyz /readyz '"status":"ok"'
check meta /api/v1/meta '"api_versions"'
if ! $api_only; then
  check "web shell" / '<div id="root">'
fi
echo "smoke test passed: $base_url"
