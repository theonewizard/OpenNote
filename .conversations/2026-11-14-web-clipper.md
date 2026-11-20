# 2026-11-14 — Web clipper (P6-04)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Part of the Phase 6 thread. Its prompts ("Start the development phase 5,6 8 using ubi 10", Flemming, 2026-11-14 00:53 UTC) are in `2026-11-14-phase-6-productivity.md` on the Phase 6 branch.

## Rulings

- R-P6-016: the clipper converts on the server. The extension sends the selection's HTML or the page's main content (`article`, else `main`, else `body`) to `POST /api/v1/clips`, and the server turns it into Markdown with the ENEX import's converter. The extension therefore ships no Readability or Turndown copy, and has no build step and no dependency. The converter gained a `base_url` (relative links and images resolved against the page) and drops `javascript:`, `data:` and other non-http(s)/mailto URLs, scripts, forms, media and embedded frames. Images stay remote links, and nothing is downloaded server-side, so the server makes no outbound requests on a user's behalf.
- R-P6-017: the extension authenticates with a personal access token with write scope, limited to the vault it clips into (`X-API-Key`). It lives in the browser's extension storage. The extension requests host access only for the configured server (`optional_host_permissions`, asked at Connect), plus `activeTab` and `scripting` to read the page the user clips. A clip becomes `Clippings/<title>.md` (a repeated title gets ` 2`), with `title`, `source`, `created` and `tags` frontmatter. The `clippings` tag is always there.
- Not covered: the Apple share sheet (the Apple workstream), and store packaging (Chrome Web Store, AMO), which needs Flemming's publisher accounts.

## Output

Branch `feature/web-clipper` in `.worktrees/clipper/`, stacked on `feature/enex-import` (#54).
