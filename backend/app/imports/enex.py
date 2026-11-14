"""Evernote ENEX import (P6-10): read an export, turn each note's ENML into Markdown.

`read_enex` streams `<note>` elements out of an `.enex` file (one note in memory at a
time). `to_markdown` converts ENML, Evernote's XHTML subset, the way Obsidian's official
Importer does in spirit: headings, paragraphs, emphasis, links, lists, checkboxes
(`<en-todo>` becomes a task), code, quotes, rules and simple tables; `<en-media>` becomes
an embed of the attachment with that MD5 hash; anything else keeps only its text.
The parser never resolves external entities or fetches a DTD (expat's defaults), and
expat refuses entity expansion bombs.
"""

import base64
import binascii
import datetime as dt
import hashlib
import mimetypes
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import IO
from urllib.parse import urljoin
from xml.etree.ElementTree import Element, ParseError, iterparse  # see docstring

from app.vaults.paths import FORBIDDEN_CHARS, LINK_CHARS, RESERVED_NAMES, truncate_utf8


class EnexError(Exception):
    """The file is not a readable ENEX export."""


@dataclass(frozen=True)
class Resource:
    data: bytes
    mime: str
    file_name: str
    md5: str  # what `<en-media hash=...>` refers to


@dataclass(frozen=True)
class EnexNote:
    title: str
    enml: str
    created: dt.datetime | None
    updated: dt.datetime | None
    tags: list[str] = field(default_factory=list)
    source_url: str | None = None
    resources: list[Resource] = field(default_factory=list)


def _time(text: str | None) -> dt.datetime | None:
    try:  # 20261114T081500Z
        return dt.datetime.strptime(text or "", "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    except ValueError:
        return None


def _text(element: Element, path: str) -> str | None:
    found = element.find(path)
    return found.text if found is not None and found.text is not None else None


def _resource(element: Element, index: int) -> Resource | None:
    raw = _text(element, "data")
    if raw is None:
        return None
    try:
        data = base64.b64decode(re.sub(r"\s+", "", raw), validate=True)
    except binascii.Error, ValueError:
        return None
    mime = (_text(element, "mime") or "application/octet-stream").strip()
    name = (_text(element, "resource-attributes/file-name") or "").strip()
    if not name:
        name = f"attachment-{index + 1}{mimetypes.guess_extension(mime) or ''}"
    return Resource(data, mime, name, hashlib.md5(data, usedforsecurity=False).hexdigest())


def read_enex(stream: IO[bytes]) -> Iterator[EnexNote]:
    try:
        for _, element in iterparse(stream, events=("end",)):  # noqa: S314  # see docstring
            if element.tag != "note":
                continue
            resources = [
                r for i, e in enumerate(element.findall("resource")) if (r := _resource(e, i))
            ]
            yield EnexNote(
                title=(_text(element, "title") or "").strip(),
                enml=_text(element, "content") or "",
                created=_time(_text(element, "created")),
                updated=_time(_text(element, "updated")),
                tags=[t.text.strip() for t in element.findall("tag") if t.text and t.text.strip()],
                source_url=_text(element, "note-attributes/source-url"),
                resources=resources,
            )
            element.clear()
    except ParseError as err:
        raise EnexError("not a valid ENEX file") from err


# File names -------------------------------------------------------------------------------

_UNSAFE = re.compile(f"[{re.escape(FORBIDDEN_CHARS + LINK_CHARS)}\\x00-\\x1f\\x7f]")


def safe_name(name: str, fallback: str, max_bytes: int = 200) -> str:
    """`name` usable as one vault path segment: forbidden and link characters become
    spaces, no leading dot or trailing space or dot, no reserved device name."""
    cleaned = re.sub(r"\s+", " ", _UNSAFE.sub(" ", name)).strip().lstrip(".").rstrip(". ")
    cleaned = truncate_utf8(cleaned, max_bytes).rstrip(". ")
    if not cleaned or cleaned.split(".")[0].upper() in RESERVED_NAMES:
        return fallback
    return cleaned


# ENML to Markdown -------------------------------------------------------------------------

_BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "li", "tr"}
_FENCE = "```"
_SKIP = {
    "head", "style", "script", "title", "noscript", "template", "svg", "canvas", "iframe",
    "object", "form", "button", "select", "textarea", "video", "audio",
}  # fmt: skip
_LINK_SCHEMES = ("http://", "https://", "mailto:")
_EMPHASIS = {"b": "**", "strong": "**", "i": "*", "em": "*", "s": "~~", "strike": "~~", "del": "~~"}


