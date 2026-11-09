"""Template rendering, compatible with Obsidian's core Templates plugin (P6-05 parse part).

A template is an ordinary note in the vault's `templates_folder` (storage contract §1.2).
`render` replaces `{{title}}`, `{{date}}`, `{{time}}`, `{{date:FORMAT}}` and `{{time:FORMAT}}`
(Moment.js format tokens) and leaves every other byte alone, frontmatter included, so the
result keeps the template's line endings and never gains `id`, `created` or `modified`.
Creating the note from it (with the `id` OpenNote-created notes get, §2.4) is the note write
path's job (P2-04), not this module's.
"""

import re
from datetime import datetime

DATE_FORMAT = "YYYY-MM-DD"  # Obsidian's defaults
TIME_FORMAT = "HH:mm"

_VARIABLE = re.compile(r"\{\{\s*(title|date|time)\s*(?::([^}]*))?\}\}", re.IGNORECASE)
_TOKEN = re.compile(
    r"\[([^\]]*)\]|YYYY|YY|Q|MMMM|MMM|MM|M|DDDD|DDD|Do|DD|D|dddd|ddd|dd|d|E|"
    r"HH|H|hh|h|kk|k|mm|m|ss|s|A|a|GGGG|WW|W|X|ZZ|Z"
)
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _offset(when: datetime, sep: str) -> str:
    delta = when.utcoffset()
    if delta is None:
        return ""
    minutes = int(delta.total_seconds()) // 60
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}{sep}{abs(minutes) % 60:02d}"


def format_moment(when: datetime, fmt: str) -> str:
    """`when` formatted with a Moment.js format string (English names; the subset Obsidian
    users put in templates and daily-note names). Unknown letters are kept as they are, and
    `[text]` is literal, as in Moment."""
    hour12 = when.hour % 12 or 12
    weekday = when.isoweekday() % 7  # Moment's d: Sunday is 0
    iso_year, iso_week, _ = when.isocalendar()
    values = {
        "YYYY": f"{when.year:04d}",
        "YY": f"{when.year % 100:02d}",
        "Q": str((when.month - 1) // 3 + 1),
        "MMMM": _MONTHS[when.month - 1],
        "MMM": _MONTHS[when.month - 1][:3],
        "MM": f"{when.month:02d}",
        "M": str(when.month),
        "DDDD": f"{when.timetuple().tm_yday:03d}",
        "DDD": str(when.timetuple().tm_yday),
        "Do": _ordinal(when.day),
        "DD": f"{when.day:02d}",
        "D": str(when.day),
        "dddd": _DAYS[weekday],
        "ddd": _DAYS[weekday][:3],
        "dd": _DAYS[weekday][:2],
        "d": str(weekday),
        "E": str(when.isoweekday()),
        "HH": f"{when.hour:02d}",
        "H": str(when.hour),
        "hh": f"{hour12:02d}",
        "h": str(hour12),
        "kk": f"{when.hour or 24:02d}",
        "k": str(when.hour or 24),
        "mm": f"{when.minute:02d}",
        "m": str(when.minute),
        "ss": f"{when.second:02d}",
        "s": str(when.second),
        "A": "AM" if when.hour < 12 else "PM",
        "a": "am" if when.hour < 12 else "pm",
        "GGGG": f"{iso_year:04d}",
        "WW": f"{iso_week:02d}",
        "W": str(iso_week),
        "X": str(int(when.timestamp())),
        "ZZ": _offset(when, ""),
        "Z": _offset(when, ":"),
    }
    return _TOKEN.sub(lambda m: m.group(1) if m.group(1) is not None else values[m[0]], fmt)


def render(
    template: str,
    *,
    title: str,
    now: datetime,
    date_format: str = DATE_FORMAT,
    time_format: str = TIME_FORMAT,
) -> str:
    """`template` with its variables filled in; `now` is the caller's local time."""

    def fill(m: re.Match[str]) -> str:
        name, fmt = m.group(1).lower(), m.group(2)
        if name == "title":
            return m[0] if fmt is not None else title
        default = date_format if name == "date" else time_format
        return format_moment(now, fmt.strip() if fmt and fmt.strip() else default)

    return _VARIABLE.sub(fill, template)
