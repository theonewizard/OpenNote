# 2026-11-14 — Phase 6 productivity features

Project: OpenNote. Recorded per the last line of `CLAUDE.md` ("Document every prompt"). Rulings continue the workstream prefix from [2026-11-07-links-tasks-templates.md](2026-11-07-links-tasks-templates.md) (R-P6-001 to 004).

## Prompts

| Time (UTC) | From | Prompt |
|---|---|---|
| 2026-11-14 00:53 | Flemming (project chat) | "Start the development phase 5,6 8 using ubi 10" |
| 2026-11-14 00:53 | Coordinator | This thread: the remaining Phase 6 items per `docs/ROADMAP.md`. First what waited on P2-04 (task writes, task index, note-from-template, the links route), then reminders, calendar, clipping and the rest. Image work targets UBI 10. |

## Rulings

- R-P6-005: tasks are indexed as derived rows (`tasks`, migration 0008) next to `note_links` and rebuilt with them. A task is addressed by its note and its position among the note's tasks (`ordinal`); because positions shift when a note changes, toggling requires `If-Match` with the note's revision (428 without, 412 stale), like every other note write. Toggling a plain task changes exactly one character (R-P6-003). Completing an open task with a supported `🔁` rule follows the Tasks plugin: the task gets `✅ <today>` (replacing an old `✅`, before a trailing `^block-id`) and a copy with the next dates, an open status and no block id is inserted on the line above. `today` is the caller's local date when sent, else the server's UTC date. Unchecking never recurs.
- R-P6-006: task metadata is the Tasks plugin's default emoji format only (📅 due, ⏳ scheduled, 🛫 start, ➕ created, ✅ done, ❌ cancelled; 🔺 ⏫ 🔼 🔽 ⏬; `🔁 rule`). Dataview-style `[due:: …]` fields are not read. Supported rules: `every [N] day|week|month|year[s]`, `every weekday`, `every <weekday>[, <weekday>…]`, `every [N] week[s] on <weekdays>`, each optionally `when done`. Months clamp to the last day (Jan 31 → Feb 28). Any other rule is kept as written and indexed, but completing the task only toggles it. Impossible dates (2026-02-30) are ignored.
- R-P6-007: a note is created from a template by `POST /api/v1/notes` with `template_id` (a live note in the same vault; any folder, so a vault without a `templates_folder` setting works) instead of `content`. `{{title}}` is the new file's name without `.md`; dates use `local_time` (with a UTC offset, else 422) or the server's UTC time; date and time formats are Obsidian's defaults. The template's `id` frontmatter is replaced by the new note's so two notes never share an identity. Sending both `content` and `template_id` is a 422.
- R-P6-014: reminders use the Obsidian Reminder plugin's syntax, `(@2026-11-20 09:30)` or `⏰ 2026-11-20 09:30`. A reminder without a time is 09:00, the plugin's default. The time is the note owner's local wall-clock time, stored without a zone (`tasks.remind_at`, migration 0008). Clients ask for due reminders with `GET /api/v1/tasks?remind_before=<local time>` and schedule their own notifications. The server sends no push notifications, because that would need APNs and Web Push credentials. When a recurring task with a reminder is completed, the next occurrence's reminder moves by the same step as its dates. The recurrence rule text ends at a reminder.
- R-P6-015: the calendar integration starts as a read-only iCalendar feed. This is the recommended option on the decision card of 2026-11-14 ("Feed now, CalDAV later"), built while the card waited. `POST /api/v1/calendar-feeds { vault_id, name }` (a signed-in user or device, not a personal access token) returns `/api/v1/calendar/tasks.ics?token=onc_…` once, and only the token's SHA-256 is stored (migration 0009). The feed route is in `KEYLESS_ROUTES` because calendar apps cannot send a bearer token: the token is the credential. It travels in the query string, which the web proxy's log format leaves out, and the API logs no access lines. Every fetch rechecks that the feed's owner is still active and a member of the vault, and deleting the feed revokes it. The feed holds open tasks with a due date (all-day events) or a reminder (a 15-minute floating-time event with a display alarm), up to 5000, and summaries leave out the plugin signifiers. Two-way CalDAV and EventKit on Apple remain.
- R-P6-008: the link graph is `GET /api/v1/graph?vault_id=` (not under `/notes`, it spans the vault), returning `app.notes.graph.graph` as is. The `/notes/{id}/links` route had already shipped with Phase 2.

## Output

Branch `feature/productivity` in `.worktrees/productivity/`: PR A (P6-01, P6-02 recurrence, P6-05, P6-08 backend).
