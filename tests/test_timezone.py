"""Tests for Free/Busy component."""

from __future__ import annotations

from collections.abc import Generator
import datetime
import inspect

import pytest
from freezegun import freeze_time

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.exceptions import CalendarParseError
from ical.timezone import IcsTimezoneInfo, Observance, Timezone
from ical.types import UtcOffset
from ical.types.recur import Frequency, Recur, Weekday, WeekdayValue
from ical.tzif.timezoneinfo import TimezoneInfoError

TEST_RECUR = Recur(
    freq=Frequency.YEARLY,
    by_month=[10],
    by_day=[WeekdayValue(Weekday.SUNDAY, occurrence=-1)],
    until=datetime.datetime(2006, 10, 29, 6, 0, 0),
)


def test_requires_subcompnent() -> None:
    """Test Timezone constructor."""
    with pytest.raises(CalendarParseError, match=r"At least one standard or daylight.*"):
        Timezone(tz_id="America/New_York")


def test_daylight() -> None:
    """Test a Timezone object with a daylight observance."""
    timezone = Timezone(
        tz_id="America/New_York",
        last_modified=datetime.datetime(2005, 8, 9, 5),
        daylight=[
            Observance(
                start=datetime.datetime(1967, 10, 29, 2, 0, 0, 0),
                tz_offset_to=UtcOffset(datetime.timedelta(hours=-4)),
                tz_offset_from=UtcOffset(datetime.timedelta(hours=-5)),
                tz_name=["edt"],
                rrule=TEST_RECUR,
            ),
        ],
    )
    assert len(timezone.daylight) == 1
    assert timezone.daylight[0].tz_name == ["edt"]

    tz_info = IcsTimezoneInfo.from_timezone(timezone)

    value = datetime.datetime(1967, 10, 29, 1, 59, 0, 0, tzinfo=tz_info)
    assert not tz_info.tzname(value)
    assert not tz_info.utcoffset(value)
    assert not tz_info.dst(value)

    value = datetime.datetime(1967, 10, 29, 2, 00, 0, 0, tzinfo=tz_info)
    assert tz_info.tzname(value) == "edt"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)


def test_timezone_observence_start_time_validation() -> None:
    """Verify that a start time must be in local time."""
    with pytest.raises(
        CalendarParseError, match=r".*Start time must be in local time format*"
    ):
        Observance(
            start=datetime.datetime(1967, 10, 29, 2, tzinfo=datetime.timezone.utc),
            tz_offset_to=UtcOffset(datetime.timedelta(hours=-5)),
            tz_offset_from=UtcOffset(datetime.timedelta(hours=-4)),
            tz_name=["est"],
            rrule=TEST_RECUR,
        )


@freeze_time("2022-08-22 12:30:00")
def test_from_tzif_timezoneinfo_with_dst(
    mock_prodid: Generator[None, None, None]
) -> None:
    """Verify a timezone created from a tzif timezone info with DST information."""

    timezone = Timezone.from_tzif("America/New_York")

    calendar = Calendar()
    calendar.timezones.append(timezone)

    stream = IcsCalendarStream(calendars=[calendar])
    assert stream.ics() == inspect.cleandoc(
        """
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:America/New_York
       BEGIN:STANDARD
       DTSTART:20101107T020000
       TZOFFSETTO:-0500
       TZOFFSETFROM:-0400
       RRULE:FREQ=YEARLY;BYDAY=1SU;BYMONTH=11
       TZNAME:EST
       END:STANDARD
       BEGIN:DAYLIGHT
       DTSTART:20100314T020000
       TZOFFSETTO:-0400
       TZOFFSETFROM:-0500
       RRULE:FREQ=YEARLY;BYDAY=2SU;BYMONTH=3
       TZNAME:EDT
       END:DAYLIGHT
       END:VTIMEZONE
       END:VCALENDAR
    """
    )

    tz_info = IcsTimezoneInfo.from_timezone(timezone)

    value = datetime.datetime(2010, 11, 7, 1, 59, 0)
    assert tz_info.tzname(value) == "EDT"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)

    value = datetime.datetime(2010, 11, 7, 2, 0, 0)
    assert tz_info.tzname(value) == "EST"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-5)
    assert tz_info.dst(value) == datetime.timedelta(hours=0)

    value = datetime.datetime(2011, 3, 13, 1, 59, 0)
    assert tz_info.tzname(value) == "EST"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-5)
    assert tz_info.dst(value) == datetime.timedelta(hours=0)

    value = datetime.datetime(2011, 3, 14, 2, 0, 0)
    assert tz_info.tzname(value) == "EDT"
    assert tz_info.utcoffset(value) == datetime.timedelta(hours=-4)
    assert tz_info.dst(value) == datetime.timedelta(hours=1)


@freeze_time("2022-08-22 12:30:00")
def test_from_tzif_timezoneinfo_fixed_offset(
    mock_prodid: Generator[None, None, None]
) -> None:
    """Verify a timezone created from a tzif timezone info with a fixed offset"""

    timezone = Timezone.from_tzif("Asia/Tokyo")

    calendar = Calendar()
    calendar.timezones.append(timezone)

    stream = IcsCalendarStream(calendars=[calendar])
    assert stream.ics() == inspect.cleandoc(
        """
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:Asia/Tokyo
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """
    )


def test_invalid_tzif_key() -> None:
    """Test creating a timezone object from tzif data that does not exist."""

    with pytest.raises(TimezoneInfoError, match=r"Unable to find timezone"):
        Timezone.from_tzif("invalid")



@freeze_time("2022-08-22 12:30:00")
def test_clear_old_dtstamp(
    mock_prodid: Generator[None, None, None]
) -> None:
    """Verify a timezone created from a tzif timezone info with a fixed offset"""

    stream = IcsCalendarStream.from_ics(inspect.cleandoc("""
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       DTSTAMP:20220822T123000
       TZID:Asia/Tokyo
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """))
    # DTSTAMP is omitted from the output
    assert stream.ics() == inspect.cleandoc("""
       BEGIN:VCALENDAR
       PRODID:-//example//1.2.3
       VERSION:2.0
       BEGIN:VTIMEZONE
       TZID:Asia/Tokyo
       BEGIN:STANDARD
       DTSTART:20100101T000000
       TZOFFSETTO:+0900
       TZOFFSETFROM:+0900
       TZNAME:JST
       END:STANDARD
       END:VTIMEZONE
       END:VCALENDAR
    """)
