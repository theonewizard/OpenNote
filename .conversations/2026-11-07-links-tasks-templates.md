# 2026-11-07 — Link graph, task and template parsing (workstream 4)

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings use the per-workstream prefix proposed for parallel work (R-P6-…), so they cannot collide with other threads' numbers.

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-07 15:01 | Flemming (project chat) | "Run most of the phases in parallel so it is developed quickly." |
| 2026-11-07 15:03 | Coordinator | Workstream 4: P6-08 backlinks and graph, plus the parse-only parts of P6-01 tasks and P6-05 templates. Anything that writes to notes waits for P2-04. |

## Rulings

- R-P6-001: library code only, no HTTP route, migration or `openapi.json` change. The Phase 2 thread owns the API contract and the note write path; `GET /api/v1/notes/{id}/links` can call `app.notes.graph.backlinks` once it exists. Cost if wrong: a thin route later.
- R-P6-002: a note's links to itself (`[[#Heading]]`, `[[Self]]`) are neither backlinks nor graph edges, as in Obsidian's backlinks pane. Embeds count as links in the graph, as in Obsidian. Attachments and unresolved targets are off by default and switched on per call, matching Obsidian's graph filters; unresolved targets are grouped case-insensitively.
- R-P6-003: a task is a list item whose first line starts with `[c]` followed by a space or the line end, for any single character `c`. Any status but a space counts as done (Obsidian's default; `/`, `-` and others are kept as written). Toggling writes `x` for an open task and a space for any other, so it changes exactly one character, and refuses with `StaleTask` if the character is no longer there. Only the first line of a task is its text. Nothing is stored or written yet.
- R-P6-004: templates follow Obsidian's core Templates plugin: `{{title}}`, `{{date}}`, `{{time}}`, `{{date:FORMAT}}`, `{{time:FORMAT}}`, Moment.js tokens with English names, defaults `YYYY-MM-DD` and `HH:mm`. Unknown variables stay as written. Date offsets and Templater syntax are not supported. Rendering is a text substitution, so the template's bytes, frontmatter and line endings are otherwise kept and it never adds `id`, `created` or `modified`. `extract._mask` became public `mask` so tasks reuse the same masking.

## Output

Branch `feature/links-tasks-parsing` in `.worktrees/parsing/`: `backend/app/notes/graph.py`, `backend/app/tasks/parse.py`, `backend/app/notes/templates.py`, their tests, and the ROADMAP and status rows for P6-01, P6-05 and P6-08.
