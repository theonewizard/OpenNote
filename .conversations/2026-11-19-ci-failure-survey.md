# 2026-11-19 — Survey of failing GitHub Actions checks

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Investigate failing GitHub build checks" thread.

## Prompts

- Flemming, 2026-11-19 07:52 UTC: "please investigate the build process as there are a lot of failed validation in the github builds."

## Findings

Runs since 2026-11-12 on `main` and every open pull request, grouped by root cause:

- `npm ci` ERESOLVE (TypeScript 7.0.2 from #72, typescript-eslint 8.72.2 peers `<6.1.0`): web job, containers image build, backend `openapi drift` (`make bootstrap`). Known; revert PR #77, upgrade check PR #78.
- `Revision 0009 is present more than once` / `Multiple head revisions`: backend pytest setup errors and the containers smoke step (api never starts). Known; PR #75.
- Weekly scheduled gitleaks run of 2026-11-16 (full history): two generic-api-key matches on the fixed Idempotency-Key UUID in `test_folders.py` and `test_vaults.py`. Push and pull request scans only see new commits, so it fails only on the Monday schedule. New; fixed here.
- Trivy image gate failures of 2026-11-15 (UBI 9 krb5) are gone since the UBI 10 move (#51).
- Structural: every push to a branch with an open pull request runs all five workflows twice (push and pull_request), and the `main` ruleset requires no status checks, which is how #72 merged red.

## Rulings

- The two gitleaks fingerprints go into `.gitleaksignore` with the reason; a local gitleaks 8.30.1 full-history scan reports "no leaks found" afterwards.
