#!/usr/bin/env bash
# Smoke-test a running OpenNote stack: the API probes and metadata answer 200 and, unless
# --api-only is given, GET / returns the web shell.
#
#   scripts/smoke-test.sh http://localhost:8080             # full stack, through the web proxy
#   scripts/smoke-test.sh --api-only http://localhost:8000  # the API alone
#
# While the stack starts, a check that gets no HTTP response or a 5xx is retried with
# backoff; all checks share one deadline of about 60 s. Any other answer is final, so a
# wrong route or body fails at once. Exits 0 when every check passes, otherwise 1 with a
# line naming the failing check (2 for bad usage).
set -euo pipefail

usage() {
  echo "usage: $0 [--api-only] <base_url>   (base_url starts with http:// or https://)" >&2
  exit 2
}

api_only=false
if [[ ${1:-} == --api-only ]]; then
  api_only=true
  shift
fi
[[ $# -eq 1 && $1 =~ ^https?://[^/]+ ]] || usage
base_url=${1%/}
deadline=$((SECONDS + 60))

# check <name> <path> <text the 200 body must contain>
check() {
  local name=$1 path=$2 expected=$3 delay=1 response status code error problem rc
  while :; do
    # The body, then a last line with the status code and curl's error text (empty when
    # the response arrived complete).
    rc=0
    response=$(curl --silent --max-time 5 --write-out '\n%{http_code} %{errormsg}' \
      "$base_url$path") || rc=$?
    status=${response##*$'\n'}
    code=${status%% *}
    error=${status#* }
    if ((rc != 0)); then
      problem="gave no complete HTTP response ($error), want 200 with $expected"
    elif [[ $code == 200 ]]; then
      if [[ ${response%$'\n'*} == *"$expected"* ]]; then
        echo "ok    $name"
        return
      fi
      problem="gave 200 without $expected in the body"
    else
      problem="gave $code, want 200 with $expected"
    fi
    # Only a connection error, a timeout or a 5xx can change while the stack starts.
    if { ((rc == 0)) && [[ $code != 5?? ]]; } || ((SECONDS + delay > deadline)); then
      echo "FAIL  $name: GET $base_url$path $problem" >&2
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
