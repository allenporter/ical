"""Tests for the DURATION/DTEND conflict compatibility component.

RFC 5545 Section 3.6.1 states that a VEVENT may have either DTEND or
DURATION, but never both. Some real-world calendar generators emit both
properties redundantly (e.g. a DTEND that is simply DTSTART + DURATION),
which causes strict parsing to fail outright even though the event's
intent is unambiguous.
"""

import pytest

from ical.exceptions import CalendarParseError
from ical.calendar_stream import IcsCalendarStream
from ical.compat import duration_dtend_compat, enable_compat_mode

DUPLICATE_DURATION_DTEND_ICS = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:19970610T172345Z-AF23B2@example.com
DTSTART:20260920T080000Z
DTEND:20260920T090000Z
DURATION:PT1H
SUMMARY:Both DTEND and DURATION set
END:VEVENT
END:VCALENDAR"""

# DTEND that disagrees with DTSTART + DURATION.
CONFLICTING_DURATION_DTEND_ICS = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:19970610T172345Z-AF23B3@example.com
DTSTART:20260920T080000Z
DTEND:20260920T093000Z
DURATION:PT1H
SUMMARY:Conflicting DTEND and DURATION values
END:VEVENT
END:VCALENDAR"""


def test_duration_dtend_conflict_fails_without_compat() -> None:
    """Test that parsing fails under strict mode when both are set."""
    with pytest.raises(
        CalendarParseError, match="Only one of dtend or duration may be set"
    ):
        IcsCalendarStream.calendar_from_ics(DUPLICATE_DURATION_DTEND_ICS)


def test_duration_dtend_conflict_compat_mode() -> None:
    """Test that compat mode resolves the conflict by preferring DTEND."""
    with enable_compat_mode(DUPLICATE_DURATION_DTEND_ICS) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.duration is None
    assert str(event.dtend) == "2026-09-20 09:00:00+00:00"

    # Verify the output re-serializes and re-parses cleanly (no DURATION
    # property line; note "DURATION" also appears inside the free-text
    # SUMMARY, so match on the property line specifically).
    output_ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert "\nDURATION:" not in output_ics
    reparsed = IcsCalendarStream.calendar_from_ics(output_ics)
    assert str(reparsed.events[0].dtend) == "2026-09-20 09:00:00+00:00"


def test_duration_dtend_conflicting_values_compat_mode() -> None:
    """Test that compat mode prefers DTEND even when values disagree."""
    with duration_dtend_compat.enable_duration_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(CONFLICTING_DURATION_DTEND_ICS)

    event = calendar.events[0]
    assert event.duration is None
    # DTEND (the more explicit, unambiguous property) wins.
    assert str(event.dtend) == "2026-09-20 09:30:00+00:00"


def test_duration_dtend_compat_context_manager() -> None:
    """Test that compat mode is properly enabled/disabled."""
    assert not duration_dtend_compat.is_duration_dtend_compat_enabled()

    with duration_dtend_compat.enable_duration_dtend_compat():
        assert duration_dtend_compat.is_duration_dtend_compat_enabled()

    assert not duration_dtend_compat.is_duration_dtend_compat_enabled()


def test_duration_only_still_works_under_compat() -> None:
    """Test that events with only DURATION (no DTEND) are unaffected."""
    ics = """BEGIN:VCALENDAR
PRODID:-//hacksw/handcal//NONSGML v1.0//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:19970610T172345Z
UID:duration-only@example.com
DTSTART:20260920T080000Z
DURATION:PT1H
SUMMARY:Duration only event
END:VEVENT
END:VCALENDAR"""
    with duration_dtend_compat.enable_duration_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(ics)

    event = calendar.events[0]
    assert event.duration is not None
    assert event.dtend is None
