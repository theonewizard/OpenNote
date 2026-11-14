"""The search tree compiled to SQL over `search_documents` (API contract §5).

User text reaches `to_tsquery` only as `\\w+` runs, each quoted and given `:*`, so no
user input is ever read as tsquery syntax; phrases go through `phraseto_tsquery`, which
takes plain text. Words of three characters or more also match as a substring of the
title or the body (trigram indexes), for partial words. The caller passes the vault
scope; it is applied in the same WHERE as the matching, so nothing outside it is ranked.
"""

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    Boolean,
    ColumnElement,
    Double,
    Select,
    SQLColumnExpression,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.notes.models import File, Note, NoteLink, NoteTag, SearchDocument
from app.search.grammar import And, Filter, Node, Not, Or, Phrase, Word, parse_date, parse_range
from app.sync.models import Conflict, Revision
from app.vaults.paths import casefold_key

D = SearchDocument
SIMPLE: ColumnElement[Any] = literal_column("'simple'::regconfig")
HEADLINE = "StartSel=«, StopSel=», MaxWords=24, MinWords=8, MaxFragments=1"
TASK = r"(^|\n)[ \t]*[-*+] \[[ xX]\]"
FAMILIES = {
    "pdf": r"\.pdf$",
    "image": r"\.(png|jpe?g|gif|webp|svg|bmp|avif|heic|tiff?)$",
    "audio": r"\.(mp3|wav|m4a|ogg|oga|flac|aac|opus)$",
    "video": r"\.(mp4|mov|webm|mkv|avi|ogv|m4v)$",
}
_LEXEME = re.compile(r"\w+")


