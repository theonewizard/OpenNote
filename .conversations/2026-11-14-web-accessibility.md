# 2026-11-14 — Phase 8: web accessibility (P8-03)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Done in the "Finish Phase 8 production hardening" thread. P8-04, P8-06 and P8-08 belong to the "Harden deployment and releases" thread (rulings R-P8-001 to R-P8-032); this thread's rulings start at R-P8-100 so the two never collide.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 00:53 | Flemming | Start the development phase 5,6 8 using ubi 10 |
| 2026-11-14 00:53 | Coordinator | Phase 8 thread: the remaining Phase 8 items per `docs/ROADMAP.md`, on UBI 10. P8-04, P8-06 and P8-08 are done in the "Harden deployment and releases" thread, which is also moving all four images to `ubi10/ubi-minimal:10.3` (PR #51): build on top of it once it merges. RHEL 10 needs an x86-64-v3 CPU. Phases 5 and 6 have threads of their own. |

## Scope

Remaining Phase 8 items: P8-01 (performance), P8-02 (security testing), P8-03 (accessibility), P8-05 (disaster recovery), P8-07 (documentation), P8-09 (beta). Done here as one pull request each. Not done by this thread, because they need Flemming or Phase 5: the external security review (P8-02), VoiceOver testing on Apple hardware (P8-03), benchmark numbers on the reference hardware of testing-strategy §6 (P8-01), and the beta program (P8-09, after M5 and P8-01 to P8-08).

## Rulings

### P8-03 web accessibility (branch `feature/web-accessibility`)

- R-P8-120: automated part of P8-03 for the web app: `web/tests/e2e/accessibility.spec.ts` runs axe-core through `@axe-core/playwright` 4.14.0 (new dev dependency, latest release, no high `npm audit` advisory) with the WCAG 2.0, 2.1 and 2.2 A and AA rule tags on the shell: empty vault, list and open note at 1280 px in light and dark theme and at 375 px (one pane at a time). A keyboard-only test finds, opens, edits and saves a note with Tab, Enter, typing and Ctrl/Cmd+S, checks a visible focus indicator on each stop (WCAG 2.4.7) and that Tab leaves the editor (2.1.2, no keyboard trap). It runs in the existing Playwright job on every push.
- R-P8-121: finding: `--muted-foreground` (oklch 0.556) on `--muted` (oklch 0.97), the path line of the selected note, is 4.3:1, under AA's 4.5:1 for small text. The light theme's token moves to oklch 0.5; the dark theme already passes.
- R-P8-122: what automated checks cannot cover stays open in P8-03: VoiceOver on the macOS and iOS apps (needs a Mac and the apps wired to the API, P4), screen-reader and zoom review of the web app by a person.
