# 2026-11-07 — P8-08 release automation and image signing

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Workstream 3 of the parallel plan; rulings R-P8-010 onwards (the workstream's numbering is explained in [2026-11-07-openshift-deployment.md](2026-11-07-openshift-deployment.md)).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |

The coordinator's brief for this workstream: P8-08 among others; notarization and TestFlight need Flemming's paid Apple account and are not to be touched without his explicit OK; anything that incurs charges or touches external production accounts needs approval.

## Rulings

- R-P8-010: publishing happens only when Flemming pushes a tag `vX.Y.Z`; the workflow is written and dry-run tested here, and no tag is pushed from this side. Publishing to ghcr.io and Sigstore's public log is free for a public repository and uses no account beyond the repository's own `GITHUB_TOKEN`. The `publish` job runs in a GitHub environment `release`, so Flemming can require his own approval per release in the repository settings.
- R-P8-011: images and the chart are signed keyless (GitHub OIDC, Fulcio, Rekor) with cosign 3.1.4, so there is no signing key to store, rotate or leak, and a signature names the workflow file and the tag. SBOMs are CycloneDX from Trivy (already pinned in the workflows) attached as cosign attestations and as release files. GitHub's own artifact attestations were left out: they would add an action and a second verification path for the same claim.
- R-P8-012: the dry run uses a registry container inside the job and a throwaway cosign key with no transparency-log upload, because a keyless dry run would write a public Rekor entry for every pull request. It covers build, scan, push, sign, attest and verify of all four images and the chart; keyless signing, the GitHub login and `gh release create` are exercised first by a real tag.
- R-P8-013: the Trivy gate runs before anything is pushed, with the same rule as the `containers` workflow (HIGH or CRITICAL with a fix fails), so a release cannot publish an image that `main`'s CI would reject.
- R-P8-014: all four images are published, `opennote-postgres` and `opennote-valkey` included, because the Compose stack uses all four and the backup tools ship in the postgres image (P8-04). `0.x` releases are marked as pre-releases.
- R-P8-015: `scripts/check-version.sh` closes the Phase 0 open item "no check compares" the version strings: it runs in the backend workflow's `constraints` job on every pull request, and against the tag before a release.
- R-P8-016: cosign 3 warns that `--tlog-upload` and `--use-signing-config` (used only by the dry run's key mode) are deprecated in favour of a signing-config file; they still work in 3.1.4, and the dry run will fail visibly when they stop.

## Output

Branch `feature/release-signing` in `.worktrees/release/`: `.github/workflows/release.yml`, `scripts/release.sh`, `scripts/check-version.sh`, the version step in `backend.yml`, `docs/development/release.md`, the CI table in setup.md, the P8-08 row in ROADMAP.md, the version item in IMPLEMENTATION_STATUS.md, and this record.
