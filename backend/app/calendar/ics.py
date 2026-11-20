"""iCalendar (RFC 5545) for dated tasks (P6-03).

A task with a reminder becomes a 15-minute event at the reminder's local time (floating,
no zone: the note owner's wall clock) with a display alarm; a task with only a due date
becomes an all-day event that day. The summary is the task text without the Tasks and
Reminder plugin signifiers."""

import datetime as dt
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.tasks.recurrence import DATE_SIGNS, PRIORITIES, RECUR_SIGN

_SIGNIFIERS = re.compile(
    "|".join(
        [
            f"[{''.join(DATE_SIGNS)}]\\ufe0f?[ \\t]*\\d{{4}}-\\d{{2}}-\\d{{2}}",
            f"[{''.join(PRIORITIES)}]\\ufe0f?",
            f"{RECUR_SIGN}\\ufe0f?[^{''.join([*DATE_SIGNS, *PRIORITIES])}(⏰]*",
            r"\(@\d{4}-\d{2}-\d{2}(?:[ \t]+\d{1,2}:\d{2})?\)",
            r"⏰\ufe0f?[ \t]*\d{4}-\d{2}-\d{2}(?:[ \t]+\d{1,2}:\d{2})?",
            r"[ \t]\^[A-Za-z0-9-]+$",
        ]
    )
)


@dataclass(frozen=True)
class FeedTask:
    file_id: uuid.UUID
    ordinal: int
    text: str
    path: str
    due: dt.date | None
    remind_at: dt.datetime | None


def summary(text: str) -> str:
    return re.sub(r"\s+", " ", _SIGNIFIERS.sub(" ", text)).strip() or "Task"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", r"\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines of at most 75 octets, continued with a leading space (RFC 5545 §3.1)."""
    out: list[str] = []
    current = b""
    for char in line:
        encoded = char.encode()
        if len(current) + len(encoded) > (75 if not out else 74):
            out.append(current.decode())
            current = b""
        current += encoded
    out.append(current.decode())
    return "\r\n ".join(out)


def calendar(name: str, tasks: Iterable[FeedTask], now: dt.datetime) -> str:
    stamp = now.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenNote//Tasks//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for task in tasks:
        event = [
            "BEGIN:VEVENT",
            f"UID:{task.file_id}-{task.ordinal}@opennote",
            f"DTSTAMP:{stamp}",
            f"SUMMARY:{_escape(summary(task.text))}",
            f"DESCRIPTION:{_escape(task.path)}",
        ]
        if task.remind_at is not None:
            event += [
                f"DTSTART:{task.remind_at.strftime('%Y%m%dT%H%M%S')}",
                "DURATION:PT15M",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape(summary(task.text))}",
                "TRIGGER:PT0S",
                "END:VALARM",
            ]
        elif task.due is not None:
            event += [
                f"DTSTART;VALUE=DATE:{task.due.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(task.due + dt.timedelta(days=1)).strftime('%Y%m%d')}",
            ]
        else:
            continue
        lines += [*event, "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(_fold(line) + "\r\n" for line in lines)
