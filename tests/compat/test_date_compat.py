"""Tests for the invalid date parsing compatibility component."""

import datetime
import pytest

from ical.exceptions import CalendarParseError
from ical.calendar_stream import IcsCalendarStream
from ical.compat import enable_compat_mode, date_compat

INVALID_DATE_ICS = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:19970610T172345Z-AF23B2@example.com
DTSTART;VALUE=DATE:20260920T080000
DTEND;VALUE=DATE:20260920T160000
SUMMARY:Value Date Event
END:VEVENT
END:VCALENDAR"""


def test_invalid_date_parsing_fail() -> None:
    """Test that parsing fails under normal mode for DATE with time suffix."""
    with pytest.raises(
        CalendarParseError,
        match="Expected value to match DATE pattern: '20260920T080000'",
    ):
        IcsCalendarStream.calendar_from_ics(INVALID_DATE_ICS)


def test_invalid_date_parsing_compat_mode() -> None:
    """Test that parsing succeeds under compat mode for DATE with time suffix."""
    with enable_compat_mode(INVALID_DATE_ICS) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.dtstart is not None
    assert event.dtend is not None
    # Verify that DTSTART/DTEND were parsed as dates and stripped of their time suffix
    assert event.dtstart.year == 2026
    assert event.dtstart.month == 9
    assert event.dtstart.day == 20
    assert event.dtend.year == 2026
    assert event.dtend.month == 9
    assert event.dtend.day == 21


def test_invalid_date_parsing_direct_compat() -> None:
    """Test that parsing succeeds directly with enable_allow_invalid_dates context manager."""
    with date_compat.enable_allow_invalid_dates():
        calendar = IcsCalendarStream.calendar_from_ics(INVALID_DATE_ICS)

    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.dtstart is not None
    assert event.dtstart.year == 2026
    assert event.dtstart.month == 9
    assert event.dtstart.day == 20
