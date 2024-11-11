"""Tests for timeline related calendar eents."""
from __future__ import annotations

from collections.abc import Generator
import datetime
import re
import uuid
import zoneinfo
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.types.recur import Recur


@pytest.fixture(name="calendar")
def mock_calendar() -> Calendar:
    """Fixture calendar with all day events to use in tests."""
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="second",
                start=datetime.date(2000, 2, 1),
                end=datetime.date(2000, 2, 2),
            ),
            Event(
                summary="fourth",
                start=datetime.date(2000, 4, 1),
                end=datetime.date(2000, 4, 2),
            ),
            Event(
                summary="third",
                start=datetime.date(2000, 3, 1),
                end=datetime.date(2000, 3, 2),
            ),
            Event(
                summary="first",
                start=datetime.date(2000, 1, 1),
                end=datetime.date(2000, 1, 2),
            ),
        ]
    )
    return cal


@pytest.fixture(name="calendar_times")
def mock_calendar_times() -> Calendar:
    """Fixture calendar with datetime based events to use in tests."""
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="first",
                start=datetime.datetime(2000, 1, 1, 11, 0),
                end=datetime.datetime(2000, 1, 1, 11, 30),
            ),
            Event(
                summary="second",
                start=datetime.datetime(2000, 1, 1, 12, 0),
                end=datetime.datetime(2000, 1, 1, 13, 0),
            ),
            Event(
                summary="third",
                start=datetime.datetime(2000, 1, 2, 12, 0),
                end=datetime.datetime(2000, 1, 2, 13, 0),
            ),
        ]
    )
    return cal


@pytest.fixture(name="calendar_mixed")
def mock_calendar_mixed() -> Calendar:
    """Fixture with a mix of all day and datetime based events."""
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="All Day",
                start=datetime.date(2000, 2, 1),
                end=datetime.date(2000, 2, 2),
            ),
            Event(
                summary="Event @ 7 UTC",
                start=datetime.datetime(
                    2000, 2, 1, 7, 00, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2000, 2, 2, 7, 00, 0, tzinfo=datetime.timezone.utc
                ),
            ),
            Event(
                summary="Event @ 5UTC",
                start=datetime.datetime(
                    2000, 2, 1, 5, 00, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2000, 2, 2, 5, 00, 0, tzinfo=datetime.timezone.utc
                ),
            ),
        ]
    )
    return cal


def test_iteration(calendar: Calendar) -> None:
    """Test chronological iteration of a timeline."""
    assert [e.summary for e in calendar.timeline] == [
        "first",
        "second",
        "third",
        "fourth",
    ]


@pytest.mark.parametrize(
    "when,expected_events",
    [
        (datetime.date(2000, 1, 1), ["first"]),
        (datetime.date(2000, 2, 1), ["second"]),
        (datetime.date(2000, 3, 1), ["third"]),
    ],
)
def test_on_date(
    calendar: Calendar, when: datetime.date, expected_events: list[str]
) -> None:
    """Test returning events on a particular day."""
    assert [e.summary for e in calendar.timeline.on_date(when)] == expected_events


def test_start_after(calendar: Calendar) -> None:
    """Test chronological iteration starting at a specific time."""
    assert [
        e.summary for e in calendar.timeline.start_after(datetime.date(2000, 1, 1))
    ] == ["second", "third", "fourth"]
    assert [
        e.summary
        for e in calendar.timeline.start_after(datetime.datetime(2000, 1, 1, 6, 0, 0))
    ] == ["second", "third", "fourth"]
    assert [
        e.summary
        for e in calendar.timeline.start_after(datetime.datetime(2000, 1, 15, 0, 0, 0))
    ] == ["second", "third", "fourth"]


def test_start_after_times(calendar_times: Calendar) -> None:
    """Test chronological iteration starting at a specific time."""
    assert [
        e.summary
        for e in calendar_times.timeline.start_after(datetime.date(2000, 1, 1))
    ] == ["first", "second", "third"]
    assert [
        e.summary
        for e in calendar_times.timeline.start_after(
            datetime.datetime(2000, 1, 1, 6, 0, 0)
        )
    ] == ["first", "second", "third"]


def test_active_after(calendar: Calendar) -> None:
    """Test chronological iteration starting at a specific time."""
    assert [
        e.summary
        for e in calendar.timeline.start_after(datetime.datetime(2000, 1, 1, 12, 0, 0))
    ] == ["second", "third", "fourth"]
    assert [
        e.summary for e in calendar.timeline.start_after(datetime.date(2000, 1, 1))
    ] == ["second", "third", "fourth"]


