"""Obsidian-compatible link resolution (storage contract §2.5)."""

from app.notes.extract import Link
from app.notes.links import resolve

PATHS = [
    "Plan.md",
    "Projects/Plan.md",
    "Projects/Deep/Plan.md",
    "Archive/Old/Plan.md",
    "Projects/Spec.md",
    "img/photo.png",
    "Café.md",
]


def _l(target: str, *, markdown: bool = False) -> Link:
    return Link(target, None, None, None, embed=False, markdown=markdown)


def test_ambiguous_name_prefers_same_folder_then_shortest():
    assert resolve(_l("Plan"), "Projects/Spec.md", PATHS) == "Projects/Plan.md"
    assert resolve(_l("Plan"), "Archive/Note.md", PATHS) == "Plan.md"
    assert resolve(_l("Plan"), "Archive/Old/Note.md", PATHS) == "Archive/Old/Plan.md"


def test_path_with_slash_resolves_from_root_then_relative():
    assert resolve(_l("Projects/Deep/Plan"), "x.md", PATHS) == "Projects/Deep/Plan.md"
    assert resolve(_l("Deep/Plan"), "Projects/Spec.md", PATHS) == "Projects/Deep/Plan.md"


def test_extension_kept_for_attachments_and_case_and_nfc_ignored():
    assert resolve(_l("PHOTO.png"), "x.md", PATHS) == "img/photo.png"
    assert resolve(_l("café"), "x.md", PATHS) == "Café.md"


def test_markdown_relative_link():
    assert resolve(_l("../Plan.md", markdown=True), "Projects/Spec.md", PATHS) == "Plan.md"


def test_same_note_heading_link_resolves_to_itself():
    assert resolve(_l(""), "Projects/Spec.md", PATHS) == "Projects/Spec.md"


def test_unresolved_link_returns_none():
    assert resolve(_l("Missing"), "x.md", PATHS) is None
    assert resolve(_l("../../outside.md", markdown=True), "Projects/Spec.md", PATHS) is None
