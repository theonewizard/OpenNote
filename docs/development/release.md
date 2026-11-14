# Releasing OpenNote

A release is a Git tag `v<major>.<minor>.<patch>` on `main`. Pushing it runs `.github/workflows/release.yml`, which publishes the server side: the four container images and the Helm chart on GitHub's container registry, signed, with an SBOM per image, and a GitHub release. The Apple apps are not part of it yet (see [Not covered](#not-covered)).

## What a release publishes

| Artifact | Where | Signed | Attestation |
|---|---|---|---|
| `opennote-api`, `opennote-web`, `opennote-postgres`, `opennote-valkey` | `ghcr.io/theonewizard/opennote-<name>:<version>` | cosign, keyless | CycloneDX SBOM (from Trivy), as a cosign attestation |
| Helm chart `opennote` | `oci://ghcr.io/theonewizard/charts/opennote`, version `<version>` | cosign, keyless | — |
| GitHub release `v<version>` | the repository's Releases page | — | the four SBOM files and `digests.txt` (every artifact by digest) attached; generated notes; versions `0.x` are marked as pre-releases |

Keyless signing means there is no signing key to keep: the workflow trades its GitHub OIDC token for a short-lived Sigstore certificate that names the workflow and the tag, and the signature is recorded in Sigstore's public transparency log (Rekor). Nothing in the repository's secrets is involved; the job's `GITHUB_TOKEN` pushes to ghcr.io.

## How to release

1. Make sure every place that carries the version says the new one. `scripts/check-version.sh` lists them and fails on any difference: `backend/app/__init__.py`, `version` and `appVersion` in the chart's `Chart.yaml`, `MARKETING_VERSION` in `apple/project.yml`, `OpenNoteCore.version` (three Swift tests assert it), the image tags in `infrastructure/kubernetes/base/*.yaml`, and the two generated OpenAPI documents (regenerate them with `scripts/gen-openapi.sh` and `scripts/gen-clients.sh` after changing the backend version). Merge that change to `main` through a pull request.
2. Tag the merge commit and push the tag:

   ```bash
   git tag -a v0.2.0 -m "OpenNote 0.2.0" <commit on main>
   git push origin v0.2.0
   ```

3. Watch the `release` run. Its `version check` job refuses a tag that differs from the files; `publish` builds the four images from the tag, refuses any HIGH or CRITICAL finding that has a fix (Trivy, the same gate as the `containers` workflow) before pushing anything, pushes, signs and attests each image and verifies each signature, packages and pushes the chart and signs it, then creates the GitHub release.

The `publish` job runs in the GitHub environment `release`. GitHub creates it on the first run without protection; adding yourself as a required reviewer under Settings, Environments, `release` makes every release wait for your approval in the run.

A run that fails after pushing leaves what it pushed: delete the tag's images and chart version under the repository's Packages, delete the tag, fix, and tag again. Never move a tag that was published.

## Verifying a release

With cosign 2.6 or newer:

```bash
cosign verify \
  --certificate-identity https://github.com/theonewizard/OpenNote/.github/workflows/release.yml@refs/tags/v0.2.0 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/theonewizard/opennote-api@sha256:<digest from digests.txt>

cosign verify-attestation --type cyclonedx \
  --certificate-identity https://github.com/theonewizard/OpenNote/.github/workflows/release.yml@refs/tags/v0.2.0 \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/theonewizard/opennote-api@sha256:<digest>
```

The same `cosign verify` works for `ghcr.io/theonewizard/charts/opennote@sha256:<digest>`. To make a cluster run only what was signed, enforce it at admission: Sigstore's policy-controller on Kubernetes, or a signature-verification policy for the `ghcr.io/theonewizard` images on OpenShift, with the identity and issuer above. The chart takes one `image.tag` for api and web, so it cannot pin their two digests itself.

## Dry run

Every pull request and branch push that changes the release path (`release.yml`, `scripts/release.sh`, `scripts/check-version.sh`), and a manual run on any branch, runs the `dry run` job instead of `publish`: the same `scripts/release.sh` against a registry started inside the job (`localhost:5000`) with a throwaway cosign key and no transparency log, then a user's `cosign verify` of every digest and a `helm pull` of the chart. Nothing leaves the runner. It does not exercise keyless signing, the GitHub login or `gh release create`; the first real tag does.

## First release: owner steps

- Package visibility: packages that a workflow pushes to a personal account's ghcr.io start private. After the first release, make `opennote-api`, `opennote-web`, `opennote-postgres`, `opennote-valkey` and `charts/opennote` public under the account's Packages (Package settings, Change visibility), or keep them private and give clusters a pull secret (`imagePullSecrets`).
- Optionally protect the `release` environment (above) and the tag pattern `v*` (Settings, Rules, a tag ruleset restricting who may create matching tags).

## Not covered

- **Apple apps.** Notarization of the macOS app and TestFlight builds need Flemming's paid Apple Developer account, signing certificates and an App Store Connect API key in the repository's secrets. Nothing here touches them; they are added to this workflow only with his explicit approval.
- **Web app on its own.** The web app ships inside the `opennote-web` image; there is no separate static bundle.
