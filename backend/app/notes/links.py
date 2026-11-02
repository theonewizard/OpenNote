"""Obsidian-compatible link resolution (storage contract §2.5)."""

import posixpath
from collections.abc import Sequence

from app.notes.extract import Link
from app.vaults.paths import casefold_key


def _candidates(target: str) -> list[str]:
    name = target.rsplit("/", 1)[-1]
    return [target] if "." in name and not name.endswith(".") else [target, target + ".md"]


def resolve(link: Link, from_path: str, paths: Sequence[str]) -> str | None:
    """The vault path `link` points to, or None when unresolved. Comparison is NFC and
    case-insensitive; ambiguous names prefer the linking file's folder, then the shortest
    path, then lexical order."""
    if not link.target:
        return from_path
    by_key = {casefold_key(p): p for p in paths}
    folder = posixpath.dirname(from_path)
    candidates = _candidates(link.target)
    if "/" in link.target:
        for base in ("", folder):
            for candidate in candidates:
                joined = posixpath.normpath(posixpath.join(base, candidate))
                if (
                    not joined.startswith("../")
                    and joined != ".."
                    and (hit := by_key.get(casefold_key(joined)))
                ):
                    return hit
        return None
    names = {casefold_key(c) for c in candidates}
    matches = [p for p in paths if casefold_key(p.rsplit("/", 1)[-1]) in names]
    if not matches:
        return None
    return min(matches, key=lambda p: (posixpath.dirname(p) != folder, p.count("/"), len(p), p))