def test_active_after_times(calendar_times: Calendar) -> None:
    """Test chronological iteration starting at a specific time."""
    assert [
        e.summary
        for e in calendar_times.timeline.start_after(
            datetime.datetime(2000, 1, 1, 12, 0, 0)
        )
    ] == ["third"]
    assert [
        e.summary
        for e in calendar_times.timeline.start_after(datetime.date(2000, 1, 1))
    ] == ["first", "second", "third"]


@pytest.mark.parametrize(
    "at_datetime,expected_events",
    [
        (datetime.datetime(2000, 1, 1, 11, 15), ["first"]),
        (datetime.datetime(2000, 1, 1, 11, 59), []),
        (datetime.datetime(2000, 1, 1, 12, 0), ["second"]),
        (datetime.datetime(2000, 1, 1, 12, 30), ["second"]),
        (datetime.datetime(2000, 1, 1, 12, 59), ["second"]),
        (datetime.datetime(2000, 1, 1, 13, 0), []),
    ],
)
def test_at_instant(
    calendar_times: Calendar, at_datetime: datetime.datetime, expected_events: list[str]
) -> None:
    """Test returning events at a specific time."""
    assert [
        e.summary for e in calendar_times.timeline.at_instant(at_datetime)
    ] == expected_events


@freeze_time("2000-01-01 12:30:00")
def test_now(calendar_times: Calendar) -> None:
    """Test events happening at the current time."""
    assert [e.summary for e in calendar_times.timeline.now()] == ["second"]


@freeze_time("2000-01-01 13:00:00")
def test_now_no_match(calendar_times: Calendar) -> None:
    """Test no events happening at the current time."""
    assert [e.summary for e in calendar_times.timeline.now()] == []


@freeze_time("2000-01-01 12:30:00")
def test_today(calendar_times: Calendar) -> None:
    """Test events active today."""
    assert [e.summary for e in calendar_times.timeline.today()] == ["first", "second"]


@pytest.mark.parametrize(
    "start,end,expected_events",
    [
        (
            datetime.datetime(2000, 1, 1, 10, 00),
            datetime.datetime(2000, 1, 2, 14, 00),
            ["first", "second", "third"],
        ),
        (
            datetime.datetime(2000, 1, 1, 10, 00),
            datetime.datetime(2000, 1, 1, 14, 00),
            ["first", "second"],
        ),
        (
            datetime.datetime(2000, 1, 1, 12, 00),
            datetime.datetime(2000, 1, 2, 14, 00),
            ["second", "third"],
        ),
        (
            datetime.datetime(2000, 1, 1, 12, 00),
            datetime.datetime(2000, 1, 1, 14, 00),
            ["second"],
        ),
    ],
)
def test_included(
    calendar_times: Calendar,
    start: datetime.datetime,
    end: datetime.datetime,
    expected_events: list[str],
) -> None:
    """Test calendar timeline inclusions."""
    assert [
        e.summary for e in calendar_times.timeline.included(start, end)
    ] == expected_events


def test_multiple_calendars(calendar: Calendar, calendar_times: Calendar) -> None:
    """Test multiple calendars have independent event lists."""
    assert len(calendar.events) == 4
    assert len(calendar_times.events) == 3
    assert len(Calendar().events) == 0


def test_multiple_iteration(calendar: Calendar) -> None:
    """Test iterating over a timeline multiple times."""
    line = calendar.timeline
    assert [e.summary for e in line] == [
        "first",
        "second",
        "third",
        "fourth",
    ]
    assert [e.summary for e in line] == [
        "first",
        "second",
        "third",
        "fourth",
    ]


TEST_ICS = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:19970610T172345Z-AF23B2@example.com
DTSTART:19970714T170000Z
DTEND:19970715T040000Z
SUMMARY:Bastille Day Party
END:VEVENT
END:VCALENDAR"""


def test_calendar_serialization() -> None:
    """Test single calendar serialization."""
    calendar = IcsCalendarStream.calendar_from_ics(TEST_ICS)
    assert len(calendar.events) == 1
    assert calendar.events[0].summary == "Bastille Day Party"
    output_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert output_ics == TEST_ICS


def test_empty_calendar() -> None:
    """Test reading an empty calendar file."""
    calendar = IcsCalendarStream.calendar_from_ics("")
    assert len(calendar.events) == 0


@pytest.fixture(name="_uid")
def mock_uid() -> Generator[str, None, None]:
    """Patch out uuid creation with a fixed value."""
    value = str(uuid.uuid3(uuid.NAMESPACE_DNS, "fixed-name"))
    with patch(
        "ical.event.uid_factory",
        return_value=value,
    ):
        yield value


@freeze_time("2000-01-01 12:30:00")
def test_create_and_serialize_calendar(
    _uid: str,
    mock_prodid: Generator[None, None, None],
) -> None:
    """Test creating a calendar manually then serializing."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event",
            start=datetime.date(2000, 2, 1),
            end=datetime.date(2000, 2, 2),
        )
    )
    ics = IcsCalendarStream.calendar_to_ics(cal)
    assert re.split("\r?\n", ics) == [
        "BEGIN:VCALENDAR",
        "PRODID:-//example//1.2.3",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "DTSTAMP:20000101T123000Z",
        "UID:68e9e07c-7557-36e2-91c1-8febe7527841",
        "DTSTART:20000201",
        "DTEND:20000202",
        "SUMMARY:Event",
        "END:VEVENT",
        "END:VCALENDAR",
    ]


