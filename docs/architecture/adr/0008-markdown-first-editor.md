# ADR-0008: Markdown-first source-preserving editor

Status: Proposed  
Date: 2026-10-17  
Deciders: Flemming (pending review)

## Context
Design §6.3 lists TipTap/ProseMirror but then recommends a Markdown-first editor with live preview for the first release, and §10 requires preserving unsupported syntax. ProseMirror-based editors hold a document tree and serialize back to Markdown, which normalizes syntax.

## Decision
- Web: **CodeMirror 6** with `@codemirror/lang-markdown`, live-preview decorations (headings, emphasis, links, wiki-links, embeds, callouts, checkboxes, tables rendered inline while the cursor is elsewhere), and the raw text as the only model.
- Apple: TextKit 2 text view with attribute-based styling over the raw text.
- WYSIWYG (TipTap) is reconsidered only after the compatibility corpus exists and can prove byte-preserving round trips (design §16.A).

## Consequences
Round-trip safety is structural: the editor never re-renders Markdown. The editing experience is closer to Obsidian's Live Preview than to Evernote's rich text; that gap is accepted for v1. TipTap appears in §15.3 as "or another suitable editor framework", so this is within the stated stack.
