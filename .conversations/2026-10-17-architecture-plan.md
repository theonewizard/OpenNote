# 2026-10-17 — Architecture plan

Project: OpenNote (Claude project thread "OpenNote plan"). Recorded per the last line of `claude.md` ("Document every prompt").

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 16:00 | Flemming | The full design document "Consulting OpenNotes — Powered by Obsidian" (stored verbatim in `docs/design/2026-10-17-opennote-design-document.md`) |
| 16:01 | Flemming | "Make a plan for the above" |
| 16:07 | Flemming | "refresh as I have added claude.md" |
| 20:34 | Flemming | "add coderabbit reviews in" with `reviews.auto_review.drafts: true` → added `.coderabbit.yaml` |

## How the prompts were read

- The design document's section 15 §20 lists initial steps 1–14. "Make a plan for the above" narrowed this session to steps 1–9 (analysis, risks, architecture, roadmap, repository structure, ADRs, contracts, sync protocol, testing strategy), delivered for review before any Phase 0 code.
- After `claude.md` landed on `main`, the branch was rebased onto it and the plan aligned with its rules (pip + `.venv`, `.worktrees/<subsystem>/`, deny-by-default routes, RFC 9457, ponytail audit, this file).

## Output

Pull request from `feature/architecture-plan`:

- `docs/superpowers/specs/2026-10-17-opennote-architecture-design.md`
- `docs/superpowers/plans/2026-10-17-phase-0-foundation-plan.md`
- `docs/architecture/` (storage contract, sync protocol, ADR-0001…0017)
- `docs/api/api-contract.md`, `docs/development/`, `docs/security/threat-model.md`
- `docs/ROADMAP.md`, `docs/IMPLEMENTATION_STATUS.md`
