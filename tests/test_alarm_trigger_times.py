"""Resolving VALARM triggers into absolute times (#651)."""

import datetime

import pytest

from ical.alarm import Alarm, Related
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event

UTC = datetime.timezone.utc
START = datetime.datetime(2025, 7, 15, 14, 0, tzinfo=UTC)
END = datetime.datetime(2025, 7, 15, 15, 0, tzinfo=UTC)


def _alarm(**kwargs) -> Alarm:
    return Alarm(action="DISPLAY", description="x", **kwargs)


def test_relative_to_start() -> None:
    """The common case: fire before the event begins."""
    alarm = _alarm(trigger=datetime.timedelta(minutes=-15))

    assert alarm.trigger_times(START, END) == [
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=UTC)
    ]


def test_relative_to_end() -> None:
    """RELATED=END measures from DTEND, not DTSTART."""
    alarm = _alarm(trigger=datetime.timedelta(minutes=-5), trigger_related=Related.END)

    assert alarm.trigger_times(START, END) == [
        datetime.datetime(2025, 7, 15, 14, 55, tzinfo=UTC)
    ]


def test_relative_to_end_without_an_end() -> None:
    """Silently anchoring to the start would move the alarm, not fail."""
    alarm = _alarm(trigger=datetime.timedelta(minutes=-5), trigger_related=Related.END)

    with pytest.raises(ValueError, match="relative to the end"):
        alarm.trigger_times(START)


def test_absolute_trigger_is_returned_as_is() -> None:
    """An absolute trigger ignores the event entirely."""
    when = datetime.datetime(2025, 7, 15, 12, 0, tzinfo=UTC)
    alarm = _alarm(trigger=when)

    assert alarm.trigger_times(START, END) == [when]


def test_absolute_trigger_ignores_related() -> None:
    """RELATED has no meaning for an absolute trigger."""
    when = datetime.datetime(2025, 7, 15, 12, 0, tzinfo=UTC)
    alarm = _alarm(trigger=when, trigger_related=Related.END)

    assert alarm.trigger_times(START, END) == [when]


def test_repeat_and_duration() -> None:
    """REPEAT is the number of *additional* firings, per rfc5545."""
    alarm = _alarm(
        trigger=datetime.timedelta(minutes=-15),
        repeat=3,
        duration=datetime.timedelta(minutes=5),
    )

    assert alarm.trigger_times(START, END) == [
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=UTC),
        datetime.datetime(2025, 7, 15, 13, 50, tzinfo=UTC),
        datetime.datetime(2025, 7, 15, 13, 55, tzinfo=UTC),
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=UTC),
    ]


def test_all_day_event_resolves_against_midnight() -> None:
    """A date has no time of day, so it becomes local midnight."""
    alarm = _alarm(trigger=datetime.timedelta(hours=-1))

    (time,) = alarm.trigger_times(datetime.date(2025, 7, 15))

    assert time.tzinfo is not None
    assert (time + datetime.timedelta(hours=1)).timetuple()[:5] == (2025, 7, 15, 0, 0)


def test_event_resolves_every_alarm_in_order() -> None:
    """The convenience API sorts across alarms, not just within one."""
    event = Event(
        summary="Dentist",
        start=START,
        end=END,
        alarm=[
            _alarm(trigger=datetime.timedelta(minutes=-15)),
            _alarm(trigger=datetime.timedelta(hours=-2)),
        ],
    )

    triggers = event.alarm_trigger_times()

    assert [trigger.time for trigger in triggers] == [
        datetime.datetime(2025, 7, 15, 12, 0, tzinfo=UTC),
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=UTC),
    ]
    assert all(trigger.alarm in event.alarm for trigger in triggers)


def test_event_without_alarms() -> None:
    event = Event(summary="Dentist", start=START, end=END)

    assert event.alarm_trigger_times() == []


def test_an_event_always_has_an_end_to_resolve_against() -> None:
    """`Event.end` falls back to the start, so RELATED=END cannot fail here."""
    event = Event(
        summary="Dentist",
        start=START,
        alarm=[
            _alarm(trigger=datetime.timedelta(minutes=-5), trigger_related=Related.END)
        ],
    )

    assert event.alarm_trigger_times()[0].time == datetime.datetime(
        2025, 7, 15, 13, 55, tzinfo=UTC
    )


def test_a_naive_absolute_trigger_stays_comparable() -> None:
    """Mixing a naive absolute trigger with a relative one broke sorting."""
    event = Event(
        summary="Dentist",
        start=START,
        end=END,
        alarm=[
            _alarm(trigger=datetime.datetime(2025, 7, 15, 12, 0)),
            _alarm(trigger=datetime.timedelta(hours=-2)),
        ],
    )

    triggers = event.alarm_trigger_times()

    assert len(triggers) == 2
    assert all(trigger.time.tzinfo is not None for trigger in triggers)