@dataclass
class Compiled:
    where: ColumnElement[bool] | None  # None: no condition, every note in scope
    rank: list[ColumnElement[object]]  # tsqueries of the words and phrases not negated
    titles: list[str]  # LIKE patterns of the same, for the title boost

    def rank_query(self) -> ColumnElement[object] | None:
        """The positive words and phrases as one tsquery (any of them), or None."""
        if not self.rank:
            return None
        query = self.rank[0]
        for more in self.rank[1:]:
            query = query.op("||")(more)
        return query


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _prefix(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"


def _day(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(), dt.UTC)


def _revision_in(
    which: SQLColumnExpression[int], start: dt.date | None, end: dt.date | None
) -> ColumnElement[bool]:
    """A revision of the note (`which`: 1 for created, the current one for modified)
    committed on or after `start` and before `end`, both days at 00:00 UTC."""
    conds = [Revision.file_id == D.file_id, Revision.revision == which]
    if start is not None:
        conds.append(Revision.committed_at >= _day(start))
    if end is not None:
        conds.append(Revision.committed_at < _day(end))
    return exists().where(*conds)


def _links(*conds: ColumnElement[bool]) -> ColumnElement[bool]:
    return exists().where(NoteLink.file_id == D.file_id, *conds)


def _attachment_link(pattern: str | None) -> ColumnElement[bool]:
    target = aliased(File)
    conds = [target.kind == "attachment", ~target.deleted]
    if pattern is not None:
        conds.append(func.lower(target.path).regexp_match(pattern))
    return exists(
        select(1)
        .select_from(NoteLink)
        .join(target, target.file_id == NoteLink.resolved_file_id)
        .where(NoteLink.file_id == D.file_id, *conds)
    )


def _property(name: str) -> ColumnElement[bool]:
    flag = cast({"opennote": {name: True}}, JSONB)
    return func.coalesce(Note.properties.op("@>", return_type=Boolean)(flag), False)


def _filter(node: Filter) -> ColumnElement[bool]:
    key, value = node.key, node.value
    if key == "tag":
        tag = casefold_key(value.strip().lstrip("#"))
        return exists().where(
            NoteTag.file_id == D.file_id,
            or_(NoteTag.tag_key == tag, NoteTag.tag_key.like(_prefix(tag), escape="\\")),
        )
    if key in ("notebook", "path"):
        return File.path_key.like(_prefix(casefold_key(value.strip("/"))), escape="\\")
    if key == "title":
        return D.title.ilike(_like(value), escape="\\")
    if key == "type":
        return _attachment_link(FAMILIES[value])
    if key == "has":
        return {
            "attachment": lambda: _attachment_link(None),
            "link": lambda: _links(),
            "unresolved": lambda: _links(
                NoteLink.resolved_file_id.is_(None), NoteLink.target != ""
            ),
            "task": lambda: D.body.regexp_match(TASK),
        }[value]()
    if key in ("created", "modified"):
        start, last = parse_range(value) or (None, None)
        which = literal(1) if key == "created" else File.revision
        return _revision_in(which, start, last + dt.timedelta(days=1) if last else None)
    if key in ("before", "after"):
        day = parse_date(value)
        if day is None:  # the parser only makes valid date filters
            raise RuntimeError(f"invalid date filter {value!r}")
        if key == "before":
            return _revision_in(File.revision, None, day)
        return _revision_in(File.revision, day + dt.timedelta(days=1), None)
    if key == "is" and value == "conflict":
        return exists().where(Conflict.copy_file_id == D.file_id, Conflict.status == "open")
    return _property(value)  # is:favorite, is:archived


def _tsquery(text: str) -> ColumnElement[object] | None:
    lexemes = _LEXEME.findall(text)
    if not lexemes:
        return None
    return func.to_tsquery(SIMPLE, " & ".join(f"'{lexeme}':*" for lexeme in lexemes))


def compile_tree(tree: Node) -> Compiled:
    rank: list[ColumnElement[object]] = []
    titles: list[str] = []

    def walk(node: Node, positive: bool) -> ColumnElement[bool] | None:
        match node:
            case Word(text):
                query = _tsquery(text)
                parts = []
                if query is not None:
                    parts.append(D.tsv.op("@@")(query))
                if len(text) >= 3:
                    parts.append(D.title.ilike(_like(text), escape="\\"))
                    parts.append(D.body.ilike(_like(text), escape="\\"))
                if positive and parts:
                    titles.append(_like(text))
                    if query is not None:
                        rank.append(query)
                return or_(*parts) if parts else None
            case Phrase(text):
                if not _LEXEME.search(text):
                    return None
                query = func.phraseto_tsquery(SIMPLE, text)
                if positive:
                    rank.append(query)
                    titles.append(_like(text))
                return D.tsv.op("@@")(query)
            case Filter():
                return _filter(node)
            case Not(child):
                inner = walk(child, not positive)
                return None if inner is None else not_(func.coalesce(inner, False, type_=Boolean))
            case And(children):
                conds = [c for c in (walk(child, positive) for child in children) if c is not None]
                return and_(*conds) if conds else None
            case Or(children):
                ors = [walk(child, positive) for child in children]
                if any(c is None for c in ors):
                    return None
                return or_(*(c for c in ors if c is not None))

    return Compiled(walk(tree, True), rank, titles)


@dataclass(frozen=True)
class Hit:
    file_id: uuid.UUID
    score: float
    snippet: str | None


async def run_search(
    db: AsyncSession,
    scope: Select[uuid.UUID] | uuid.UUID,
    tree: Node,
    after: tuple[float, uuid.UUID] | None,
    limit: int,
) -> tuple[list[Hit], bool]:
    """One page of hits, best first (score, then file id, both descending), and whether
    more follow. `scope` is the vault ids the caller may read, or one vault id."""
    compiled = compile_tree(tree)
    in_scope = D.vault_id == scope if isinstance(scope, uuid.UUID) else D.vault_id.in_(scope)
    score: ColumnElement[float]
    query = compiled.rank_query()
    if query is not None:
        boost = or_(*(D.title.ilike(p, escape="\\") for p in compiled.titles))
        score = cast(func.ts_rank_cd(D.tsv, query), Double) + case((boost, 1.0), else_=0.0)
    else:
        score = literal(0.0, Double)
    matches = (
        select(D.file_id.label("file_id"), score.label("score"))
        .join(File, File.file_id == D.file_id)
        .join(Note, Note.file_id == D.file_id)
        .where(in_scope, ~File.deleted, compiled.where if compiled.where is not None else true())
        .subquery()
    )
    page = select(matches.c.file_id, matches.c.score)
    if after is not None:
        last_score, last_id = after
        page = page.where(
            or_(
                matches.c.score < last_score,
                and_(matches.c.score == last_score, matches.c.file_id < last_id),
            )
        )
    rows = (
        await db.execute(
            page.order_by(matches.c.score.desc(), matches.c.file_id.desc()).limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    snippets: dict[uuid.UUID, str] = {}
    if query is not None and rows:
        result = await db.execute(
            select(D.file_id, func.ts_headline(SIMPLE, D.body, query, HEADLINE)).where(
                D.file_id.in_([r.file_id for r in rows])
            )
        )
        snippets = {file_id: text for file_id, text in result.all() if text and text.strip()}
    return [Hit(r.file_id, r.score, snippets.get(r.file_id)) for r in rows], more
