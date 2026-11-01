"""Frontmatter properties: reading, and round-trip editing (storage contract §2.2).

Editing never re-dumps the whole block. Each changed top-level key is rendered on its own
and spliced over that key's lines, so the other keys keep their quoting, comments, order
and flow style byte for byte.
"""

import datetime as dt
import io
import re
from collections.abc import Mapping
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from app.notes.document import NoteDocument, replace_span, with_newlines

Properties = dict[str, Any]
DELETE: Any = object()
EDITABLE_KEYS = frozenset({"tags", "aliases", "id", "opennote"})
_LIST_KEYS = ("tags", "aliases")
_BLOCK_ITEM = re.compile(r"^( *)- ", re.MULTILINE)


class FrontmatterInvalid(Exception):
    """The frontmatter is not a valid YAML mapping; the body stays editable."""


class PropertyNotEditable(Exception):
    """User edits may only change tags, aliases, id and the opennote namespace."""


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    return yaml


def _load(doc: NoteDocument) -> CommentedMap | None:
    """The frontmatter mapping (None when there is no frontmatter); FrontmatterInvalid when
    it is not a YAML mapping."""
    if doc.text is None or doc.frontmatter is None:
        return None
    try:
        data = _yaml().load(doc.text[doc.frontmatter])
    except YAMLError:
        raise FrontmatterInvalid("frontmatter is not valid YAML") from None
    if data is None:
        return CommentedMap()
    if not isinstance(data, CommentedMap):
        raise FrontmatterInvalid("frontmatter is not a mapping")
    return data


def _plain(value: Any) -> Any:
    """JSON-safe copy: mappings to dicts, sequences to lists, dates to ISO strings."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def read_properties(doc: NoteDocument) -> tuple[Properties | None, bool]:
    """(properties, frontmatter_error). `tags` and `aliases` are always lists; the legacy
    comma-separated string form is split."""
    try:
        data = _load(doc)
    except FrontmatterInvalid:
        return None, True
    if data is None:
        return None, False
    props: Properties = _plain(data)
    for key in _LIST_KEYS:
        if isinstance(props.get(key), str):
            props[key] = [p.strip() for p in props[key].split(",") if p.strip()]
    return props, False


def edit_properties(doc: NoteDocument, changes: Mapping[str, Any]) -> bytes:
    """A user's metadata edit: only `tags`, `aliases`, `id` and `opennote` (merged key by
    key, `DELETE` removes a sub-key) may change."""
    if bad := sorted(set(changes) - EDITABLE_KEYS):
        raise PropertyNotEditable(f"not editable: {', '.join(bad)}")
    return splice_keys(doc, changes)


def splice_keys(doc: NoteDocument, changes: Mapping[str, Any]) -> bytes:
    """Set or `DELETE` any top-level keys, splicing each over its own lines. The server
    merge calls this directly; user edits go through `edit_properties`."""
    if doc.text is None:
        return replace_span(doc, doc.body, "")  # raises ReadOnlyNote
    data = _load(doc)
    if data is None:
        new = {k: v for k, v in changes.items() if v is not DELETE}
        if not new:
            return doc.raw
        block = "---\n" + "".join(_render(k, v, None, "") for k, v in new.items()) + "---\n"
        return replace_span(doc, slice(0, 0), with_newlines(block, doc.newline))
    span = doc.frontmatter
    if span is None:  # _load returned a mapping, so there is a block; satisfies mypy
        raise FrontmatterInvalid("frontmatter span missing")
    yaml_text = doc.text[span]
    lines = yaml_text.splitlines(keepends=True)
    keys = list(data.keys())
    # Work bottom-up so earlier line numbers stay valid; appended keys go after the last.
    replacements: list[tuple[int, int, str]] = []
    appended: list[str] = []
    for key, value in changes.items():
        if key == "opennote" and isinstance(value, Mapping) and value is not DELETE:
            value = _merge_namespace(data.get("opennote"), value)
        if key in data:
            start, end = _key_lines(data, keys, key, lines)
            text = "" if value is DELETE else _render(key, value, data[key], yaml_text)
            replacements.append((start, end, text))
        elif value is not DELETE:
            appended.append(_render(key, value, None, yaml_text))
    for start, end, text in sorted(replacements, reverse=True):
        lines[start:end] = [text]
    new_yaml = "".join(lines)
    if appended:
        if new_yaml and not new_yaml.endswith("\n"):
            new_yaml += "\n"
        new_yaml += "".join(appended)
    if new_yaml == yaml_text:
        return doc.raw
    return replace_span(doc, span, with_newlines(new_yaml, doc.newline))


def _merge_namespace(current: Any, changes: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current) if isinstance(current, Mapping) else {}
    for key, value in changes.items():
        if value is DELETE:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _key_lines(data: CommentedMap, keys: list[Any], key: str, lines: list[str]) -> tuple[int, int]:
    """The line range [start, end) of top-level `key`: its own line up to the next key,
    leaving out column-0 comments and blank lines in between (they belong to the block)."""
    index = keys.index(key)
    start = data.lc.key(key)[0]
    end = data.lc.key(keys[index + 1])[0] if index + 1 < len(keys) else len(lines)
    while end > start + 1 and (lines[end - 1].startswith("#") or not lines[end - 1].strip()):
        end -= 1
    return start, end


def _render(key: str, value: Any, old: Any, yaml_text: str) -> str:
    """`key: value` as YAML text ending in a newline, in the block's list style, keeping
    flow style when the old value was a flow sequence or mapping."""
    if isinstance(value, list):
        seq = CommentedSeq(value)
        if getattr(old, "fa", None) is not None and old.fa.flow_style():
            seq.fa.set_flow_style()
        value = seq
    elif isinstance(value, Mapping):
        mapping = CommentedMap(value)
        if getattr(old, "fa", None) is not None and old.fa.flow_style():
            mapping.fa.set_flow_style()
        value = mapping
    yaml = _yaml()
    item = _BLOCK_ITEM.search(yaml_text)
    offset = len(item.group(1)) if item else 0
    yaml.indent(mapping=2, sequence=offset + 2, offset=offset)
    yaml.width = 4096
    out = io.StringIO()
    yaml.dump(CommentedMap([(key, value)]), out)
    return out.getvalue()
