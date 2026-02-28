"""Tests for the same-day DTEND compatibility module."""

import pathlib

import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import same_day_dtend_compat

TESTDATA_PATH = pathlib.Path("tests/compat/testdata/")
CALENDAR_LABS_SAME_DAY = TESTDATA_PATH / "calendar_labs_same_day_dtend.ics"


def test_same_day_dtend_fail() -> None:
    """Test Calendar Labs same-day DTEND without compat mode."""
    # This should parse but have incorrect DTEND (same as DTSTART)
    calendar = IcsCalendarStream.calendar_from_ics(
        CALENDAR_LABS_SAME_DAY.read_text(encoding="utf-8")
    )
    
    event = calendar.events[0]
    # Without compat mode, DTEND should equal DTSTART (incorrect)
    assert event.dtstart == event.dtend
    assert str(event.dtstart) == "2025-12-08"
    assert str(event.dtend) == "2025-12-08"


def test_same_day_dtend_compat() -> None:
    """Test Calendar Labs same-day DTEND with compat mode enabled."""
    with same_day_dtend_compat.enable_same_day_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(
            CALENDAR_LABS_SAME_DAY.read_text(encoding="utf-8")
        )
    
    event = calendar.events[0]
    # With compat mode, DTEND should be DTSTART + 1 day (correct)
    assert event.dtend != event.dtstart
    assert str(event.dtstart) == "2025-12-08"
    assert str(event.dtend) == "2025-12-09"
    
    # Test that the output can be serialized and parsed back
    output_ics = IcsCalendarStream.calendar_to_ics(calendar)
    reparsed_calendar = IcsCalendarStream.calendar_from_ics(output_ics)
    reparsed_event = reparsed_calendar.events[0]
    assert str(reparsed_event.dtstart) == "2025-12-08"
    assert str(reparsed_event.dtend) == "2025-12-09"


def test_same_day_dtend_compat_context_manager() -> None:
    """Test that compat mode is properly enabled/disabled."""
    # Initially disabled
    assert not same_day_dtend_compat.is_same_day_dtend_compat_enabled()
    
    # Enabled within context
    with same_day_dtend_compat.enable_same_day_dtend_compat():
        assert same_day_dtend_compat.is_same_day_dtend_compat_enabled()
    
    # Disabled after context
    assert not same_day_dtend_compat.is_same_day_dtend_compat_enabled()


def test_same_day_dtend_only_affects_all_day_events() -> None:
    """Test that same-day DTEND fix only affects all-day events, not datetime events."""
    datetime_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Calendar Labs//Calendar 1.0//EN
BEGIN:VEVENT
UID:datetime-event
DTSTART:20251208T100000Z
DTEND:20251208T100000Z
SUMMARY:Datetime Event
END:VEVENT
END:VCALENDAR"""
    
    with same_day_dtend_compat.enable_same_day_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(datetime_ics)
    
    event = calendar.events[0]
    # Datetime events should NOT be fixed (DTEND should remain same as DTSTART)
    assert event.dtstart == event.dtend
    assert "10:00:00+00:00" in str(event.dtstart)


def test_same_day_dtend_only_affects_same_dates() -> None:
    """Test that fix only applies when DTSTART equals DTEND."""
    different_dates_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Calendar Labs//Calendar 1.0//EN
BEGIN:VEVENT
UID:different-dates
DTSTART;VALUE=DATE:20251208
DTEND;VALUE=DATE:20251210
SUMMARY:Multi-day Event
END:VEVENT
END:VCALENDAR"""
    
    with same_day_dtend_compat.enable_same_day_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(different_dates_ics)
    
    event = calendar.events[0]
    # Events with different DTSTART/DTEND should NOT be modified
    assert str(event.dtstart) == "2025-12-08"
    assert str(event.dtend) == "2025-12-10"
