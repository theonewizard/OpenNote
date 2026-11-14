"""Backlinks and the link graph (P6-08), read from the derived index (`note_links`).

Read-only queries over rows `app.notes.index` keeps up to date; nothing here touches the
vault. A note's links to itself (`[[#Heading]]`) are neither backlinks nor graph edges.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.notes.models import File, Note, NoteLink
from app.vaults.paths import casefold_key


@dataclass(frozen=True)
class Backlink:
    file_id: uuid.UUID  # the linking note
    path: str
    title: str
    ordinal: int  # the link's position among that note's links
    heading: str | None
    block: str | None
    alias: str | None
    embed: bool


@dataclass(frozen=True)
class Node:
    id: str  # str(file_id), or "unresolved:" + the case-folded link target
    kind: Literal["note", "attachment", "unresolved"]
    label: str  # note title, attachment path, or the target as first written
    path: str | None


@dataclass(frozen=True)
class Edge:
    source: str  # Node.id of the linking note
    target: str
    count: int  # links and embeds from source to target


@dataclass(frozen=True)
class Graph:
    nodes: list[Node]
    edges: list[Edge]


def backlinks(session: Session, file_id: uuid.UUID) -> list[Backlink]:
    """Links and embeds in other live notes that resolve to `file_id`, by path then order."""
    rows = session.execute(
        select(
            NoteLink.file_id,
            File.path,
            Note.title,
            NoteLink.ordinal,
            NoteLink.heading,
            NoteLink.block,
            NoteLink.alias,
            NoteLink.embed,
        )
        .join(File, File.file_id == NoteLink.file_id)
        .join(Note, Note.file_id == NoteLink.file_id)
        .where(NoteLink.resolved_file_id == file_id, NoteLink.file_id != file_id, ~File.deleted)
        .order_by(File.path, NoteLink.ordinal)
    ).all()
    return [Backlink(*row) for row in rows]


def graph(
    session: Session,
    vault_id: uuid.UUID,
    *,
    attachments: bool = False,
    unresolved: bool = False,
    center: uuid.UUID | None = None,
    depth: int = 1,
) -> Graph:
    """The vault's link graph: every live note (orphans too), plus linked attachments and
    unresolved targets when asked, as Obsidian's graph view toggles do. With `center`, the
    local graph instead: nodes within `depth` links of that note in either direction."""
    source, target = aliased(File), aliased(File)
    rows = session.execute(
        select(
            NoteLink.file_id,
            NoteLink.resolved_file_id,
            target.kind,
            target.path,
            NoteLink.target,
            func.count(),
        )
        .join(source, source.file_id == NoteLink.file_id)
        .outerjoin(target, target.file_id == NoteLink.resolved_file_id)
        .where(source.vault_id == vault_id, ~source.deleted)
        .where(NoteLink.resolved_file_id.is_(None) | (NoteLink.resolved_file_id != source.file_id))
        .group_by(
            NoteLink.file_id,
            NoteLink.resolved_file_id,
            target.kind,
            target.path,
            NoteLink.target,
        )
    ).all()
    notes = session.execute(
        select(File.file_id, File.path, Note.title)
        .join(Note, Note.file_id == File.file_id)
        .where(File.vault_id == vault_id, ~File.deleted)
    ).all()
    nodes = {str(fid): Node(str(fid), "note", title, path) for fid, path, title in notes}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for src, dst, kind, path, written, count in sorted(rows, key=lambda r: r[4]):
        if dst is None:
            if not unresolved:
                continue
            node = Node(f"unresolved:{casefold_key(written)}", "unresolved", written, None)
        elif kind == "note":
            node = nodes.get(str(dst)) or Node(str(dst), "note", path, path)
        elif attachments:
            node = Node(str(dst), "attachment", path, path)
        else:
            continue
        nodes.setdefault(node.id, node)
        counts[(str(src), node.id)] += count
    edges = [Edge(s, t, n) for (s, t), n in sorted(counts.items())]
    if center is not None:
        keep = _within(str(center), edges, depth)
        nodes = {k: v for k, v in nodes.items() if k in keep}
        edges = [e for e in edges if e.source in keep and e.target in keep]
    return Graph(sorted(nodes.values(), key=lambda n: (n.kind, n.path or n.label)), edges)


def _within(center: str, edges: list[Edge], depth: int) -> set[str]:
    neighbours: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        neighbours[e.source].add(e.target)
        neighbours[e.target].add(e.source)
    seen, frontier = {center}, {center}
    for _ in range(depth):
        frontier = {n for f in frontier for n in neighbours[f]} - seen
        seen |= frontier
    return seen
