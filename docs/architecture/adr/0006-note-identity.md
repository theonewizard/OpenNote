# ADR-0006: Note identity without forcing metadata into files

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §4 wants a stable `id` in frontmatter, but also says not to modify existing notes on open, and §15.8 forbids device-specific state in Markdown. The §4 example also shows `modified:` in frontmatter, which would change on every save and conflict with Obsidian edits.

## Decision
- Identity = frontmatter `id` (UUID) when present, otherwise a server-assigned file ID stored only in the index.
- OpenNote writes `id` only into notes it creates or via the explicit "Normalize metadata" action (decision D5 in the spec).
- External renames are detected by hash/`id` matching during reconciliation.
- OpenNote never auto-writes `created`/`modified`; displayed timestamps come from revisions. Existing values are preserved.

## Consequences
Existing vaults are never touched merely by being opened or synced. Identity of un-normalized notes depends on the server index; if the index is lost it is rebuilt from the history log (storage contract §7), and in the worst case renames done during the outage show as delete + create, without content loss.
