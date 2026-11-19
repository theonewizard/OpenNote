# 2026-11-19 — CI on pull requests and main only

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Investigate failing GitHub build checks" thread; the survey itself is recorded in `2026-11-19-ci-failure-survey.md` (PR #79).

## Prompts

- Flemming, 2026-11-19 07:52 UTC: "please investigate the build process as there are a lot of failed validation in the github builds."
- Flemming, 2026-11-19 08:01 UTC, decision card "Stop running CI twice on every PR push?": chose "PR and main only".

## Rulings

- Since 2026-11-12 the repository saw 195 push runs and 194 pull_request runs: each push to a branch with a pull request ran all workflows twice, and 18 `apple` runs sat queued for macOS runners, `main`'s included. The five workflows now run `push` on `main` only; `release` keeps `push` for its tags and runs the dry run on pull requests and manual runs. A branch without a pull request gets no CI; a draft pull request is enough. setup.md section 9 and release.md "Dry run" say so (replaces the earlier "worth the extra minutes" choice, R101).
