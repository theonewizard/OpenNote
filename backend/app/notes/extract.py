"""Read-only extraction of links, embeds and tags from a note body (storage contract §2.3).

Code (fenced, indented, inline), HTML blocks, HTML comments and `%%comments%%` are masked
out first, keeping offsets, then plain regular expressions run over what is left.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from markdown_it import MarkdownIt

from app.notes.document import NoteDocument

_MD = MarkdownIt("commonmark")
_MASKED_BLOCKS = frozenset({"fence", "code_block", "html_block"})
_INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OBSIDIAN_COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
_WIKI = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
_MARKDOWN = re.compile(r"(!?)\[([^\]\n]*)\]\((?:<([^>\n]*)>|([^)\s]*))\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_TAG = re.compile(r"(?:(?<=\s)|^)#([^\s#!\"$%&'()*+,.:;<=>?@\[\\\]^`{|}~]+)", re.MULTILINE)


@dataclass(frozen=True)
class Link:
    target: str  # without #heading, #^block and |alias; "" for a link to a heading here
    heading: str | None
    block: str | None
    alias: str | None  # also an embed's size, as in ![[image.png|300]]
    embed: bool
    markdown: bool  # [text](path) rather than [[wiki]]


@dataclass(frozen=True)
class Extraction:
    links: list[Link] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    external_urls: list[str] = field(default_factory=list)


def _blank(text: str, start: int, end: int) -> str:
    """`text` with [start, end) replaced by spaces, newlines kept, so offsets stay put."""
    return text[:start] + re.sub(r"[^\n]", " ", text[start:end]) + text[end:]


def _mask(body: str) -> str:
    line_starts = [0]
    for line in body.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    for token in _MD.parse(body):
        if token.type in _MASKED_BLOCKS and token.map:
            begin, end = token.map
            body = _blank(body, line_starts[begin], line_starts[min(end, len(line_starts) - 1)])
    for pattern in (_OBSIDIAN_COMMENT, _HTML_COMMENT, _INLINE_CODE):
        for match in list(pattern.finditer(body)):
            body = _blank(body, match.start(), match.end())
    return body


def _split_target(raw: str) -> tuple[str, str | None, str | None]:
    target, sep, rest = raw.partition("#")
    if not sep:
        return target.strip(), None, None
    if rest.startswith("^"):
        return target.strip(), None, rest[1:].strip()
    return target.strip(), rest.strip(), None


def _wiki(match: re.Match[str]) -> Link:
    """[[target#heading|alias]]; `\\|` is the pipe escaped inside a table cell."""
    parts = re.split(r"\\?\|", match.group(2), maxsplit=1)
    alias = parts[1] if len(parts) == 2 else None
    target, heading, block = _split_target(parts[0])
    return Link(target, heading, block, alias, embed=bool(match.group(1)), markdown=False)


def extract(doc: NoteDocument) -> Extraction:
    if doc.text is None:
        return Extraction()
    body = _mask(doc.text[doc.body])
    found: list[tuple[int, Link]] = [(m.start(), _wiki(m)) for m in _WIKI.finditer(body)]
    urls: list[tuple[int, str]] = []
    for m in _MARKDOWN.finditer(body):
        url = m.group(3) if m.group(3) is not None else m.group(4)
        if _SCHEME.match(url):
            urls.append((m.start(), url))
            continue
        target, heading, block = _split_target(unquote(url))
        alias = m.group(2) or None
        found.append((m.start(), Link(target, heading, block, alias, bool(m.group(1)), True)))
    tags = [t for t in (m.group(1) for m in _TAG.finditer(body)) if not t.isdigit()]
    return Extraction(
        links=[link for _, link in sorted(found, key=lambda x: x[0])],
        tags=tags,
        external_urls=[u for _, u in sorted(urls)],
    )
