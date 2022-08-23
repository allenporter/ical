"""Tests for Free/Busy component."""

from __future__ import annotations

import datetime
import inspect

import pytest
from freezegun import freeze_time
from pydantic import ValidationError

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.timezone import Timezone, TimezoneInfo
from ical.types import Frequency, Recur, UtcOffset, Weekday, WeekdayValue

TEST_RECUR = Recur(
    freq=Frequency.YEARLY,
    by_month=[10],
    by_day=[WeekdayValue(Weekday.SUNDAY, occurrence=-1)],
    until=datetime.datetime(2006, 10, 29, 6, 0, 0, tzinfo=datetime.timezone.utc),
)


def test_requires_subcompnent() -> None:
    """Test Timezone constructor."""
    with pytest.raises(ValidationError, match=r"At least one standard or daylight.*"):
        Timezone(tz_id="America/New_York")


def test_daylight() -> None:
    """Test a Timezone object with a daylight observance."""
    timezone = Timezone(
        tz_id="America/New_York",
        last_modified=datetime.datetime(
            2005, 8, 9, 5, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
        daylight=[
            TimezoneInfo(
                start=datetime.datetime(1967, 10, 29, 2, 0, 0, 0),
                tz_offset_to=UtcOffset(datetime.timedelta(hours=-5)),
                tz_offset_from=UtcOffset(datetime.timedelta(hours=-4)),
                tz_name=["est"],
                rrule=TEST_RECUR,
            ),
        ],
    )
    assert len(timezone.daylight) == 1
    assert timezone.daylight[0].tz_name == ["est"]


def test_timezone_observence_start_time_validation() -> None:
    """Verify that a start time must be in local time."""
    with pytest.raises(ValidationError, match=r".*must be in local time.*"):
        TimezoneInfo(
            start=datetime.datetime(
                1967, 10, 29, 2, 0, 0, 0, tzinfo=datetime.timezone.utc
            ),
            tz_offset_to=UtcOffset(datetime.timedelta(hours=-5)),
            tz_offset_from=UtcOffset(datetime.timedelta(hours=-4)),
            tz_name=["est"],
            rrule=TEST_RECUR,
        )


@freeze_time("2022-08-22 12:30:00")
def test_from_tzif_timezoneinfo() -> None:
    """Verify a timezone created from a tzif timezone info."""

    timezone = Timezone.from_tzif("America/New_York")

    calendar = Calendar()
    calendar.timezones.append(timezone)

    stream = IcsCalendarStream(calendars=[calendar])
    assert stream.ics() == inspect.cleandoc(
        """
       BEGIN:VCALENDAR
       BEGIN:VTIMEZONE
       DTSTAMP:20220822T123000
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
