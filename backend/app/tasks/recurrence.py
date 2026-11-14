"""Task metadata and recurrence in the Obsidian Tasks plugin's emoji format (P6-02).

`metadata` reads the signifiers the Tasks plugin writes after a task's text: dates
(📅 due, ⏳ scheduled, 🛫 start, U+2795 created, ✅ done, ❌ cancelled), priority (🔺 ⏫ 🔼 🔽 ⏬)
and a recurrence rule (🔁 every week). `next_dates` gives the next instance of a
recurring task as the Tasks plugin does: every date moves by the same step, measured from
the due date (else scheduled, else start), or from the completion day for `when done`.
Rules outside the supported subset (`supported` False) are kept and never acted on.
"""

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field

DATE_SIGNS = {
    "📅": "due",
    "⏳": "scheduled",
    "🛫": "start",
    "\u2795": "created",  # HEAVY PLUS SIGN
    "✅": "done",
    "❌": "cancelled",
}
PRIORITIES = {"🔺": "highest", "⏫": "high", "🔼": "medium", "🔽": "low", "⏬": "lowest"}
RECUR_SIGN = "🔁"
_SIGNS = "".join([*DATE_SIGNS, *PRIORITIES, RECUR_SIGN])
_DATE = re.compile(f"([{''.join(DATE_SIGNS)}])️?[ \t]*(\\d{{4}}-\\d{{2}}-\\d{{2}})")
_PRIORITY = re.compile(f"[{''.join(PRIORITIES)}]")
_RECUR = re.compile(f"{RECUR_SIGN}️?[ \t]*([^{_SIGNS}]*)")
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_RULE = re.compile(
    r"every(?:\s+(?P<n>\d{1,4}))?\s+(?P<unit>day|week|month|year)s?"
    r"(?:\s+on\s+(?P<on>[a-z, ]+?))?(?P<when_done>\s+when\s+done)?",
)
_WEEKDAY_RULE = re.compile(r"every\s+(?P<days>weekday|[a-z, ]+?)(?P<when_done>\s+when\s+done)?")


@dataclass(frozen=True)
class Rule:
    text: str  # as written, after the 🔁
    supported: bool
    interval: int = 1
    unit: str = "day"  # day, week, month or year
    weekdays: tuple[int, ...] = ()  # Monday 0; for `every weekday` and `every week on ...`
    when_done: bool = False


@dataclass(frozen=True)
class TaskMeta:
    dates: dict[str, dt.date] = field(default_factory=dict)  # DATE_SIGNS values -> date
    priority: str | None = None
    recurrence: Rule | None = None


def _weekdays(words: str) -> tuple[int, ...] | None:
    names = [w for w in re.split(r"[\s,]+|\band\b", words) if w]
    if not names or any(n not in _WEEKDAYS for n in names):
        return None
    return tuple(sorted({_WEEKDAYS.index(n) for n in names}))


def parse_rule(text: str) -> Rule:
    written = text.strip()
    rule = written.lower()
    if m := _RULE.fullmatch(rule):
        days: tuple[int, ...] = ()
        if m["on"]:
            if m["unit"] != "week" or (found := _weekdays(m["on"])) is None:
                return Rule(written, False)
            days = found
        interval = int(m["n"] or 1)
        if interval < 1:
            return Rule(written, False)
        return Rule(written, True, interval, m["unit"], days, bool(m["when_done"]))
    if m := _WEEKDAY_RULE.fullmatch(rule):
        found = (0, 1, 2, 3, 4) if m["days"] == "weekday" else _weekdays(m["days"])
        if found is not None:
            return Rule(written, True, 1, "week", found, bool(m["when_done"]))
    return Rule(written, False)


def metadata(text: str) -> TaskMeta:
    dates: dict[str, dt.date] = {}
    for sign, value in _DATE.findall(text):
        try:
            dates.setdefault(DATE_SIGNS[sign], dt.date.fromisoformat(value))
        except ValueError:  # 2026-02-30: not a date, ignored as the Tasks plugin does
            continue
    priority = PRIORITIES[m[0]] if (m := _PRIORITY.search(text)) else None
    recurrence = parse_rule(m[1]) if (m := _RECUR.search(text)) else None
    return TaskMeta(dates, priority, recurrence)


def _add_months(day: dt.date, months: int) -> dt.date:
    """The same day `months` later, clamped to the month's last day (Jan 31 -> Feb 28)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return day.replace(year=year, month=month, day=min(day.day, last))


def advance(rule: Rule, day: dt.date) -> dt.date:
    """The rule's next date after `day`."""
    if rule.weekdays:  # rrule's weekly BYDAY: only weeks `interval` apart from `day`'s week
        monday = day - dt.timedelta(days=day.weekday())
        step = day + dt.timedelta(days=1)
        while ((step - monday).days // 7) % rule.interval or step.weekday() not in rule.weekdays:
            step += dt.timedelta(days=1)
        return step
    if rule.unit == "day":
        return day + dt.timedelta(days=rule.interval)
    if rule.unit == "week":
        return day + dt.timedelta(weeks=rule.interval)
    return _add_months(day, rule.interval * (12 if rule.unit == "year" else 1))


def next_dates(meta: TaskMeta, today: dt.date) -> dict[str, dt.date] | None:
    """The dates of the next occurrence (due, scheduled and start moved by one step), or
    None when the task does not recur or its rule is not supported."""
    rule = meta.recurrence
    if rule is None or not rule.supported:
        return None
    moving = {k: v for k, v in meta.dates.items() if k in ("due", "scheduled", "start")}
    reference = next((moving[k] for k in ("due", "scheduled", "start") if k in moving), None)
    if reference is None:
        return {}
    base = today if rule.when_done else reference
    shift = advance(rule, base) - reference
    return {k: v + shift for k, v in moving.items()}
