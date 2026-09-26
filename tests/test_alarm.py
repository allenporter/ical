"""Tests for Alarm component."""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from ical.alarm import Alarm, Related
from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.exceptions import CalendarParseError


def test_todo() -> None:
    """Test a valid Alarm."""
    alarm = Alarm(action="AUDIO", trigger=datetime.timedelta(minutes=-5))
    assert alarm.action == "AUDIO"
    assert alarm.trigger == datetime.timedelta(minutes=-5)
    assert not alarm.duration
    assert not alarm.repeat


def test_duration_and_repeat() -> None:
    """Test relationship between the duration and repeat fields."""

    alarm = Alarm(
        action="AUDIO",
        trigger=datetime.timedelta(minutes=-5),
        duration=datetime.timedelta(seconds=30),
        repeat=2,
    )
    assert alarm.action
    assert alarm.trigger
    assert alarm.duration
    assert alarm.repeat == 2

    # Duration but no repeat
    with pytest.raises(CalendarParseError):
        Alarm(
            action="AUDIO",
            trigger=datetime.timedelta(minutes=-5),
            duration=datetime.timedelta(seconds=30),
        )

    # Repeat but no duration
    with pytest.raises(CalendarParseError):
        Alarm(action="AUDIO", trigger=datetime.timedelta(minutes=-5), repeat=2)


def test_display_required_fields() -> None:
    """Test required fields for action DISPLAY."""
    with pytest.raises(
        CalendarParseError, match="Description value is required for action DISPLAY"
    ):
        Alarm(action="DISPLAY", trigger=datetime.timedelta(minutes=-5))

    alarm = Alarm(
        action="DISPLAY",
        trigger=datetime.timedelta(minutes=-5),
        description="Notification description",
    )
    assert alarm.action == "DISPLAY"
    assert alarm.description == "Notification description"


def test_empty_display_field() -> None:
    """Test required fields for action DISPLAY."""
    alarm = Alarm(
        action="DISPLAY",
        trigger=datetime.timedelta(minutes=-5),
        description="",
    )
    assert alarm.action == "DISPLAY"
    assert alarm.description == ""


def test_email_required_fields() -> None:
    """Test required fields for action EMAIL."""
    # Missing multiple fields
    with pytest.raises(
        CalendarParseError, match="Description value is required for action EMAIL"
    ):
        Alarm(action="EMAIL", trigger=datetime.timedelta(minutes=-5))

    # Missing summary
    with pytest.raises(CalendarParseError):
        Alarm(
            action="EMAIL",
            trigger=datetime.timedelta(minutes=-5),
            description="Email description",
        )

    # Missing description
    with pytest.raises(CalendarParseError):
        Alarm(
            action="EMAIL",
            trigger=datetime.timedelta(minutes=-5),
            summary="Email summary",
        )

    alarm = Alarm(
        action="DISPLAY",
        trigger=datetime.timedelta(minutes=-5),
        description="Email description",
        summary="Email summary",
    )
    assert alarm.action == "DISPLAY"
    assert alarm.summary == "Email summary"
    assert alarm.description == "Email description"


_UTC = datetime.timezone.utc
_START = datetime.datetime(2025, 7, 15, 14, 0, tzinfo=_UTC)
_END = datetime.datetime(2025, 7, 15, 15, 0, tzinfo=_UTC)

_ICS = """BEGIN:VCALENDAR
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

_TODO_ICS = """BEGIN:VCALENDAR
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


def _display_alarm(**kwargs: Any) -> Alarm:
    """Build the smallest valid DISPLAY alarm."""
    return Alarm(action="DISPLAY", description="x", **kwargs)


def test_trigger_times_relative_to_start() -> None:
    """The common case: fire before the event begins."""
    alarm = _display_alarm(trigger=datetime.timedelta(minutes=-15))

    assert alarm.trigger_times(_START, _END) == [
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=_UTC)
    ]


def test_trigger_times_relative_to_end() -> None:
    """RELATED=END measures from DTEND, not DTSTART."""
    alarm = _display_alarm(
        trigger=datetime.timedelta(minutes=-5), trigger_related=Related.END
    )

    assert alarm.trigger_times(_START, _END) == [
        datetime.datetime(2025, 7, 15, 14, 55, tzinfo=_UTC)
    ]


def test_trigger_times_relative_to_end_without_an_end() -> None:
    """Silently anchoring to the start would move the alarm, not fail."""
    alarm = _display_alarm(
        trigger=datetime.timedelta(minutes=-5), trigger_related=Related.END
    )

    with pytest.raises(ValueError, match="relative to the end"):
        alarm.trigger_times(_START)


def test_absolute_trigger_is_returned_as_is() -> None:
    """An absolute trigger ignores the event entirely."""
    when = datetime.datetime(2025, 7, 15, 12, 0, tzinfo=_UTC)
    alarm = _display_alarm(trigger=when)

    assert alarm.trigger_times(_START, _END) == [when]


def test_absolute_trigger_ignores_related() -> None:
    """RELATED has no meaning for an absolute trigger."""
    when = datetime.datetime(2025, 7, 15, 12, 0, tzinfo=_UTC)
    alarm = _display_alarm(trigger=when, trigger_related=Related.END)

    assert alarm.trigger_times(_START, _END) == [when]


