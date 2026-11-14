"""Template rendering compatible with Obsidian's core Templates plugin (P6-05)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.notes.templates import format_moment, render

NOW = datetime(2026, 1, 3, 9, 5, 7, tzinfo=timezone(timedelta(hours=1)))


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("YYYY-MM-DD", "2026-01-03"),
        ("HH:mm:ss", "09:05:07"),
        ("dddd, MMMM Do YYYY", "Saturday, January 3rd 2026"),
        ("ddd D MMM YY", "Sat 3 Jan 26"),
        ("h:mm A / a", "9:05 AM / am"),
        ("GGGG-[W]WW", "2026-W01"),
        ("[Week] W, E, d, DDDD, Q", "Week 1, 6, 6, 003, 1"),
        ("Z ZZ", "+01:00 +0100"),
        ("k kk", "9 09"),
        ("YYYY/[literal YYYY]/x", "2026/literal YYYY/x"),
    ],
)
def test_format_moment(fmt, expected):
    assert format_moment(NOW, fmt) == expected


def test_ordinals_midnight_and_week_belonging_to_last_year():
    assert [format_moment(datetime(2026, 1, d), "Do") for d in (1, 2, 11, 12, 13, 21, 22, 23)] == [
        "1st",
        "2nd",
        "11th",
        "12th",
        "13th",
        "21st",
        "22nd",
        "23rd",
    ]
    assert format_moment(datetime(2026, 1, 1, 0, 30), "h A, kk") == "12 AM, 24"
    assert format_moment(datetime(2027, 1, 1), "GGGG-[W]WW") == "2026-W53"
    assert format_moment(datetime(2026, 1, 1), "Z") == ""  # naive time has no offset
    assert format_moment(datetime(2026, 1, 1, tzinfo=UTC), "X") == "1767225600"


def test_render_fills_variables_and_keeps_every_other_byte():
    template = (
        "---\r\ntags: [daily]\r\ncreated: {{date}}\r\n---\r\n"
        "# {{title}}\r\n{{ DATE:dddd }} at {{time}}, {{time:HH.mm}} {{date:}}\n"
        "{{unknown}} {{title:x}} {date} %%{{title}}%%\n"
    )
    out = render(template, title="Plan", now=NOW)
    assert out == (
        "---\r\ntags: [daily]\r\ncreated: 2026-01-03\r\n---\r\n"
        "# Plan\r\nSaturday at 09:05, 09.05 2026-01-03\n"
        "{{unknown}} {{title:x}} {date} %%Plan%%\n"
    )


def test_render_uses_the_configured_default_formats():
    out = render("{{date}} {{time}}", title="", now=NOW, date_format="D/M", time_format="h a")
    assert out == "3/1 9 am"


def test_render_never_adds_identity_or_timestamps():
    assert render("body\n", title="T", now=NOW) == "body\n"
