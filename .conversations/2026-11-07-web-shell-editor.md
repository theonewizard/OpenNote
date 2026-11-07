# 2026-11-07 — Web shell, editor and PWA (P3-02, P3-04, P3-10)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Several threads work in parallel since 2026-11-07, so this record numbers its rulings W1, W2, … instead of continuing the shared R numbers.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |
| 2026-11-07 15:03 | Coordinator (for the above) | Workstream 2 of the parallel plan: P3-02 layout, P3-04 CodeMirror 6 editor (byte-identical save), P3-10 PWA in `web/`, against mocks until the Phase 2 contract lands; TypeScript stays 6.0.3 |

## Rulings

- W1: bytes go into the editor without normalisation. The note is decoded as UTF-8 with `fatal` and `ignoreBOM` (a BOM stays as U+FEFF), the editor's `lineSeparator` is the file's first line separator (other separators stay inside lines as characters), and the text comes back with `state.sliceDoc()`, which joins with that separator (`doc.toString()` always joins with `\n`, which the first test run caught on the CRLF cases). A file that is not UTF-8 opens read-only and is never re-encoded. Every UTF-8 corpus note round-trips in a unit test and, with a typed character appended, through the built app in Playwright.
- W2: the editor lives in a shadow root. nginx's CSP has no `'unsafe-inline'` for styles, and CodeMirror on a document installs its styles as a `<style>` element, which that CSP blocks (the editor rendered unstyled; found because `vite preview` now sends the same CSP for the Playwright tests). In a shadow root CodeMirror uses constructed style sheets, which the CSP allows. Weakening the CSP was not considered: it is a security control (`CLAUDE.md` §2).
- W3: saving is a `PUT /notes/{id}/content` with `If-Match`, automatic 1.5 s after the last edit and on Save or Ctrl/Cmd-S. A 412 stops autosave, keeps the edits in the editor and says so; nothing is overwritten. A failed save is retried by the next edit or the Save button, never in a loop (`CLAUDE.md` §19).
- W4: "live preview" in v1 of the editor is styled Markdown source (headings sized, emphasis, code, links and wiki-links styled, markup dimmed but visible). Hiding markup changes what the cursor walks over and is left for a later item.
- W5: the service worker is hand-written (`web/public/sw.js`, about 60 lines) rather than a plugin: it caches the page and Vite's hashed assets, serves the cached shell offline, drops assets of earlier releases, and never handles `/api/` or the probes. Offline note data is P3-08.
- W6 (superseded by W8): the screens use hand-written types for the fields they read (`web/src/api/types.ts`), matched to the v1 schemas of the Phase 2 contract (pull request #34, not yet merged), so this branch does not carry a generated `schema.d.ts` that would fail the drift check. Once #34 is on `main` the file becomes aliases of the generated types.
- W7: no Zustand (spec §5.5): the selected vault, folder, note and phone pane are four `useState` values in `Layout`; a store comes when state is shared further.

- W8: once the Phase 2 contract and API were on `main` (#34, #42, merged into this branch), `web/src/api/types.ts` became aliases of the generated schemas, and the MSW fixtures are now typed against them.
- W9: checked by hand against the real API (`npm run dev` proxied to a local uvicorn, Python 3.14, PostgreSQL 16 with pgvector, Valkey-compatible Redis): 31 UTF-8 corpus notes created with `POST /notes` saved byte for byte through the UI, and a stale save showed the conflict without overwriting. The run found that frontmatter rendered as headings (`key: value` above `---` is a Markdown setext heading); the editor now parses frontmatter with `@codemirror/lang-yaml`'s `yamlFrontmatter`, and a Playwright test fails without it. `npm run dev` gained a proxy for `/api` to make such runs possible. Registering an existing directory as a vault (`POST /vaults` with `directory`) listed no notes in this run; that was passed to the Phase 2 thread.

## Output

Branch `feature/web-shell-editor` in `.worktrees/web/`: one pull request to `main`.
