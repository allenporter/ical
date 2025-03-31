"""Tests for Journal component."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

import pytest

from ical.exceptions import CalendarParseError
from ical.journal import Journal, JournalStatus
from ical.timespan import Timespan


def test_empty() -> None:
    """Test that in practice a Journal requires no fields."""
    journal = Journal()
    assert not journal.summary


def test_journal() -> None:
    """Test a valid Journal object."""
    journal = Journal(summary="Example")
    assert journal.summary == "Example"


def test_status() -> None:
    """Test Journal status."""
    journal = Journal.parse_obj({"status": "DRAFT"})
    assert journal.status == JournalStatus.DRAFT

    with pytest.raises(
        CalendarParseError,
        match="^Failed to parse calendar JOURNAL component: value is not a valid enumeration member; permitted: 'DRAFT', 'FINAL', 'CANCELLED'$",
    ):
        Journal.parse_obj({"status": "invalid-status"})


def test_start_datetime() -> None:
    """Test journal start date conversions."""

    journal = Journal(start=datetime.date(2022, 8, 7))
    assert journal.start
    assert journal.start.isoformat() == "2022-08-07"

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ), patch(
        "ical.journal.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert journal.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
        assert not journal.recurring

        ts = journal.timespan
        assert ts
        assert ts.start.isoformat() == "2022-08-07T00:00:00-06:00"
        assert ts.end.isoformat() == "2022-08-08T00:00:00-06:00"


def test_computed_duration_date() -> None:
    """Test computed duration for a date."""

    journal = Journal(
        start=datetime.date(
            2022,
            8,
            7,
        )
    )
    assert journal.start
    assert journal.computed_duration == datetime.timedelta(days=1)


def test_computed_duration_datetime() -> None:
    """Test computed duration for a datetime."""

    journal = Journal(start=datetime.datetime(2022, 8, 7, 0, 0, 0))
    assert journal.start
    assert journal.computed_duration == datetime.timedelta(hours=1)
