"""The search query grammar of API contract §5, parsed by hand into a small tree.

Implicit AND between expressions, `OR` binding tighter, `-` negating, parentheses,
`"phrases"` with `\\"` escapes and `key:value` filters. User input never raises: an
unknown key, a bad filter value or any fragment that does not fit the grammar becomes a
plain word, a stray `)` is dropped and an unclosed `(` or `"` ends at the end of the query.
The query is cut to `MAX_LENGTH` characters, `MAX_TERMS` words, phrases and filters, and
`MAX_DEPTH` nested groups, so the tree (and the SQL built from it) stays small.
"""

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass

MAX_LENGTH = 1024
MAX_TERMS = 32
MAX_DEPTH = 8

TYPE_FAMILIES = frozenset({"pdf", "image", "audio", "video"})
HAS_VALUES = frozenset({"attachment", "link", "unresolved", "task"})
IS_VALUES = frozenset({"favorite", "archived", "conflict"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Word:
    text: str


@dataclass(frozen=True)
class Phrase:
    text: str


@dataclass(frozen=True)
class Filter:
    key: str
    value: str
    quoted: bool = False


@dataclass(frozen=True)
class Not:
    child: Node


@dataclass(frozen=True)
class And:
    children: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    children: tuple[Node, ...]


type Node = Word | Phrase | Filter | Not | And | Or


def parse_date(value: str) -> dt.date | None:
    if not _DATE.fullmatch(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def parse_range(value: str) -> tuple[dt.date, dt.date] | None:
    """`YYYY-MM-DD` or `YYYY-MM-DD..YYYY-MM-DD` as inclusive (first day, last day)."""
    first, sep, last = value.partition("..")
    start, end = parse_date(first), parse_date(last if sep else first)
    if start is None or end is None or end < start:
        return None
    return start, end


_VALID: dict[str, Callable[[str], bool]] = {
    "tag": bool,
    "notebook": bool,
    "path": bool,
    "title": bool,
    "type": TYPE_FAMILIES.__contains__,
    "has": HAS_VALUES.__contains__,
    "is": IS_VALUES.__contains__,
    "created": lambda v: parse_range(v) is not None,
    "modified": lambda v: parse_range(v) is not None,
    "before": lambda v: parse_date(v) is not None,
    "after": lambda v: parse_date(v) is not None,
}
_ENUMERATED = frozenset({"type", "has", "is"})


# Tokens: "(", ")", "-", "OR", or a leaf node.
type Token = str | Word | Phrase | Filter


def _phrase(query: str, start: int) -> tuple[str, int]:
    """The text of the phrase opening at `query[start] == '"'` and the index after it."""
    out: list[str] = []
    i = start + 1
    while i < len(query):
        if query.startswith('\\"', i):
            out.append('"')
            i += 2
        elif query[i] == '"':
            return "".join(out), i + 1
        else:
            out.append(query[i])
            i += 1
    return "".join(out), i


def _filter(written: str, value: str, quoted: bool) -> Filter | Word:
    key = written.lower()
    norm = value.lower() if key in _ENUMERATED else value
    if not norm.strip() or not _VALID[key](norm):
        return Word(f"{written}:{_quote(value) if quoted else value}")
    return Filter(key, norm, quoted)


def _tokens(query: str) -> list[Token]:
    tokens: list[Token] = []
    leaves = 0
    i = 0
    while i < len(query) and leaves < MAX_TERMS:
        c = query[i]
        if c.isspace():
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c == "-" and i + 1 < len(query) and not query[i + 1].isspace() and query[i + 1] != ")":
            tokens.append("-")
            i += 1
        elif c == '"':
            text, i = _phrase(query, i)
            if text.strip():
                tokens.append(Phrase(text))
                leaves += 1
        else:
            start = i
            while i < len(query) and not query[i].isspace() and query[i] not in '()"':
                i += 1
            word = query[start:i]
            key, colon, value = word.partition(":")
            if colon and not value and query.startswith('"', i) and key.lower() in _VALID:
                value, i = _phrase(query, i)
                tokens.append(_filter(key, value, quoted=True))
            elif colon and key.lower() in _VALID:
                tokens.append(_filter(key, value, quoted=False))
            else:
                tokens.append("OR" if word == "OR" else Word(word))
            leaves += 1
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens, self.pos = tokens, 0

    def peek(self, offset: int = 0) -> Token | None:
        at = self.pos + offset
        return self.tokens[at] if at < len(self.tokens) else None

    def query(self, depth: int) -> Node | None:
        """Expressions up to the end, or up to the `)` closing this group."""
        parts: list[Node] = []
        while (tok := self.peek()) is not None:
            if tok == ")":
                if depth > 0:
                    break
                self.pos += 1  # a stray ")" at the top level
                continue
            if (node := self.expr(depth)) is not None:
                parts.append(node)
        return _join(And, parts)

    def expr(self, depth: int) -> Node | None:
        parts = [self.term(depth)]
        while self.peek() == "OR" and self.peek(1) not in (None, ")"):
            self.pos += 1
            parts.append(self.term(depth))
        return _join(Or, [p for p in parts if p is not None])

    def term(self, depth: int) -> Node | None:
        negate = False
        while self.peek() == "-":  # "--a" is "a": a chain never nests
            negate = not negate
            self.pos += 1
        node = self.primary(depth)
        return Not(node) if negate and node is not None else node

    def primary(self, depth: int) -> Node | None:
        tok = self.peek()
        self.pos += 1
        if tok is None or tok == ")":  # after a "-" with nothing to negate
            if tok is not None:
                self.pos -= 1  # the ")" closes the group
            return None
        if tok == "(":
            if depth >= MAX_DEPTH:
                return None  # too deep: the parenthesis is ignored
            node = self.query(depth + 1)
            if self.peek() == ")":
                self.pos += 1
            return node
        if tok == "OR":
            return Word("OR")
        assert not isinstance(tok, str)  # noqa: S101 - "-" was consumed by term()
        return tok


def _join(kind: type[And] | type[Or], parts: list[Node]) -> Node | None:
    flat: list[Node] = []
    for part in parts:
        flat.extend(part.children if isinstance(part, kind) else (part,))
    if not flat:
        return None
    return flat[0] if len(flat) == 1 else kind(tuple(flat))


def parse(query: str) -> Node | None:
    """The tree of a query, or None when it holds nothing to match."""
    return _Parser(_tokens(query[:MAX_LENGTH])).query(0)


def _quote(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def render(node: Node) -> str:
    """The query text of a tree; `parse(render(tree)) == tree` for trees `parse` makes."""
    match node:
        case Word(text):
            return text
        case Phrase(text):
            return _quote(text)
        case Filter(key, value, quoted):
            return f"{key}:{_quote(value) if quoted else value}"
        case Not(child):
            return "-" + _grouped(child, (And, Or))
        case And(children):
            return " ".join(_grouped(c, ()) for c in children)
        case Or(children):
            return " OR ".join(_grouped(c, (And,)) for c in children)


def _grouped(node: Node, kinds: tuple[type, ...]) -> str:
    text = render(node)
    return f"({text})" if isinstance(node, kinds) else text
