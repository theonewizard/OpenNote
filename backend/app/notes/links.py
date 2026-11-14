"""Obsidian-compatible link resolution (storage contract §2.5)."""

import posixpath
from collections.abc import Sequence

from app.notes.extract import Link
from app.vaults.paths import casefold_key


def target_key(target: str) -> str:
    """The case-folded file name every path `target` can resolve to ends in, with or
    without `.md` (an empty target links to its own note)."""
    return casefold_key(posixpath.basename(posixpath.normpath(target))) if target else ""


def name_keys(path: str) -> list[str]:
    """The `target_key`s of the links that can resolve to `path`."""
    leaf = casefold_key(posixpath.basename(path))
    return [leaf, leaf.removesuffix(".md")] if leaf.endswith(".md") else [leaf]


def _candidates(target: str) -> list[str]:
    name = target.rsplit("/", 1)[-1]
    return [target] if "." in name and not name.endswith(".") else [target, target + ".md"]


def resolve(link: Link, from_path: str, paths: Sequence[str]) -> str | None:
    """The vault path `link` points to, or None when unresolved. Comparison is NFC and
    case-insensitive; ambiguous names prefer the linking file's folder, then the shortest
    path, then lexical order. `paths` may be only those whose file name matches the
    target's (`target_key`, with or without `.md`): no other path can be the answer."""
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
