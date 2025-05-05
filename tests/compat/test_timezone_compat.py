"""Tests for the extended timezone component."""

import pathlib

import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream
from ical.store import TodoStore
from ical.compat import timezone_compat

TESTDATA_PATH = pathlib.Path("tests/compat/testdata/")
OFFICE_365_EXTENDED_TIMEZONE = TESTDATA_PATH / "office_365_extended_timezone.ics"
OFFICE_365_INVALID_TIMEZONE = TESTDATA_PATH / "office_365_invalid_timezone.ics"


def test_extended_timezone_fail() -> None:
    """Test Office 365 extended timezone."""

    with pytest.raises(
        CalendarParseError,
        match="Expected DATE-TIME TZID value 'W. Europe Standard Time' to be valid timezone",
    ):
        IcsCalendarStream.from_ics(
            OFFICE_365_EXTENDED_TIMEZONE.read_text(encoding="utf-8")
        )


def test_extended_timezone_compat(snapshot: SnapshotAssertion) -> None:
    """Test Office 365 extended timezone with compat enabled."""
    with timezone_compat.enable_extended_timezones():
        calendar = IcsCalendarStream.from_ics(
            OFFICE_365_EXTENDED_TIMEZONE.read_text(encoding="utf-8")
        )
    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot


def test_invalid_timezone_fail() -> None:
    """Test Office 365 invalid timezone."""

    with pytest.raises(
        CalendarParseError,
        match="Expected DATE-TIME TZID value 'Customized Time Zone' to be valid timezone",
    ):
        IcsCalendarStream.from_ics(
            OFFICE_365_INVALID_TIMEZONE.read_text(encoding="utf-8")
        )


def test_invalid_timezone_compat(snapshot: SnapshotAssertion) -> None:
    """Test Office 365 invalid timezone."""

    with timezone_compat.enable_allow_invalid_timezones():
        calendar = IcsCalendarStream.from_ics(
            OFFICE_365_INVALID_TIMEZONE.read_text(encoding="utf-8")
        )
    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot
