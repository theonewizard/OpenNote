"""Rewriting links after a rename (P6-09), as Obsidian's "Automatically update internal links".

`rewrite_links` returns a linking note's bytes with every link that resolved to the old
path pointing at the new one; only the link targets change, every other byte (alias,
heading, block, embed `!`, the rest of the note) is kept.
Wiki links keep their style: a bare name stays a bare name when it still resolves to the
renamed file from that note, else becomes the vault path; `.md` is written only when the
old link had it. Markdown links get the new path relative to the linking note, in the old
link's form (`<angle brackets>`, or `%20` when the old one was URL-encoded).
"""

import posixpath
import re
from collections.abc import Sequence
from urllib.parse import quote, unquote

from app.notes.document import NoteDocument, replace_span
from app.notes.extract import _MARKDOWN, _SCHEME, _WIKI, Link, _split_target, mask
from app.notes.links import resolve


def _resolves_to(target: str, from_path: str, paths: Sequence[str], path: str) -> bool:
    hit = resolve(Link(target, None, None, None, embed=False, markdown=False), from_path, paths)
    return hit == path


def _wiki_target(old: str, from_path: str, new_path: str, after: Sequence[str]) -> str:
    keep_ext = old.lower().endswith(".md") or not new_path.lower().endswith(".md")
    name = posixpath.basename(new_path)
    if "/" not in old:
        short = name if keep_ext else name[:-3]
        if _resolves_to(short, from_path, after, new_path):
            return short
    return new_path if keep_ext else new_path[:-3]


def _markdown_target(raw: str, from_path: str, new_path: str, *, bare: bool) -> str:
    relative = posixpath.relpath(new_path, posixpath.dirname(from_path) or ".")
    return quote(relative, safe="/") if bare or unquote(raw) != raw else relative


def rewrite_links(
    doc: NoteDocument,
    from_path: str,
    old_path: str,
    new_path: str,
    before: Sequence[str],
    after: Sequence[str],
) -> bytes | None:
    """The note at `from_path` with its links to `old_path` aimed at `new_path`, or None
    when it has none. `before` and `after` are the vault's live paths around the rename."""
    if doc.text is None:
        return None
    start = doc.body.start
    body = mask(doc.text[start:])
    edits: list[tuple[int, int, str]] = []
    for m in _WIKI.finditer(body):
        raw = doc.text[start + m.start(2) : start + m.end(2)]
        head = re.split(r"\\?\|", raw, maxsplit=1)[0]
        target, _, _ = _split_target(head)
        if target and _resolves_to(target, from_path, before, old_path):
            at = start + m.start(2) + raw.index(target)
            edits.append((at, at + len(target), _wiki_target(target, from_path, new_path, after)))
    for m in _MARKDOWN.finditer(body):
        group = 3 if m.group(3) is not None else 4
        url = doc.text[start + m.start(group) : start + m.end(group)]
        if _SCHEME.match(url):
            continue
        path_part = url.split("#", 1)[0]
        target, _, _ = _split_target(unquote(url))
        if target and _resolves_to(target, from_path, before, old_path):
            at = start + m.start(group)
            edits.append(
                (
                    at,
                    at + len(path_part),
                    _markdown_target(path_part, from_path, new_path, bare=group == 4),
                )
            )
    if not edits:
        return None
    text = doc.text
    for begin, end, new in sorted(edits, reverse=True):
        text = text[:begin] + new + text[end:]
    return replace_span(doc, slice(0, len(doc.text)), text)
