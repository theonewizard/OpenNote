"""Three-way merge of a note, run on the server only (sync protocol §6).

Frontmatter merges key by key and is re-emitted by splicing changed keys into `theirs`;
the body merges line by line with diff3. Nothing is ever written with conflict markers:
an unsafe merge is reported as unclean and the caller keeps both versions.
"""

import posixpath
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from merge3 import Merge3

from app.notes.document import NoteDocument, parse_note, replace_span, with_newlines
from app.notes.frontmatter import DELETE, FrontmatterInvalid, load_frontmatter, splice_keys
from app.vaults.paths import FORBIDDEN_CHARS, LINK_CHARS, MAX_SEGMENT_BYTES, truncate_utf8

_MISSING: Any = object()


@dataclass(frozen=True)
class MergeResult:
    clean: bool
    data: bytes | None


def _merge_lines(base: str, theirs: str, ours: str) -> str | None:
    groups = Merge3(
        base.splitlines(keepends=True),
        ours.splitlines(keepends=True),
        theirs.splitlines(keepends=True),
    ).merge_groups()
    out: list[str] = []
    for group in groups:
        if group[0] == "conflict":
            return None
        out.extend(group[1])
    return "".join(out)


def _key_changes(docs: list[NoteDocument]) -> dict[str, Any] | None:
    """Top-level keys to splice into `theirs` (ours' changes); None on a key conflict.
    FrontmatterInvalid when any side's frontmatter is not a mapping."""
    maps: list[Mapping[str, Any]] = [load_frontmatter(d) or {} for d in docs]
    base, theirs, ours = maps
    changes: dict[str, Any] = {}
    for key in dict.fromkeys([*base, *theirs, *ours]):
        b, t, o = (m.get(key, _MISSING) for m in (base, theirs, ours))
        if o in (b, t):
            continue
        if t != b:
            return None  # changed on both sides to different values
        changes[key] = DELETE if o is _MISSING else o
    return changes


def merge_note(base: bytes, theirs: bytes, ours: bytes) -> MergeResult:
    """Merge `ours` (pushed) into `theirs` (current), both derived from `base`."""
    if ours in (theirs, base):
        return MergeResult(True, theirs)
    if theirs == base:
        return MergeResult(True, ours)
    docs = [parse_note(raw) for raw in (base, theirs, ours)]
    if any(d.text is None for d in docs):
        return MergeResult(False, None)  # opaque bytes: no line merge
    newline = docs[1].newline
    if len({d.newline for d in docs}) > 1:  # merge on \n, then write theirs' endings
        texts = [d.text.replace("\r\n", "\n") for d in docs if d.text is not None]
        merged = _merge_lines(*texts)
        if merged is None:
            return MergeResult(False, None)
        return MergeResult(True, _encode(docs[1], with_newlines(merged, newline)))
    try:
        changes = _key_changes(docs)
    except FrontmatterInvalid:
        merged = _merge_lines(*(d.text for d in docs if d.text is not None))
        if merged is None:
            return MergeResult(False, None)
        return MergeResult(True, _encode(docs[1], merged))
    if changes is None:
        return MergeResult(False, None)
    bodies = [d.text[d.body] for d in docs if d.text is not None]
    body = _merge_lines(*bodies)
    if body is None:
        return MergeResult(False, None)
    out = replace_span(docs[1], docs[1].body, body)
    return MergeResult(True, splice_keys(parse_note(out), changes) if changes else out)


def _encode(theirs: NoteDocument, text: str) -> bytes:
    return (b"\xef\xbb\xbf" if theirs.bom else b"") + text.encode()


def conflict_copy_path(path: str, device_name: str, day: str, taken: Callable[[str], bool]) -> str:
    """`<name> (conflict <device> <yyyy-mm-dd>)<ext>`, then ` 2`, ` 3` on collision."""
    folder, name = posixpath.split(path)
    stem, ext = posixpath.splitext(name)
    device = "".join(
        "-" if c in FORBIDDEN_CHARS or c in LINK_CHARS or not c.isprintable() else c
        for c in truncate_utf8(device_name, 64)
    )
    n = 1
    while True:
        tail = f" (conflict {device} {day})" + (f" {n}" if n > 1 else "") + ext
        candidate = truncate_utf8(stem, MAX_SEGMENT_BYTES - len(tail.encode())) + tail
        if not taken(posixpath.join(folder, candidate)):
            return posixpath.join(folder, candidate)
        n += 1
