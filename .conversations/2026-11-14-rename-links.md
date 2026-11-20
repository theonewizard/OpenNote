# 2026-11-14 — Link update on rename (P6-09)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Part of the Phase 6 thread; the prompts are in [2026-11-14-phase-6-productivity.md](2026-11-14-phase-6-productivity.md) on the Phase 6 branch ("Start the development phase 5,6 8 using ubi 10", Flemming, 2026-11-14 00:53 UTC).

## Rulings

- R-P6-009: link updates on rename go through a new `POST /api/v1/notes/{id}/rename` (`{ path, update_links = true }`, `If-Match`), not `PATCH /notes/{id}`, so that the response can list the rewritten notes without changing `PATCH`'s response type. The move commits first. Each note whose links resolved to the old path is then rewritten as its own revision, based on the revision read (`expected_revision`). A note that changed in between is reported in `skipped` and left alone, never merged. The response lists `{ note, revision, previous_revision }` per rewritten note, so a client can undo with a revision restore (Phase 5) and a rename back. It is not one atomic transaction: notes are separate files on the commit path.
- R-P6-010: rewriting follows Obsidian's "Automatically update internal links". Only the link target text changes. Alias, heading, block, embed `!` and every other byte stay as they were. A bare wiki name stays bare if it still resolves to the renamed note from that linking note; otherwise it becomes the vault path. `.md` is written only if the old link had it. Markdown links get the new path relative to the linking note, URL-encoded unless written in `<angle brackets>` without encoding. Links in code, comments and frontmatter are not touched (the same masking as extraction).
- Not covered yet: folder moves (`PATCH /folders`) do not update links, and the moved note's own relative Markdown links to other files are not rewritten when its folder changes. Wiki links by name are unaffected by the latter.

## Output

Branch `feature/rename-links` in `.worktrees/rename/`.
