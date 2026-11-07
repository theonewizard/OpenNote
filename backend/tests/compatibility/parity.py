"""Parity fixtures: inputs plus what the Python parsers make of them, for the Swift twins.

The corpus covers whole notes; these lists pin the edge cases one rule at a time (YAML scalar
resolution, path rules, extraction). `tests/compatibility/parity/*.json` is generated from the
Python code, so it is the reference the Swift tests in `apple/Packages/OpenNoteCore` compare
with. Regenerate after changing a parser or a list below:

    cd backend && ../.venv/bin/python -m tests.compatibility.parity

`test_parity_fixtures.py` fails when the committed files drift from the Python behaviour.
"""

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

from app.notes.document import parse_note
from app.notes.extract import extract
from app.notes.frontmatter import read_properties
from app.vaults.paths import casefold_key, classify, normalize, validate

PARITY = Path(__file__).resolve().parents[3] / "tests" / "compatibility" / "parity"

# Frontmatter YAML, one block each. Left out on purpose, because Python has no JSON answer:
# explicit tags (`!!str 5` gives a TaggedScalar), impossible dates and times (ValueError
# escapes read_properties), non-scalar keys, .inf/.nan (not JSON).
FRONTMATTER = [
    "a: 1",
    "a: -0",
    "a: +1",
    "a: 012",
    "a: 0o17",
    "a: 0x1F",
    "a: 0b101",
    "a: 1_000",
    "a: 0o",
    "a: 99999999999999999999",
    "a: 1.0",
    "a: 1e3",
    "a: 3.",
    "a: -.5",
    "a: 1_0.5",
    "a: 3.e2",
    "a: +.5e+3",
    "a: 1.5e-3",
    "a: true",
    "a: True",
    "a: TRUE",
    "a: false",
    "a: yes",
    "a: no",
    "a: on",
    "a: tRUE",
    "a: ~",
    "a: null",
    "a: Null",
    "a: NULL",
    "a:",
    "a: nul",
    "a: 2024-01-02",
    "a: 2024-1-2",
    "a: 2024-1-2 3:04:05",
    "a: 2024-03-04T05:06:07",
    "a: 2024-03-04t05:06:07",
    "a: 2024-03-04 05:06:07 Z",
    "a: 2024-03-04T05:06:07Z",
    "a: 2024-03-04T05:06:07+2",
    "a: 2024-03-04T05:06:07-05:30",
    "a: 2024-03-04T05:06:07-00:00",
    "a: 2024-03-04T05:06:07.0",
    "a: 2024-03-04T05:06:07.",
    "a: 2024-03-04T05:06:07.5",
    "a: 2024-03-04T05:06:07.123456789",
    "a: 2024-03-04T05:06:07.9999995",
    "a: 2024-02-29",
    "a: 00:00",
    "a: 12:30:00",
    "a: 1:2",
    'a: "x"',
    "a: 'it''s'",
    'a: "\\u00e9\\t"',
    "a: 5 # comment",
    'a: "5"',
    "a: '1.0'",
    "a: |\n  literal\n  text",
    "a: >\n  folded\n  text",
    "a: |-\n  strip",
    "a: plain text: no",
    "a: #not a comment?",
    "a: x#y",
    "a: -",
    "a: .",
    "a: [1, two, 3.0, null]",
    "a: {b: c, d: [e]}",
    "a:\n  - 1\n  - [x, {b: c}]",
    "a:\n  b:\n    c: 1",
    "tags: one, two , ,three",
    "tags: [x, y]",
    "tags: single",
    "tags:",
    "aliases: A, B",
    "tags: 5",
    "tags:\n  - a\n  - b",
    "base: &b\n  x: 1\nderived:\n  <<: *b\n  y: 2",
    "base: &b\n  x: 1\nderived:\n  x: 9\n  <<: *b",
    "a: &a {x: 1}\nb: &b {x: 2, y: 2}\nc:\n  <<: [*a, *b]",
    "s: &s hello\nt: *s",
    "1: x",
    "true: x",
    "null: x",
    "1.5: x",
    "2024-01-02: x",
    "'quoted': x",
    "0x10: x",
    "",
    "# only a comment",
    "~",
    "a: 1\na: 2",
    "- a\n- b",
    "just text",
    "a: [unclosed",
    "a: b: c",
    "a: *undefined",
    "a: 1\n--- \nb: 2",
    "\ta: 1",
    "a: x\n  b: y",
    "naïve: café",
    "emoji: 😀",
    "ключ: значение",
]

