"""Task extraction and the one-character toggle (storage contract §2.3, P6-01)."""

import pytest

from app.notes.document import parse_note
from app.tasks.parse import StaleTask, extract_tasks, toggle


def _tasks(text: str):
    return extract_tasks(parse_note(text.encode()))


def test_statuses_markers_and_lines():
    note = "---\ntitle: T\n---\n- [ ] open\n* [x] done\n+ [X] Done\n1. [/] half\n2) [-] dropped\n"
    got = [(t.text, t.status, t.done, t.line) for t in _tasks(note)]
    assert got == [
        ("open", " ", False, 3),
        ("done", "x", True, 4),
        ("Done", "X", True, 5),
        ("half", "/", True, 6),
        ("dropped", "-", True, 7),
    ]


def test_not_tasks():
    note = (
        "[ ] no list marker\n"
        "- [] empty brackets\n"
        "- [ ]no space\n"
        "-[ ] no space after marker\n"
        "- plain item [ ] later\n"
        "```\n- [ ] fenced\n```\n"
        "\n    - [ ] indented code\n\n"
        "<!--\n- [ ] html comment\n-->\n"
        "%%\n- [ ] obsidian comment\n%%\n"
        "`- [ ] inline code`\n"
    )
    assert _tasks(note) == []


def test_frontmatter_lookalike_is_not_a_task():
    assert _tasks("---\nlist:\n- [ ] yaml\n---\nbody\n") == []


def test_quotes_callouts_empty_text_and_crlf():
    note = "> - [ ] quoted\n\n> [!todo]\n> - [x] in callout\n\n- [ ]\r\n- [ ] crlf\r\n"
    assert [(t.text, t.status) for t in _tasks(note)] == [
        ("quoted", " "),
        ("in callout", "x"),
        ("", " "),
        ("crlf", " "),
    ]


def test_nested_tasks_get_their_parent():
    note = "- [ ] a\n  - [ ] a.1\n    - plain\n      - [x] a.1.x\n- [ ] b\n  1. [ ] b.1\n"
    got = [(t.text, t.parent) for t in _tasks(note)]
    assert got == [("a", None), ("a.1", 0), ("a.1.x", 1), ("b", None), ("b.1", 3)]


def test_toggle_changes_exactly_one_character():
    raw = "﻿---\r\nid: x\r\n---\r\nText\n- [ ] one  \r\n- [x] two\n".encode()
    doc = parse_note(raw)
    one, two = extract_tasks(doc)
    for task, char in ((one, b"x"), (two, b" ")):
        out = toggle(doc, task)
        assert len(out) == len(raw)
        diff = [i for i, (a, b) in enumerate(zip(raw, out, strict=True)) if a != b]
        assert len(diff) == 1 and out[diff[0] : diff[0] + 1] == char
        assert extract_tasks(parse_note(out))[0 if task is one else 1].done is not task.done


def test_toggle_refuses_a_stale_task():
    task = _tasks("- [ ] one\n")[0]
    with pytest.raises(StaleTask):
        toggle(parse_note(b"- [x] one\n"), task)
    with pytest.raises(StaleTask):
        toggle(parse_note(b"\xff- [ ] one\n"), task)


def test_read_only_note_has_no_tasks():
    assert extract_tasks(parse_note(b"\xff- [ ] x\n")) == []
