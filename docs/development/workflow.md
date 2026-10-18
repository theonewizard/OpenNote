# Development Workflow

Status: Proposed (2026-10-17). `CLAUDE.md` is authoritative; this page applies it to OpenNote and fills the gaps in design §15.6.

## Branches and worktrees

- Feature work happens on a branch in a worktree under `.worktrees/<subsystem>/` (e.g. `.worktrees/storage/`), never directly on `main`.
- Branch names: `feature/<topic>`, `fix/<topic>`, `security/<topic>`, `docs/<topic>`.
- `.worktrees/` is git-ignored.
- Completed work is squash-merged into `main` through a pull request after CI is green and the diff is reviewed. `main` is never force-pushed.

### Repository settings the owner enables

CI cannot change repository settings; the repository owner sets these on GitHub:

- **Private vulnerability reporting:** Settings → Security → "Private vulnerability reporting", enable. The advisory form that `SECURITY.md` links to works only once this is on.
- **Branch protection for `main`** (Settings → Branches, or a ruleset):
  - require a pull request before merging;
  - require these status checks, by their exact job names (`.github/workflows/`; docs/development/setup.md, "Continuous integration"): `test (3.13)`, `test (3.14)` and `openapi drift` (backend); `lint, typecheck, test, build, e2e` (web); `macOS` and `Linux` (apple); `build, run, scan` and `manifests` (containers); `gitleaks`, `pip-audit, bandit`, `npm audit` and `trivy filesystem` (security). A job added to a workflow later is added to this list and to the settings;
  - block force pushes and deletion of `main`.
- **Merge methods:** Settings → General → "Pull Requests": allow squash merging only, with merge commits and rebase merging turned off.

## Per feature

For each significant feature (design §15.6):

1. Requirements analysis and design spec: `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`.
2. Implementation plan with test plan: `docs/superpowers/plans/YYYY-MM-DD-<topic>-plan.md`.
3. Implementation test-first, in small commits.
4. Automated tests, then runtime verification in the dev Compose stack (`CLAUDE.md` §8).
5. Documentation updated with the change (`CLAUDE.md` §26).
6. Review: full-diff review, then the `ponytail-audit` over-engineering review (`CLAUDE.md` §28).
7. Update `docs/IMPLEMENTATION_STATUS.md` and the item's status in `docs/ROADMAP.md`.
8. Squash merge.

Trivial fixes skip steps 1–2 (`CLAUDE.md` §7).

## Prompts

Every prompt that drives work is recorded in `.conversations/YYYY-MM-DD-<topic>.md` (verbatim prompt, who sent it, what it produced), per the last line of `CLAUDE.md`. Long source documents are stored once under `docs/design/` and referenced.

## Environments

| Environment | What | Approval |
|---|---|---|
| Local / CI | Developer machines, Claude Code containers, GitHub Actions | None for routine work; the `CLAUDE.md` §2 approval gates (e.g. disabling tests or security checks) still apply |
| Development / prepped | Dev Compose or a dev namespace | None needed (`CLAUDE.md` §2) |
| Production | Anything holding real user vaults | Explicit approval for every change |
