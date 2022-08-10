"""Tests for Free/Busy component."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

from ical.freebusy import FreeBusy


def test_empty() -> None:
    """Test that no fields are required."""
    freebusy = FreeBusy()
    assert not freebusy.sequence


def test_freebusy() -> None:
    """Test a valid Journal object."""
    freebusy = FreeBusy(sequence=1)
    assert freebusy.sequence == 1


def test_start() -> None:
    """Test freebusy start date conversions."""

    freebusy = FreeBusy(
        start=datetime.datetime(2022, 8, 7, 5, 0, 0, tzinfo=datetime.timezone.utc)
    )
    assert freebusy.start_datetime.isoformat() == "2022-08-07T05:00:00+00:00"
    assert not freebusy.end


def test_start_datetime() -> None:
    """Test freebusy start date conversions."""

    freebusy = FreeBusy(start=datetime.date(2022, 8, 7))
    assert freebusy.start

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert freebusy.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"

    assert not freebusy.end


def test_start_end_datetime() -> None:
    """Test freebusy start date conversions."""

    freebusy = FreeBusy(start=datetime.date(2022, 8, 7), end=datetime.date(2022, 8, 10))
    assert freebusy.start
    assert freebusy.end

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert freebusy.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
        assert freebusy.end_datetime
        assert freebusy.end_datetime.isoformat() == "2022-08-10T06:00:00+00:00"