def test_trigger_times_repeat_and_duration() -> None:
    """REPEAT is the number of *additional* firings, per rfc5545."""
    alarm = _display_alarm(
        trigger=datetime.timedelta(minutes=-15),
        repeat=3,
        duration=datetime.timedelta(minutes=5),
    )

    assert alarm.trigger_times(_START, _END) == [
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=_UTC),
        datetime.datetime(2025, 7, 15, 13, 50, tzinfo=_UTC),
        datetime.datetime(2025, 7, 15, 13, 55, tzinfo=_UTC),
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=_UTC),
    ]


def test_trigger_times_repeat_of_zero_fires_once() -> None:
    """rfc5545 counts repeats as additional firings, so zero means just one."""
    alarm = _display_alarm(
        trigger=datetime.timedelta(minutes=-15),
        repeat=0,
        duration=datetime.timedelta(minutes=5),
    )

    assert alarm.trigger_times(_START, _END) == [
        datetime.datetime(2025, 7, 15, 13, 45, tzinfo=_UTC)
    ]


def test_trigger_times_negative_duration_still_comes_back_sorted() -> None:
    """Malformed but readable; the docstring promises chronological order."""
    alarm = _display_alarm(
        trigger=datetime.timedelta(minutes=-15),
        repeat=2,
        duration=datetime.timedelta(minutes=-5),
    )

    times = alarm.trigger_times(_START, _END)

    assert times == sorted(times)


def test_trigger_times_against_an_all_day_date() -> None:
    """A date has no time of day, so it becomes local midnight."""
    alarm = _display_alarm(trigger=datetime.timedelta(hours=-1))

    (time,) = alarm.trigger_times(datetime.date(2025, 7, 15))

    assert time.tzinfo is not None
    assert (time + datetime.timedelta(hours=1)).timetuple()[:5] == (2025, 7, 15, 0, 0)


def test_related_is_read_from_the_trigger_parameter() -> None:
    """RELATED lives on TRIGGER, not on a property of its own."""
    alarm = IcsCalendarStream.calendar_from_ics(_ICS).events[0].alarm[0]

    assert alarm.trigger_related == Related.END
    assert alarm.trigger_times(_START, _END) == [
        datetime.datetime(2025, 7, 15, 14, 55, tzinfo=_UTC)
    ]


def test_related_survives_a_round_trip() -> None:
    """Dropping the parameter silently moves the alarm to the start."""
    ics = IcsCalendarStream.calendar_to_ics(IcsCalendarStream.calendar_from_ics(_ICS))

    assert "TRIGGER;RELATED=END:-PT5M" in ics
    assert "TRIGGER_RELATED" not in ics


def test_related_default_is_not_written_out() -> None:
    """RELATED=START is the default; emitting it would churn every file."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _ICS.replace("TRIGGER;RELATED=END:-PT5M", "TRIGGER:-PT5M")
    )

    ics = IcsCalendarStream.calendar_to_ics(calendar)

    assert "TRIGGER:-PT5M" in ics
    assert "RELATED" not in ics


def test_unknown_related_value_is_ignored_not_fatal() -> None:
    """This parameter was unread before; rejecting the file would be stricter."""
    calendar = IcsCalendarStream.calendar_from_ics(
        _ICS.replace("RELATED=END", "RELATED=MIDDLE")
    )

    alarm = calendar.events[0].alarm[0]

    assert alarm.trigger_related == Related.START
    assert "RELATED" not in IcsCalendarStream.calendar_to_ics(calendar)


def test_related_does_not_accumulate_across_round_trips() -> None:
    """The encoder appends to `params`; twice would be twice the parameter."""
    ics = IcsCalendarStream.calendar_to_ics(IcsCalendarStream.calendar_from_ics(_ICS))
    again = IcsCalendarStream.calendar_to_ics(IcsCalendarStream.calendar_from_ics(ics))

    assert ics == again
    assert again.count("RELATED=END") == 1


def test_related_is_serialised_for_an_alarm_built_in_python() -> None:
    """Nothing lifts RELATED off a property here; it comes from the field."""
    calendar = Calendar()
    calendar.events.append(
        Event(
            summary="Dentist",
            dtstart=_START,
            dtend=_END,
            alarm=[
                _display_alarm(
                    trigger=datetime.timedelta(minutes=-5),
                    trigger_related=Related.END,
                )
            ],
        )
    )

    ics = IcsCalendarStream(vcalendar=[calendar]).ics()

    assert "TRIGGER;RELATED=END:-PT5M" in ics


def test_trigger_times_for_an_alarm_on_a_todo() -> None:
    """VTODO has no convenience method, but the primitive and ics both work."""
    calendar = IcsCalendarStream.calendar_from_ics(_TODO_ICS)
    todo = calendar.todos[0]
    due = todo.due
    assert due is not None

    assert todo.alarms[0].trigger_times(due, due) == [
        datetime.datetime(2025, 7, 16, 8, 30, tzinfo=_UTC)
    ]
    assert "TRIGGER;RELATED=END:-PT30M" in IcsCalendarStream.calendar_to_ics(calendar)
