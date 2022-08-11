"""Tests for Free/Busy component."""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

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
