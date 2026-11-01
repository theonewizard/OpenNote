# ADR-0002: Obsidian-compatible vault is the source of truth

Status: Accepted (2026-11-01)  
Date: 2026-10-17  
Deciders: Flemming

## Context
Design §3 and §15.2.2–2.3: Markdown files are authoritative; Obsidian is an application, not a server; indexes must be rebuildable.

## Decision
Implement our own Obsidian-compatible storage engine (Python on the server, Swift on Apple clients) that treats vault files as the only authoritative copy of note content. PostgreSQL, SQLite and IndexedDB hold derived or operational data only. The rules are fixed in the [storage contract](../storage-contract.md).

## Consequences
- Users can open any vault in Obsidian at any time; OpenNote can be removed without data loss.
- Every feature that needs structured data (tags, links, tasks) must derive it by parsing files, and every write must be a byte-preserving text edit. This rules out storing rich-text documents as JSON.
- Server-side revision history must also live outside the database ([ADR-0017](0017-history-store-outside-database.md)).

## Alternatives
- Running Obsidian headless as a backend: not supported by Obsidian, ties us to its runtime.
- Database-first with Markdown export: violates §3.1 and loses direct Obsidian editing.
