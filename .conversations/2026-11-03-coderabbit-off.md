# 2026-11-03 — CodeRabbit reviews off for now

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the numbering of [2026-11-01-phase-1-storage-sync.md](2026-11-01-phase-1-storage-sync.md) (R150).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-03 04:39 | Flemming (project chat) | "remove coderabbit reviews for now" |

## Rulings

- R151: reviews are switched off in `.coderabbit.yaml` (`reviews.auto_review.enabled: false`, `reviews.review_status: false`) rather than by deleting the file or the GitHub App installation. "For now" asks for something reversible: the file keeps the earlier `drafts: true` and says how to turn reviews back on, and the threads stop posting `@coderabbitai review` comments (the only way reviews have run since 2026-11-01, when CodeRabbit stopped reviewing this repository unprompted for its size). `review_status: false` also stops the "Review skipped" status comment CodeRabbit has posted on every pull request. The installation itself, and with it the `CodeRabbit` row among the checks, can only be removed in the repository's GitHub settings (Settings, Integrations, GitHub Apps), which is Flemming's step if he wants it gone entirely. Cost if wrong: two lines to flip back.

## Output

Branch `chore/coderabbit-off` in `.worktrees/coderabbit/`: one pull request to `main` with the two settings and this record.
