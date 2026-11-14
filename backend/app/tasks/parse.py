"""Read-only task extraction (storage contract §2.3, P6-01 parse part).

A task is a list item whose text starts with `[c]`: `- [ ] open`, `* [x] done`, `1. [/] other
status`, also inside block quotes and callouts. Code, HTML blocks and comments are masked out
first, as for links. `toggle` computes the bytes of a one-character status change; nothing
writes them to the vault until the Phase 2 note write path (P2-04) exists.
"""

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt

from app.notes.document import NoteDocument, replace_span
from app.notes.extract import mask

_MD = MarkdownIt("commonmark")
_TASK = re.compile(r"[ \t>]*(?:[-*+]|\d{1,9}[.)])[ \t]+\[([^\]\r\n])\](?:[ \t]+|\r?$)")


@dataclass(frozen=True)
class Task:
    text: str  # the rest of the item's first line, without the `[c] `
    status: str  # the character between the brackets
    done: bool  # any status but a space (Obsidian's default)
    line: int  # 0-based line in the note, frontmatter included
    offset: int  # index of the status character in `NoteDocument.text`
    parent: int | None  # index of the enclosing task in the list, for subtasks


class StaleTask(Exception):
    """The note no longer has the task's status character where the task says."""


def extract_tasks(doc: NoteDocument) -> list[Task]:
    if doc.text is None:
        return []
    start = doc.body.start
    body = doc.text[start:]
    masked = mask(body)
    line_starts = [0]
    for line in masked.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    first_line = doc.text.count("\n", 0, start)
    tasks: list[Task] = []
    stack: list[int | None] = []  # per open list item: its task index, or None
    for token in _MD.parse(masked):
        if token.type == "list_item_close":
            stack.pop()
        elif token.type == "list_item_open" and token.map:
            row = token.map[0]
            begin, end = line_starts[row], line_starts[min(row + 1, len(line_starts) - 1)]
            index = None
            if m := _TASK.match(masked, begin, end):
                index = len(tasks)
                text = body[m.end() : end].rstrip("\r\n")
                status = m.group(1)
                parent = next((i for i in reversed(stack) if i is not None), None)
                offset = start + m.start(1)
                tasks.append(Task(text, status, status != " ", first_line + row, offset, parent))
            stack.append(index)
    return tasks


def toggle(doc: NoteDocument, task: Task) -> bytes:
    """The note's bytes with `task` checked (`x`) or unchecked (space): one character
    changes, everything else is kept byte for byte."""
    if doc.text is None or doc.text[task.offset : task.offset + 1] != task.status:
        raise StaleTask(f"no task status {task.status!r} at offset {task.offset}")
    return replace_span(doc, slice(task.offset, task.offset + 1), " " if task.done else "x")
