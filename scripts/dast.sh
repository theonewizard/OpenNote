#!/usr/bin/env bash
# DAST (P8-02): an OWASP ZAP API scan of the running Compose stack, through the web proxy,
# driven by docs/api/openapi.json and signed in as a local administrator.
#
#   scripts/dast.sh [base_url] [out_dir]      # defaults: http://localhost:8080 dast
#
# Needs the full stack up (docker compose -f infrastructure/compose/compose.yaml) with a
# migrated database, docker, curl and jq. Creates the user "dast" with a random password,
# signs in (session cookie plus CSRF header, the web client's credentials) and creates a
# vault, then runs zap-api-scan.py (passive and active rules) with those credentials on
# every request. POST /api/v1/auth/logout is left out of the scanned document: ZAP would
# end its own session there. Writes report.html, report.json and report.md to out_dir;
# exits 1 when ZAP reports any High risk alert, 0 otherwise (Medium and Low are listed in
# the report and printed).
set -euo pipefail

base=${1:-http://localhost:8080}
out=${2:-dast}
zap_image=zaproxy/zap-stable:2.17.0@sha256:9624669db72f54d86c4b46a7064518bd9bf79d8c61a4c31befa9923489f328af
compose=(docker compose -f infrastructure/compose/compose.yaml)

mkdir -p "$out"
out=$(cd "$out" && pwd) # absolute, for the docker bind mount
chmod 777 "$out" # ZAP runs as its own user (uid 1000) and writes the reports here

password=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')
printf '%s\n' "$password" | "${compose[@]}" exec -T api python -m app.auth.admin create-user --admin dast
login=$(jq -n --arg p "$password" '{username: "dast", password: $p}' |
  curl --silent --show-error --fail --max-time 10 -c "$out/cookies" \
    -H 'Content-Type: application/json' --data @- "$base/api/v1/auth/login")
csrf=$(jq -r .csrf_token <<<"$login")
cookie=$(awk '$6 ~ /^opennote_(session|csrf)$/ {printf "%s%s=%s", sep, $6, $7; sep=";"}' "$out/cookies")
rm -f "$out/cookies"
curl --silent --show-error --fail --max-time 10 -o /dev/null -H "Cookie: $cookie" \
  -H "X-CSRF-Token: $csrf" -H 'Content-Type: application/json' \
  --data '{"name": "dast"}' "$base/api/v1/vaults"

jq 'del(.paths["/api/v1/auth/logout"])' docs/api/openapi.json >"$out/openapi.json"

# The replacer adds the session to every request ZAP sends. No spaces in the values: ZAP
# splits -z on whitespace (hence ";" without a space between the cookies).
replace() { # index header value
  printf -- '-config replacer.full_list(%s).%s ' \
    "$1" "description=$2" "$1" enabled=true "$1" matchtype=REQ_HEADER \
    "$1" "matchstr=$2" "$1" regex=false "$1" "replacement=$3"
}
rc=0
docker run --rm --network host -v "$out:/zap/wrk:rw" "$zap_image" \
  zap-api-scan.py -t /zap/wrk/openapi.json -f openapi -O "$base" \
  -J report.json -r report.html -w report.md -I \
  -z "$(replace 0 Cookie "$cookie")$(replace 1 X-CSRF-Token "$csrf")" || rc=$?
# -I: warnings do not fail; anything else non-zero (2 is WARN, 3 an error) is checked below.
if ((rc != 0 && rc != 2)) || [[ ! -s $out/report.json ]]; then
  echo "FAIL  ZAP did not complete (exit $rc)" >&2
  exit 1
fi

jq -r '.site[].alerts[] | "\(.riskdesc)\t\(.alert)\t\(.count) instance(s)"' "$out/report.json" | sort
# Status codes of the 4xx answers ZAP saw: a scan that lost its session shows 401s here.
echo "4xx responses by status:"
jq -r '.site[].alerts[] | select(.pluginid == "100000") | .instances[] | "\(.evidence) \(.method)"' \
  "$out/report.json" | sort | uniq -c | sort -rn
high=$(jq '[.site[].alerts[] | select(.riskcode == "3")] | length' "$out/report.json")
if ((high > 0)); then
  echo "FAIL  ZAP reported $high High risk alert type(s); see $out/report.html" >&2
  exit 1
fi
echo "dast passed: no High risk alerts ($base)"
