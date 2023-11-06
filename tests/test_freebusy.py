"""Tests for Free/Busy component."""

from __future__ import annotations

import datetime
import zoneinfo
from typing import Generator
from unittest.mock import patch

import pytest

from ical.exceptions import CalendarParseError
from ical.freebusy import FreeBusy
from ical.types import FreeBusyType, Period


@pytest.fixture(autouse=True)
def local_timezone() -> Generator[None, None, None]:
    """Fixture to set a local timezone to use during tests."""
    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        yield


def test_empty() -> None:
    """Test that no fields are required."""
    freebusy = FreeBusy()
    assert not freebusy.sequence
    assert not freebusy.start
    assert not freebusy.start_datetime
    assert not freebusy.end
    assert not freebusy.end_datetime
    assert not freebusy.computed_duration


def test_freebusy() -> None:
    """Test a valid Journal object."""
    freebusy = FreeBusy(sequence=1)
    assert freebusy.sequence == 1


def test_start_datetime() -> None:
    """Test FreeBusy with a start datetime and no end."""

    freebusy = FreeBusy(
        start=datetime.datetime(2022, 8, 7, 5, 0, 0, tzinfo=datetime.timezone.utc)
    )
    assert freebusy.start
    assert freebusy.start.isoformat() == "2022-08-07T05:00:00+00:00"
    assert freebusy.start_datetime
    assert freebusy.start_datetime.isoformat() == "2022-08-07T05:00:00+00:00"
    assert not freebusy.end
    assert not freebusy.end_datetime


def test_start_date() -> None:
    """Test FreeBusy with a start date and no end."""

    freebusy = FreeBusy(start=datetime.date(2022, 8, 7))
    assert freebusy.start.isoformat() == "2022-08-07"
    # Use local timezone
    assert freebusy.start_datetime
    assert freebusy.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"

    assert not freebusy.end
    assert not freebusy.end_datetime


def test_start_end_date() -> None:
    """Test freebusy start date conversions."""

    freebusy = FreeBusy(start=datetime.date(2022, 8, 7), end=datetime.date(2022, 8, 10))
    assert freebusy.start
    assert freebusy.start.isoformat() == "2022-08-07"
    assert freebusy.end
    assert freebusy.end.isoformat() == "2022-08-10"
    assert freebusy.computed_duration == datetime.timedelta(days=3)

    # Use local timezone
    assert freebusy.start_datetime
    assert freebusy.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
    assert freebusy.end_datetime
    assert freebusy.end_datetime.isoformat() == "2022-08-10T06:00:00+00:00"


def test_free_busy() -> None:
    """Test freebusy start date conversions."""
    freebusy = FreeBusy(
        start=datetime.date(2022, 8, 7),
        end=datetime.date(2022, 8, 10),
        freebusy=[
            Period(
                start=datetime.datetime(
                    2022, 8, 7, 5, 0, 0, tzinfo=datetime.timezone.utc
                ),
                duration=datetime.timedelta(hours=2),
                free_busy_type=FreeBusyType.BUSY,
            ),
            Period(
                start=datetime.datetime(
                    2022, 8, 7, 10, 0, 0, tzinfo=datetime.timezone.utc
                ),
                duration=datetime.timedelta(minutes=30),
                free_busy_type=FreeBusyType.BUSY,
            ),
        ],
    )
    assert freebusy.start
    assert freebusy.start.isoformat() == "2022-08-07"
    assert freebusy.end
    assert freebusy.end.isoformat() == "2022-08-10"
    assert len(freebusy.freebusy) == 2


def test_free_busy_requires_utc() -> None:
    """Test freebusy start date conversions."""
    with pytest.raises(CalendarParseError, match=r"Freebusy time must be in UTC format.*"):
        FreeBusy(
            start=datetime.date(2022, 8, 7),
            end=datetime.date(2022, 8, 10),
            freebusy=[
                Period(
                    start=datetime.datetime(2022, 8, 7, 5, 0, 0),
                    duration=datetime.timedelta(hours=2),
                    free_busy_type=FreeBusyType.BUSY,
                ),
            ],
        )