def test_mixed_iteration_order(calendar_mixed: Calendar) -> None:
    """Test iteration order of all day events based on the attendee timezone."""

    # UTC order
    assert [e.summary for e in calendar_mixed.timeline_tz(datetime.timezone.utc)] == [
        "All Day",
        "Event @ 5UTC",
        "Event @ 7 UTC",
    ]

    # Attendee is in -6
    assert [
        e.summary
        for e in calendar_mixed.timeline_tz(zoneinfo.ZoneInfo("America/Regina"))
    ] == ["Event @ 5UTC", "All Day", "Event @ 7 UTC"]

    # Attendee is in -8
    assert [
        e.summary
        for e in calendar_mixed.timeline_tz(zoneinfo.ZoneInfo("America/Los_Angeles"))
    ] == ["Event @ 5UTC", "Event @ 7 UTC", "All Day"]


@pytest.mark.parametrize(
    "tzname,dt_before,dt_after",
    [
        (
            "America/Los_Angeles",  # UTC-8 in Feb
            datetime.datetime(2000, 2, 1, 7, 59, 59, tzinfo=datetime.timezone.utc),
            datetime.datetime(2000, 2, 1, 8, 0, 0, tzinfo=datetime.timezone.utc),
        ),
        (
            "America/Regina",  # UTC-6 all year round
            datetime.datetime(2000, 2, 1, 5, 59, 59, tzinfo=datetime.timezone.utc),
            datetime.datetime(2000, 2, 1, 6, 0, 0, tzinfo=datetime.timezone.utc),
        ),
        (
            "CET",  # UTC-1 in Feb
            datetime.datetime(2000, 1, 31, 22, 59, 59, tzinfo=datetime.timezone.utc),
            datetime.datetime(2000, 1, 31, 23, 0, 0, tzinfo=datetime.timezone.utc),
        ),
    ],
)
def test_all_day_with_local_timezone(
    tzname: str, dt_before: datetime.datetime, dt_after: datetime.datetime
) -> None:
    """Test iteration of all day events using local timezone override."""
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="event",
                start=datetime.date(2000, 2, 1),
                end=datetime.date(2000, 2, 2),
            ),
        ]
    )

    local_tz = zoneinfo.ZoneInfo(tzname)

    def start_after(dtstart: datetime.datetime) -> list[str]:
        nonlocal cal, local_tz
        return [e.summary for e in cal.timeline_tz(local_tz).start_after(dtstart)]

    local_before = dt_before.astimezone(local_tz)
    assert start_after(local_before) == ["event"]

    local_after = dt_after.astimezone(local_tz)
    assert not start_after(local_after)


@freeze_time(datetime.datetime(2023, 10, 25, 12, 0, 0, tzinfo=datetime.timezone.utc))
def test_floating_time_with_timezone_propagation() -> None:
    """Test iteration of floating time events ensuring timezones are respected."""
    cal = Calendar()
    cal.events.extend(
        [
            Event(
                summary="Event 1",
                start=datetime.datetime(2023, 10, 25, 6, 40),
                end=datetime.datetime(2023, 10, 25, 6, 50),
                rrule=Recur.from_rrule("FREQ=WEEKLY;BYDAY=WE,MO,TU,TH,FR"),
            ),
            Event(
                summary="Event 2",
                start=datetime.datetime(2023, 10, 25, 8, 30),
                end=datetime.datetime(2023, 10, 25, 8, 40),
                rrule=Recur.from_rrule("FREQ=DAILY"),
            ),
            Event(
                summary="Event 3",
                start=datetime.datetime(2023, 10, 25, 18, 30),
                end=datetime.datetime(2023, 10, 25, 18, 40),
                rrule=Recur.from_rrule("FREQ=DAILY"),
            ),
        ]
    )
    # Ensure there are no calls to fetch the local timezone, only using the provided
    # timezone information.
    with patch("ical.util.local_timezone", side_effect=ValueError("do not invoke")):
        it = iter(cal.timeline_tz(zoneinfo.ZoneInfo("Europe/Brussels")))
        for i in range(0, 30):
            next(it)
