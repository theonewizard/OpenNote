# Development Workflow

Status: Proposed (2026-10-17). `claude.md` is authoritative; this page applies it to OpenNote and fills the gaps in design §15.6.

## Branches and worktrees

- Feature work happens on a branch in a worktree under `.worktrees/<subsystem>/` (e.g. `.worktrees/storage/`), never directly on `main`.
- Branch names: `feature/<topic>`, `fix/<topic>`, `security/<topic>`, `docs/<topic>`.
- `.worktrees/` is git-ignored.
- Completed work is squash-merged into `main` through a pull request after CI is green and the diff is reviewed. `main` is never force-pushed.

## Per feature

For each significant feature (design §15.6):

1. Requirements analysis and design spec: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
2. Implementation plan with test plan: `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`.
3. Implementation test-first, in small commits.
4. Automated tests, then runtime verification in the dev Compose stack (`claude.md` §8).
5. Documentation updated with the change (`claude.md` §26).
6. Review: full-diff review, then the `ponytail-audit` over-engineering review (`claude.md` §28).
7. Update `docs/IMPLEMENTATION_STATUS.md` and the item's status in `docs/ROADMAP.md`.
8. Squash merge.

Trivial fixes skip steps 1–2 (`claude.md` §7).

## Prompts

Every prompt that drives work is recorded in `.conversations/YYYY-MM-DD-<topic>.md` (verbatim prompt, who sent it, what it produced), per the last line of `claude.md`. Long source documents are stored once under `docs/design/` and referenced.

## Environments

| Environment | What | Approval |
|---|---|---|
| Local / CI | Developer machines, Claude Code containers, GitHub Actions | None for routine work; the `claude.md` §2 approval gates (e.g. disabling tests or security checks) still apply |
| Development / prepped | Dev Compose or a dev namespace | None needed (`claude.md` §2) |
| Production | Anything holding real user vaults | Explicit approval for every change |
