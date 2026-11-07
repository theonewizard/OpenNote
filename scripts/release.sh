#!/usr/bin/env bash
# Build, scan, push, sign and attest OpenNote's four images and its Helm chart
# (docs/development/release.md). Run by .github/workflows/release.yml: for a release tag
# against ghcr.io with keyless signing, and as a dry run against a local registry with a
# throwaway key.
#
#   scripts/release.sh <registry> <version> keyless            # ghcr.io/theonewizard 0.2.0 keyless
#   scripts/release.sh <registry> <version> key <key prefix>   # localhost:5000/opennote 0.2.0 key /tmp/cosign
#
# keyless signs with the GitHub Actions OIDC identity through Sigstore (Fulcio certificate,
# Rekor transparency log) and verifies against the identity of this repository's release
# workflow at refs/tags/v<version>; key signs with <key prefix>.key (empty password, nothing
# sent to Rekor) and verifies with <key prefix>.pub. A registry whose host is localhost is
# spoken to over plain HTTP.
#
# Needs docker, trivy, cosign and helm, and a login to <registry> for pushing. Writes into
# dist/: one CycloneDX SBOM per image (opennote-<name>-<version>.cdx.json), the chart package
# and digests.txt, one "<reference>@<digest>" line per image and for the chart. Stops at the
# first failure; a fixable HIGH or CRITICAL finding in any image stops it before anything is
# pushed.
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  echo "usage: $0 <registry> <version> keyless | $0 <registry> <version> key <key prefix>" >&2
  exit 2
}
(($# >= 3)) || usage
registry=${1%/} version=$2 mode=$3 key=${4:-}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage
case $mode in
  keyless) (($# == 3)) || usage ;;
  key) (($# == 4)) || usage ;;
  *) usage ;;
esac

scripts/check-version.sh "$version" >/dev/null
images=(api web postgres valkey)
revision=$(git rev-parse HEAD)
created=$(git show -s --format=%cI HEAD) # the commit's time, so a rebuild labels the same
# insecure: for every cosign command; sign_args: sign and attest; verify_args: verify.
insecure=() sign_args=() verify_args=() helm_args=()
if [[ $registry == localhost:* || $registry == localhost/* ]]; then
  insecure+=(--allow-insecure-registry)
  helm_args+=(--plain-http)
fi
if [[ $mode == keyless ]]; then
  verify_args+=(
    --certificate-identity "https://github.com/theonewizard/OpenNote/.github/workflows/release.yml@refs/tags/v$version"
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  )
else
  sign_args+=(--key "$key.key" --tlog-upload=false --use-signing-config=false)
  verify_args+=(--key "$key.pub" --insecure-ignore-tlog=true)
fi

rm -rf dist
mkdir dist

echo "== build"
for name in "${images[@]}"; do
  docker build -f "infrastructure/containers/$name/Containerfile" -t "$registry/opennote-$name:$version" \
    --label "org.opencontainers.image.version=$version" \
    --label "org.opencontainers.image.revision=$revision" \
    --label "org.opencontainers.image.created=$created" .
done

echo "== scan (HIGH and CRITICAL with a fix fail the release)"
for name in "${images[@]}"; do
  trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$registry/opennote-$name:$version"
done

# sign <reference@digest>: sign it and check the signature.
sign() {
  cosign sign --yes "${insecure[@]}" "${sign_args[@]}" "$1"
  cosign verify "${insecure[@]}" "${verify_args[@]}" "$1" >/dev/null
}

echo "== push, SBOM, sign, attest"
for name in "${images[@]}"; do
  ref=$registry/opennote-$name
  docker push "$ref:$version"
  digest=$(docker inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$ref:$version" |
    sed -n "s|^$ref@||p" | head -n 1)
  [[ $digest == sha256:* ]] || { echo "no digest for $ref:$version" >&2; exit 1; }
  echo "$ref@$digest" >>dist/digests.txt
  sbom=dist/opennote-$name-$version.cdx.json
  trivy image --format cyclonedx --output "$sbom" "$ref:$version"
  sign "$ref@$digest"
  cosign attest --yes "${insecure[@]}" "${sign_args[@]}" --type cyclonedx --predicate "$sbom" "$ref@$digest"
  cosign verify-attestation "${insecure[@]}" "${verify_args[@]}" --type cyclonedx "$ref@$digest" >/dev/null
done

echo "== chart"
helm package infrastructure/helm/opennote --destination dist
helm push "dist/opennote-$version.tgz" "oci://$registry/charts" "${helm_args[@]}" 2>&1 | tee dist/helm-push.log
digest=$(sed -n -E 's/^Digest: (sha256:[0-9a-f]{64})$/\1/p' dist/helm-push.log)
rm dist/helm-push.log
[[ -n $digest ]] || { echo "no digest for the chart" >&2; exit 1; }
echo "$registry/charts/opennote@$digest" >>dist/digests.txt
sign "$registry/charts/opennote@$digest"

echo "== done"
cat dist/digests.txt
