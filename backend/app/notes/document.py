"""The byte-preserving note model (storage contract §2.1, §2.2).

A note is its bytes. Parsing finds the BOM, the dominant line ending and the frontmatter
span; every edit is a text replacement on the original string (`replace_span`), never a
re-render, so bytes outside the edit cannot change.
"""

from dataclasses import dataclass
from typing import Literal

BOM = b"\xef\xbb\xbf"
_OPEN = "---"
_CLOSE = ("---", "...")


class ReadOnlyNote(Exception):
    """The note is not valid UTF-8: it is readable and synced as bytes, never edited."""


@dataclass(frozen=True)
class NoteDocument:
    raw: bytes
    text: str | None  # None when not valid UTF-8 (read-only, opaque)
    bom: bool
    newline: Literal["\n", "\r\n"]
    frontmatter: slice | None  # the YAML between the delimiters, in `text`
    body: slice


def _dominant_newline(text: str) -> Literal["\n", "\r\n"]:
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _line_end(text: str, start: int) -> tuple[int, int]:
    """End of the line starting at `start` (without its ending) and start of the next."""
    end = text.find("\n", start)
    if end == -1:
        return len(text), len(text)
    content_end = end - 1 if end > start and text[end - 1] == "\r" else end
    return content_end, end + 1


def _frontmatter(text: str) -> tuple[slice | None, slice]:
    first_end, pos = _line_end(text, 0)
    if text[:first_end] != _OPEN or pos == first_end:
        return None, slice(0, len(text))
    yaml_start = pos
    while pos < len(text):
        line_end, next_pos = _line_end(text, pos)
        if text[pos:line_end] in _CLOSE:
            return slice(yaml_start, pos), slice(next_pos, len(text))
        pos = next_pos
    return None, slice(0, len(text))


def parse_note(raw: bytes) -> NoteDocument:
    bom = raw.startswith(BOM)
    try:
        text = raw[len(BOM) if bom else 0 :].decode("utf-8")
    except UnicodeDecodeError:
        return NoteDocument(raw, None, bom, "\n", None, slice(0, 0))
    frontmatter, body = _frontmatter(text)
    return NoteDocument(raw, text, bom, _dominant_newline(text), frontmatter, body)


def with_newlines(text: str, newline: str) -> str:
    """`text` with every line ending made `newline`: for new lines OpenNote inserts."""
    return text.replace("\r\n", "\n").replace("\n", newline)


def replace_span(doc: NoteDocument, span: slice, new: str) -> bytes:
    """The note's bytes with `doc.text[span]` replaced by `new`, verbatim; everything else is
    kept byte for byte. Text OpenNote generates goes through `with_newlines` first, so it
    follows the note's dominant line ending; text from an editor keeps its own endings, so
    lines it did not change (in a file with mixed endings, too) keep theirs."""
    if doc.text is None:
        raise ReadOnlyNote("note is not valid UTF-8")
    text = doc.text[: span.start] + new + doc.text[span.stop :]
    return (BOM if doc.bom else b"") + text.encode("utf-8")
