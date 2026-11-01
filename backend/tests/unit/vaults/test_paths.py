"""Path rules (storage contract §1.1, §3): classification, NFC, validation."""

import pytest

from app.vaults.paths import casefold_key, classify, normalize, validate


@pytest.mark.parametrize(
    "path",
    [
        "../x.md",
        "a/../../x.md",
        "/etc/passwd",
        "a\\b.md",
        "a//b.md",
        "a/./b.md",
        "con.md",
        "a/LPT1.png",
        "a /b.md",
        "a/b.",
        "x\x00.md",
        "x\x1f.md",
        ".hidden.md",
        "a/.git/x",
        "a:b.md",
        "",
    ],
)
def test_traversal_and_bad_names_rejected(path):
    assert validate(path, note=True)


def test_link_chars_only_rejected_in_notes():
    assert {v.code for v in validate("a#b.md", note=True)} == {"link_char"}
    assert validate("a#b.png", note=False) == []


def test_good_paths_accepted():
    assert validate("Work/Projects/Plan 2026.md", note=True) == []
    assert validate("Café/naïve.md", note=True) == []


def test_segment_and_path_length_limits():
    assert {v.code for v in validate("é" * 128 + ".md", note=True)} == {"segment_too_long"}
    long_path = "/".join(["a" * 200] * 6)
    assert "path_too_long" in {v.code for v in validate(long_path, note=False)}


def test_violation_names_the_segment():
    (violation,) = validate("ok/con.md", note=True)
    assert violation.code == "reserved_name" and violation.segment == "con.md"


def test_normalize_is_nfc_only():
    assert normalize("Café/x.md") == "Café/x.md"
    assert normalize("A/B.md") == "A/B.md"


def test_casefold_key_folds_case_and_unicode_form():
    assert casefold_key("CAFÉ.md") == casefold_key("café.MD")


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("Notes/a.md", "note"),
        ("Notes/a.MD", "note"),
        ("img/x.png", "attachment"),
        ("board.canvas", "attachment"),
        ("db.base", "attachment"),
        (".opennote/config.json", "config"),
        (".obsidian/app.json", "obsidian_config"),
        (".trash/old.md", "ignored"),
        ("a/.DS_Store", "ignored"),
        ("a/Thumbs.db", "ignored"),
        ("desktop.ini", "ignored"),
        ("Icon\r", "ignored"),
        ("a/.x.md.abc123.opennote-tmp", "temp"),
    ],
)
def test_classify(path, kind):
    assert classify(path) == kind