class _Converter(HTMLParser):
    def __init__(self, media: dict[str, str], base_url: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self.media = media
        self.base_url = base_url
        self.out: list[str] = []  # finished blocks
        self.line: list[str] = []  # the block being built
        self.prefix = ""  # list marker, heading hashes or quote marks for the current block
        self.lists: list[list[int]] = []  # per open list: [is_ordered, next number]
        self.quote = 0
        self.code = 0  # block depth inside a code block (`<pre>` or Evernote's codeblock div)
        self.skip = 0
        self.links: list[str] = []
        self.table: list[list[str]] | None = None
        self.cell: list[str] | None = None

    # blocks
    def _flush(self) -> None:
        text = re.sub(r"[ \t]+", " ", "".join(self.line)).strip()
        if text or self.prefix.strip().startswith(
            ("-", "1", "2", "3", "4", "5", "6", "7", "8", "9")
        ):
            quote = "> " * self.quote
            lines = text.split("\n") or [""]
            block = (quote + self.prefix + lines[0]).rstrip()
            indent = quote + " " * len(self.prefix)
            block += "".join("\n" + (indent + rest).rstrip() for rest in lines[1:])
            self.out.append(block)
        self.line, self.prefix = [], ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag in _SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif self.code:  # inside code only line structure counts
            if tag in _BLOCKS or tag == "br":
                if self.line and not "".join(self.line).endswith("\n"):
                    self._write("\n")
                self.code += tag != "br"
        elif tag == "pre" or (tag == "div" and "-en-codeblock" in (a.get("style") or "")):
            self._flush()
            self.code = 1
        elif tag in ("td", "th") and self.table is not None:
            self.cell = []
        elif tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.table.append([])
        elif tag in ("ul", "ol"):
            self._flush()
            self.lists.append([tag == "ol", 1])
        elif tag == "li":
            self._flush()
            depth = max(len(self.lists) - 1, 0)
            marker = "- "
            if self.lists and self.lists[-1][0]:
                marker = f"{self.lists[-1][1]}. "
                self.lists[-1][1] += 1
            self.prefix = "  " * depth + marker
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag == "blockquote":
            self._flush()
            self.quote += 1
        elif tag in _BLOCKS:
            self._flush()
        elif tag == "br":
            self._write("\n")
        elif tag == "hr":
            self._flush()
            self.out.append("---")
        elif tag in _EMPHASIS:
            self._write(_EMPHASIS[tag])
        elif tag == "code":
            self._write("`")
        elif tag == "a":
            self.links.append(self._url(a.get("href")))
            self._write("[")
        elif tag == "en-todo":
            box = "- [x] " if (a.get("checked") or "").lower() == "true" else "- [ ] "
            if not "".join(self.line).strip() and not self.prefix:
                self.prefix = box
            elif self.prefix.endswith("- "):  # a checkbox inside a list item
                self.prefix = self.prefix[:-2] + box
            else:
                self._write(box[2:])
        elif tag == "en-media":
            name = self.media.get((a.get("hash") or "").lower())
            self._write(f"![[{name}]]" if name else "")
        elif tag == "en-crypt":
            self.skip += 1
            self._write("`[encrypted]`")
        elif tag == "img" and (src := self._url(a.get("src"))).startswith(("http://", "https://")):
            alt = re.sub(r"[\[\]\s]+", " ", a.get("alt") or "").strip()
            self._write(f"![{alt}](<{src}>)" if " " in src else f"![{alt}]({src})")

    def _url(self, value: str | None) -> str:
        """An absolute http(s) or mailto URL, or "" (javascript:, data: and the like)."""
        url = urljoin(self.base_url or "", (value or "").strip())
        return url if url.lower().startswith(_LINK_SCHEMES) else ""

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "hr", "en-todo", "en-media", "img", "en-crypt"):
            self.handle_endtag(tag)
        elif tag == "en-crypt":
            self.skip -= 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP or tag == "en-crypt":
            self.skip = max(self.skip - 1, 0)
        elif self.skip:
            return
        elif self.code:
            if tag in _BLOCKS:
                self.code -= 1
                if not self.code:
                    code = "".join(self.line).strip("\n")
                    self.line = []
                    quote = "> " * self.quote
                    self.out.append(
                        "\n".join(quote + row for row in [_FENCE, *code.split("\n"), _FENCE])
                    )
        elif tag in ("td", "th") and self.table is not None and self.cell is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip().replace("|", "\\|")
            if self.table:
                self.table[-1].append(text)
            self.cell = None
        elif tag == "table" and self.table is not None:
            rows = [r for r in self.table if r]
            self.table = None
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                self.out.append("\n".join(lines))
        elif tag in ("ul", "ol"):
            self._flush()
            if self.lists:
                self.lists.pop()
        elif tag == "blockquote":
            self._flush()
            self.quote = max(self.quote - 1, 0)
        elif tag in _BLOCKS:
            self._flush()
        elif tag in _EMPHASIS:
            self._write(_EMPHASIS[tag])
        elif tag == "code":
            self._write("`")
        elif tag == "a":
            href = self.links.pop() if self.links else ""
            self._write((f"](<{href}>)" if " " in href else f"]({href})") if href else "]")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self._write(data if self.code else data.replace("\n", " "))

    def _write(self, text: str) -> None:
        (self.cell if self.cell is not None else self.line).append(text)

    def result(self) -> str:
        self._flush()
        markdown = "\n\n".join(self.out)
        # Consecutive list items and tasks form one list: drop the blank line between them.
        markdown = re.sub(
            r"(?m)^(\s*(?:[-*] |\d+\. ).*)\n\n(?=\s*(?:[-*] |\d+\. ))", r"\1\n", markdown
        )
        return markdown.strip() + "\n" if markdown.strip() else ""


def to_markdown(enml: str, media: dict[str, str], base_url: str | None = None) -> str:
    """Markdown for one note's ENML (or any HTML, as for web clips); `media` maps MD5 hex
    to the attachment's file name, `base_url` resolves relative links and images."""
    converter = _Converter(media, base_url)
    converter.feed(re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", enml))
    converter.close()
    return converter.result()
