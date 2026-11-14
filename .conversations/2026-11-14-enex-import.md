# 2026-11-14 — Evernote ENEX import (P6-10)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Part of the Phase 6 thread. Its prompts ("Start the development phase 5,6 8 using ubi 10", Flemming, 2026-11-14 00:53 UTC) are in `2026-11-14-phase-6-productivity.md` on the Phase 6 branch.

## Rulings

- R-P6-011: ENEX import is `POST /api/v1/imports/enex` (multipart `vault_id`, `folder` defaulting to `Evernote`, `file`; editor role). It runs inside the request, with the upload capped at `max_blob_bytes`. A background job can come later if real exports need it. Every note and attachment is an ordinary create on the commit path, so history, index and sync treat them like any new file. Notes go to `folder/<title>.md`. The title is made path-safe (forbidden and link characters become spaces, reserved names fall back to `Untitled`), and a repeated title gets ` 2`, ` 3` and so on. Attachments go to `folder/_resources/<title>.resources/<file name>`, Obsidian Importer's layout. An attached `.md` file is renamed `.md.txt` so it stays an attachment.
- R-P6-012: imported metadata goes in frontmatter: `tags` (spaces become `-`, as Obsidian Importer does), `created`, `updated` (UTC) and `source`, plus the `id` every OpenNote-created note gets. Writing `created` and `updated` here is not OpenNote auto-writing timestamps (storage contract §2.2). They are the user's Evernote data, carried over once at creation.
- R-P6-013: ENML becomes Markdown with the stdlib (`html.parser`, `xml.etree` iterparse), with no new dependency. Covered: headings, paragraphs, line breaks, emphasis, links, nested lists, `<en-todo>` as tasks, `<pre>` and Evernote's codeblock div as fenced code, quotes, rules and simple tables. `<en-media>` becomes `![[<attachment vault path>]]`: the full path, because names like `image.png` repeat across notes. `<en-crypt>` becomes `` `[encrypted]` ``, and other markup keeps its text. Parsing never fetches DTDs or external entities, and expat's amplification limit refuses entity bombs (a test covers it). A file that breaks partway through keeps the notes already imported and reports the rest as skipped.
- Email-to-note (the other half of P6-10) is not started. It needs an inbound mail path, which is a deployment decision.

## Output

Branch `feature/enex-import` in `.worktrees/import/`.
