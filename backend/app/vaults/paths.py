"""Vault path rules shared by every client (storage contract §1.1 and §3).

Paths are vault-relative, `/`-separated and compared in Unicode NFC. The rules here are
pure string checks; `fsio` does the filesystem side (containment, no symlinks).
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

FileKind = Literal["note", "attachment", "config", "obsidian_config", "ignored", "temp"]

MAX_SEGMENT_BYTES = 255
MAX_PATH_BYTES = 1024
FORBIDDEN_CHARS = '*"\\/<>:|?'
LINK_CHARS = "#^[]|"
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
OS_CRUFT = frozenset({"thumbs.db", "desktop.ini", "icon\r"})
TEMP_SUFFIX = ".opennote-tmp"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# Served as-is at GET /api/v1/meta/path-rules so every client applies the same rules.
PATH_RULES: dict[str, object] = {
    "separator": "/",
    "unicode_normalization": "NFC",
    "case_insensitive_collisions": True,
    "max_segment_bytes": MAX_SEGMENT_BYTES,
    "max_path_bytes": MAX_PATH_BYTES,
    "forbidden_chars": FORBIDDEN_CHARS,
    "note_forbidden_chars": LINK_CHARS,
    "reserved_names": sorted(RESERVED_NAMES),
    "no_leading_dot": True,
    "no_trailing_space_or_dot": True,
}


@dataclass(frozen=True)
class PathViolation:
    code: str
    segment: str | None = None


def normalize(path: str) -> str:
    """The NFC form of `path`; nothing else changes."""
    return unicodedata.normalize("NFC", path)


def casefold_key(path: str) -> str:
    """The key two paths collide on: NFC, then case-folded."""
    return normalize(path).casefold()


def classify(path: str) -> FileKind:
    """Storage contract §1.1, first match wins."""
    segments = path.split("/")
    name = segments[-1]
    if name.endswith(TEMP_SUFFIX):
        return "temp"
    if path == ".opennote/config.json":
        return "config"
    if segments[0] == ".obsidian":
        return "obsidian_config"
    if any(s.startswith(".") for s in segments) or name.casefold() in OS_CRUFT:
        return "ignored"
    if name.casefold().endswith(".md"):
        return "note"
    return "attachment"


def validate(path: str, *, note: bool) -> list[PathViolation]:
    """The rule violations of `path` (empty when valid). Case-fold collisions need the folder
    listing, so callers check those with `casefold_key`."""
    if not path:
        return [PathViolation("empty_segment")]
    if path.startswith("/"):
        return [PathViolation("absolute")]
    violations: list[PathViolation] = []
    if "\\" in path:
        violations.append(PathViolation("backslash"))
    if len(path.encode()) > MAX_PATH_BYTES:
        violations.append(PathViolation("path_too_long"))
    segments = path.split("/")
    for index, segment in enumerate(segments):
        violations.extend(_segment_violations(segment, note=note and index == len(segments) - 1))
    return violations


def _segment_violations(segment: str, *, note: bool) -> list[PathViolation]:
    def bad(code: str) -> PathViolation:
        return PathViolation(code, segment)

    if segment == "":
        return [bad("empty_segment")]
    if segment in (".", ".."):
        return [bad("dot_segment")]
    found: list[PathViolation] = []
    if _CONTROL.search(segment):
        found.append(bad("control_char"))
    if any(c in FORBIDDEN_CHARS for c in segment.replace("\\", "")):
        found.append(bad("forbidden_char"))
    if note and any(c in LINK_CHARS for c in segment):
        found.append(bad("link_char"))
    if segment.startswith("."):
        found.append(bad("leading_dot"))
    if segment.endswith((" ", ".")):
        found.append(bad("trailing_space_or_dot"))
    if len(segment.encode()) > MAX_SEGMENT_BYTES:
        found.append(bad("segment_too_long"))
    if segment.split(".")[0].upper() in RESERVED_NAMES:
        found.append(bad("reserved_name"))
    return found
