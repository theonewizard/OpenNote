"""Tasks plugin metadata, recurrence rules and completing a recurring task (P6-02)."""

import datetime as dt

import pytest

from app.notes.document import parse_note
from app.tasks.parse import StaleTask, complete, extract_tasks
from app.tasks.recurrence import advance, metadata, next_dates, parse_rule

D = dt.date


def test_metadata_reads_dates_priority_and_rule():
    meta = metadata("Pay ⏫ 🔁 every week 🛫 2026-11-01 ⏳ 2026-11-10 📅 2026-11-12 ✅ 2026-11-13")
    assert meta.dates == {
        "start": D(2026, 11, 1),
        "scheduled": D(2026, 11, 10),
        "due": D(2026, 11, 12),
        "done": D(2026, 11, 13),
    }
    assert meta.priority == "high"
    assert meta.recurrence is not None and meta.recurrence.text == "every week"


def test_metadata_ignores_impossible_dates_and_plain_text():
    assert metadata("call 📅 2026-02-30").dates == {}
    assert metadata("nothing here") == metadata("")


@pytest.mark.parametrize(
    ("rule", "interval", "unit", "weekdays", "when_done"),
    [
        ("every day", 1, "day", (), False),
        ("every 3 days", 3, "day", (), False),
        ("every 2 weeks", 2, "week", (), False),
        ("Every Month when done", 1, "month", (), True),
        ("every year", 1, "year", (), False),
        ("every weekday", 1, "week", (0, 1, 2, 3, 4), False),
        ("every monday", 1, "week", (0,), False),
        ("every week on Monday, Friday", 1, "week", (0, 4), False),
        ("every 2 weeks on tuesday and thursday", 2, "week", (1, 3), False),
    ],
)
def test_supported_rules(rule, interval, unit, weekdays, when_done):
    parsed = parse_rule(rule)
    assert parsed.supported
    assert (parsed.interval, parsed.unit, parsed.weekdays, parsed.when_done) == (
        interval,
        unit,
        weekdays,
        when_done,
    )


@pytest.mark.parametrize(
    "rule", ["every month on the 3rd", "every 0 days", "every blursday", "daily", ""]
)
def test_unsupported_rules_are_kept_but_not_acted_on(rule):
    assert not parse_rule(rule).supported
    meta = metadata(f"x 🔁 {rule} 📅 2026-01-01")
    assert next_dates(meta, D(2026, 1, 5)) is None


def test_advance():
    assert advance(parse_rule("every month"), D(2026, 1, 31)) == D(2026, 2, 28)
    assert advance(parse_rule("every year"), D(2028, 2, 29)) == D(2029, 2, 28)
    assert advance(parse_rule("every 2 weeks"), D(2026, 11, 14)) == D(2026, 11, 28)
    assert advance(parse_rule("every weekday"), D(2026, 11, 13)) == D(2026, 11, 16)  # Fri->Mon
    biweekly = parse_rule("every 2 weeks on monday, friday")
    got, day = [], D(2026, 11, 9)  # a Monday
    for _ in range(4):
        day = advance(biweekly, day)
        got.append(day)
    assert got == [D(2026, 11, 13), D(2026, 11, 23), D(2026, 11, 27), D(2026, 12, 7)]


def test_next_dates_moves_every_date_by_the_same_step():
    meta = metadata("x 🔁 every week ⏳ 2026-11-10 📅 2026-11-12 ✅ 2026-11-01")
    assert next_dates(meta, D(2026, 12, 1)) == {
        "scheduled": D(2026, 11, 17),
        "due": D(2026, 11, 19),
    }
    when_done = metadata("x 🔁 every week when done 📅 2026-11-12")
    assert next_dates(when_done, D(2026, 12, 1)) == {"due": D(2026, 12, 8)}
    assert next_dates(metadata("x 🔁 every day"), D(2026, 1, 1)) == {}
    assert next_dates(metadata("x 📅 2026-11-12"), D(2026, 1, 1)) is None


def _complete(text: str) -> bytes:
    doc = parse_note(text.encode())
    return complete(doc, extract_tasks(doc)[0], D(2026, 11, 14))


def test_completing_a_plain_task_changes_one_character():
    assert _complete("- [ ] a 📅 2026-11-12\n") == "- [x] a 📅 2026-11-12\n".encode()
    assert _complete("- [x] a 🔁 every day 📅 2026-11-12\n") == (
        "- [ ] a 🔁 every day 📅 2026-11-12\n".encode()  # unchecking never recurs
    )


def test_completing_a_recurring_task_adds_the_next_one_above():
    note = "# Bills\r\n  - [ ] Rent 🔁 every month 📅 2026-01-31 ^rent\r\ntail"
    assert (
        _complete(note)
        == (
            "# Bills\r\n"
            "  - [ ] Rent 🔁 every month 📅 2026-02-28\r\n"
            "  - [x] Rent 🔁 every month 📅 2026-01-31 ✅ 2026-11-14 ^rent\r\n"
            "tail"
        ).encode()
    )


def test_an_old_done_date_is_replaced():
    note = "- [/] Water ✅ 2026-01-01 🔁 every 3 days ⏳ 2026-11-14\n"
    doc = parse_note(note.encode())
    task = extract_tasks(doc)[0]
    assert task.done  # status `/` counts as done: completing it is unchecking
    open_note = note.replace("[/]", "[ ]")
    assert (
        _complete(open_note)
        == (
            "- [ ] Water 🔁 every 3 days ⏳ 2026-11-17\n"
            "- [x] Water 🔁 every 3 days ⏳ 2026-11-14 ✅ 2026-11-14\n"
        ).encode()
    )


def test_complete_refuses_a_stale_task():
    doc = parse_note("- [ ] a 🔁 every day 📅 2026-11-12\n".encode())
    task = extract_tasks(doc)[0]
    other = parse_note("- [x] a 🔁 every day 📅 2026-11-12\n".encode())
    with pytest.raises(StaleTask):
        complete(other, task, D(2026, 11, 14))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call (@2026-11-20 09:30)", dt.datetime(2026, 11, 20, 9, 30)),
        ("call (@2026-11-20)", dt.datetime(2026, 11, 20, 9, 0)),  # the plugin's default time
        ("call ⏰ 2026-11-20 7:05", dt.datetime(2026, 11, 20, 7, 5)),
        ("call (@2026-02-30)", None),
        ("call (@2026-11-20 25:00)", None),
        ("mail me @2026-11-20", None),
    ],
)
def test_reminders(text, expected):
    assert metadata(text).reminder == expected


def test_a_reminder_ends_the_rule_and_moves_with_the_dates():
    note = "- [ ] call 🔁 every week (@2026-11-12 10:00) 📅 2026-11-13\n"
    assert metadata(note).recurrence.text == "every week"
    assert (
        _complete(note)
        == (
            "- [ ] call 🔁 every week (@2026-11-19 10:00) 📅 2026-11-20\n"
            "- [x] call 🔁 every week (@2026-11-12 10:00) 📅 2026-11-13 ✅ 2026-11-14\n"
        ).encode()
    )