PATHS = [
    "Welcome.md",
    "notes/Plan.MD",
    "a/b/c.png",
    "Projects/Board.canvas",
    "x.base",
    ".obsidian/app.json",
    ".opennote/config.json",
    ".opennote/other.json",
    ".trash/x.md",
    "a/.hidden/b.md",
    ".DS_Store",
    "Thumbs.db",
    "folder/desktop.INI",
    "Icon\r",
    "a/.x.md.abc.opennote-tmp",
    "dir.md/file",
    "",
    "/abs.md",
    "a//b.md",
    "a/./b.md",
    "a/../b.md",
    "back\\slash.md",
    "ctrl\x01.md",
    "del\x7f.md",
    "star*.md",
    'quote".md',
    "lt<gt>.md",
    "colon:.md",
    "pipe|.md",
    "q?.md",
    "hash#tag.md",
    "caret^.md",
    "[br].md",
    "hash#dir/x.png",
    "trailing .md",
    "trailing./x.md",
    "space /x.md",
    "CON.md",
    "con.txt",
    "COM1",
    "lpt9.md",
    "COM10.md",
    "aux/x.md",
    "x" * 252 + ".md",
    "x" * 253 + ".md",
    "é" * 127 + ".md",
    "/".join(["d"] * 512) + ".md",
    "Café.md",
    "Cafe\u0301.md",
    "STRASSE.md",
    "Straße.md",
    "ΣΑΣ.md",
    "\u01f0.md",
    "\u0130stanbul.md",
    "\ufb03.md",
    "\uff21.md",
]

EXTRACTION = [
    "[[a]] [[b|B]] [[c#H]] [[d#^blk]] [[#Local]] [[e#H|E]] ![[img.png|300]]",
    "| x | [[t\\|alias]] |",
    "[[ spaced  ]] [[x # h ]] [[y#^ b ]]",
    "[t](a%20b.md) [u](<c d.md>) [v](https://e.org/x) ![w](img/p%C3%A9.png) [](empty.md)",
    "[x](mailto:a@b.c) [y](file.md#Head) [z](%ZZ.md) [q](%e9.md)",
    "#tag #nested/tag #123 #1a #ünï #日本語 x#no #a-b_c #end. (#paren) #tag!",
    "# Heading #tag\n## #inheading",
    "`#code [[nolink]]` ``x ` [[still]] `` [[yes]]",
    "```\n[[fenced]] #fenced\n```\n[[after]]",
    "~~~md\n[[tilde]]\n~~~",
    "    [[indented]] #indented\n\npara [[p]]",
    "para\n    [[continuation]]",
    "- item\n\n      [[code-in-list]]\n- [[list-link]]",
    "> quote\n> ```\n> [[in-quote-fence]]\n> ```\n> [[quote-link]]",
    "<div>\n[[in-html]]\n</div>\n\n[[out]]",
    "<!-- [[comment]] -->[[x]] %%[[obs]] #obs%% #vis",
    "%%\nmulti\n[[obs2]]\n%%\n#after",
    "```\nunclosed [[fence]]",
    "text\r\n```\r\n[[crlf-fence]]\r\n```\r\n[[crlf-out]] #crlf",
    "😀 [[emoji-before]] `😀😀` [[after-code]] #😀tag",
    "https://x.org/#frag #real",
    "\u00a0#nbsp \u3000#ideo \u2028#ls",
    "[[a]][[b]]![[c]]",
    "![[x.pdf#page=3]] [[a/b/c]] [[../up]]",
    "[[unclosed [[ok]]",
]


def _plain_link(link: Any) -> dict[str, Any]:
    return dataclasses.asdict(link)


def _json_safe(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_json_safe(v) for v in value.values())
    if isinstance(value, list):
        return all(_json_safe(v) for v in value)
    return value is None or isinstance(value, str | int | bool)


def frontmatter_cases() -> list[dict[str, Any]]:
    out = []
    for yaml in FRONTMATTER:
        props, error = read_properties(parse_note(f"---\n{yaml}\n---\nBody\n".encode()))
        assert _json_safe(props), f"not JSON-safe, leave it out: {yaml!r}"
        out.append({"yaml": yaml, "frontmatter": props, "frontmatter_error": error})
    return out


def path_cases() -> list[dict[str, Any]]:
    return [
        {
            "path": p,
            "normalized": normalize(p),
            "casefold_key": casefold_key(p),
            "kind": classify(p),
            "violations_note": [dataclasses.asdict(v) for v in validate(p, note=True)],
            "violations_attachment": [dataclasses.asdict(v) for v in validate(p, note=False)],
        }
        for p in PATHS
    ]


def extraction_cases() -> list[dict[str, Any]]:
    out = []
    for body in EXTRACTION:
        result = extract(parse_note(body.encode()))
        out.append(
            {
                "body": body,
                "links": [_plain_link(link) for link in result.links],
                "tags": result.tags,
                "external_urls": result.external_urls,
            }
        )
    return out


def render() -> dict[str, str]:
    """File name to the exact text that is committed."""
    files = {
        "frontmatter.json": frontmatter_cases(),
        "paths.json": path_cases(),
        "extraction.json": extraction_cases(),
    }
    return {
        name: json.dumps(cases, ensure_ascii=False, indent=1) + "\n"
        for name, cases in files.items()
    }


if __name__ == "__main__":
    PARITY.mkdir(exist_ok=True)
    for name, text in render().items():
        (PARITY / name).write_text(text, encoding="utf-8")