def test_a_negative_duration_still_comes_back_sorted() -> None:
    """Malformed but readable; the docstring promises chronological order."""
    alarm = _alarm(
        trigger=datetime.timedelta(minutes=-15),
        repeat=2,
        duration=datetime.timedelta(minutes=-5),
    )

    times = alarm.trigger_times(START, END)

    assert times == sorted(times)


ICS = """BEGIN:VCALENDAR
PRODID:-//example//example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
DTSTART:20250715T140000Z
DTEND:20250715T150000Z
SUMMARY:Dentist
BEGIN:VALARM
TRIGGER;RELATED=END:-PT5M
ACTION:DISPLAY
DESCRIPTION:leaving
END:VALARM
END:VEVENT
END:VCALENDAR
"""


def test_related_is_read_from_the_parameter() -> None:
    event = IcsCalendarStream.calendar_from_ics(ICS).events[0]

    assert event.alarm[0].trigger_related == Related.END
    assert event.alarm_trigger_times()[0].time == datetime.datetime(
        2025, 7, 15, 14, 55, tzinfo=UTC
    )


def test_related_survives_a_round_trip() -> None:
    """Dropping the parameter silently moves the alarm to the start."""
    calendar = IcsCalendarStream.calendar_from_ics(ICS)

    ics = IcsCalendarStream.calendar_to_ics(calendar)

    assert "TRIGGER;RELATED=END:-PT5M" in ics
    assert "TRIGGER_RELATED" not in ics


def test_the_default_is_not_written_out() -> None:
    """RELATED=START is the default; emitting it would churn every file."""
    calendar = IcsCalendarStream.calendar_from_ics(
        ICS.replace("TRIGGER;RELATED=END:-PT5M", "TRIGGER:-PT5M")
    )

    ics = IcsCalendarStream.calendar_to_ics(calendar)

    assert "TRIGGER:-PT5M" in ics
    assert "RELATED" not in ics


def test_an_unknown_related_value_is_ignored_not_fatal() -> None:
    """This parameter was unread before; rejecting the file would be stricter."""
    calendar = IcsCalendarStream.calendar_from_ics(
        ICS.replace("RELATED=END", "RELATED=MIDDLE")
    )

    alarm = calendar.events[0].alarm[0]

    assert alarm.trigger_related == Related.START
    assert "RELATED" not in IcsCalendarStream.calendar_to_ics(calendar)


RECURRING = ICS.replace("SUMMARY:Dentist", "RRULE:FREQ=DAILY;COUNT=3\nSUMMARY:Dentist")


def test_each_occurrence_resolves_its_own_alarm() -> None:
    """The point of the API: a recurring event alarms on every occurrence."""
    calendar = IcsCalendarStream.calendar_from_ics(RECURRING)

    times = [
        trigger.time
        for event in calendar.timeline.included(
            datetime.datetime(2025, 7, 14, tzinfo=UTC),
            datetime.datetime(2025, 7, 20, tzinfo=UTC),
        )
        for trigger in event.alarm_trigger_times()
    ]

    assert times == [
        datetime.datetime(2025, 7, 15, 14, 55, tzinfo=UTC),
        datetime.datetime(2025, 7, 16, 14, 55, tzinfo=UTC),
        datetime.datetime(2025, 7, 17, 14, 55, tzinfo=UTC),
    ]


TODO_ICS = """BEGIN:VCALENDAR
PRODID:-//example//example//EN
VERSION:2.0
BEGIN:VTODO
DTSTAMP:20250715T100000Z
UID:2
SUMMARY:Taxes
DUE:20250716T090000Z
BEGIN:VALARM
TRIGGER;RELATED=END:-PT30M
ACTION:DISPLAY
DESCRIPTION:d
END:VALARM
END:VTODO
END:VCALENDAR
"""


def test_a_todo_alarm_resolves_and_round_trips() -> None:
    """VTODO has no convenience method, but the primitive and ics both work."""
    calendar = IcsCalendarStream.calendar_from_ics(TODO_ICS)
    todo = calendar.todos[0]
    due = todo.due
    assert due is not None

    assert todo.alarms[0].trigger_times(due, due) == [
        datetime.datetime(2025, 7, 16, 8, 30, tzinfo=UTC)
    ]
    assert "TRIGGER;RELATED=END:-PT30M" in IcsCalendarStream.calendar_to_ics(calendar)
