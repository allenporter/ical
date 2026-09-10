"""Tests for the DTSTART/DTEND type mismatch compatibility component.

RFC 5545 Section 3.8.2.2 states that the value type of DTEND must match the value
type of DTSTART (both DATE or both DATE-TIME). Some real-world calendar feeds
(such as Edlio webcal feeds) emit all-day events with a DATE start and a DATE-TIME
end (e.g. 23:59:59 on the final day). Strict parsing rejects these files outright;
this compatibility fixup coerces DTEND to match DTSTART's type.
"""

import datetime
from zoneinfo import ZoneInfo
import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import dtstart_dtend_compat, enable_compat_mode
from ical.exceptions import CalendarParseError


EDLIO_MULTI_DAY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Edlio Inc//Edlio Calendar//EN
BEGIN:VTIMEZONE
TZID:US/Pacific
BEGIN:STANDARD
DTSTART:20071104T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZOFFSETFROM:-0700
TZOFFSETTO:-0800
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:20070311T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZOFFSETFROM:-0800
TZOFFSETTO:-0700
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:24770297@example.com
DTSTAMP:20260910T231136Z
DTSTART;VALUE=DATE:20260526
DTEND;TZID=US/Pacific:20260529T235959
SUMMARY:12th Senior Exam Week
END:VEVENT
END:VCALENDAR"""

SINGLE_DAY_END_TIME_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp//EN
BEGIN:VEVENT
UID:single-day-1@example.com
DTSTAMP:20260910T231136Z
DTSTART;VALUE=DATE:20260526
DTEND:20260526T235959Z
SUMMARY:Single Day Event
END:VEVENT
END:VCALENDAR"""

MIDNIGHT_END_TIME_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp//EN
BEGIN:VEVENT
UID:midnight-end-1@example.com
DTSTAMP:20260910T231136Z
DTSTART;VALUE=DATE:20260526
DTEND:20260529T000000Z
SUMMARY:Midnight End Event
END:VEVENT
END:VCALENDAR"""

DATETIME_START_DATE_END_SAME_DAY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp//EN
BEGIN:VEVENT
UID:dt-start-date-end-1@example.com
DTSTAMP:20260910T231136Z
DTSTART:20260526T100000Z
DTEND;VALUE=DATE:20260526
SUMMARY:Timed start, same day date end
END:VEVENT
END:VCALENDAR"""

DATETIME_START_DATE_END_NEXT_DAY_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Example Corp//EN
BEGIN:VEVENT
UID:dt-start-date-end-2@example.com
DTSTAMP:20260910T231136Z
DTSTART:20260526T100000Z
DTEND;VALUE=DATE:20260528
SUMMARY:Timed start, future date end
END:VEVENT
END:VCALENDAR"""


def test_date_start_datetime_end_fails_without_compat() -> None:
    """Test that parsing fails under strict mode when types mismatch."""
    with pytest.raises(
        CalendarParseError,
        match="Unexpected dtstart value '2026-05-26' was date but dtend value",
    ):
        IcsCalendarStream.calendar_from_ics(EDLIO_MULTI_DAY_ICS)


def test_datetime_start_date_end_fails_without_compat() -> None:
    """Test that parsing fails under strict mode when start is datetime and end is date."""
    with pytest.raises(
        CalendarParseError,
        match="was datetime but dtend value '2026-05-26' was not datetime",
    ):
        IcsCalendarStream.calendar_from_ics(DATETIME_START_DATE_END_SAME_DAY_ICS)


def test_edlio_multi_day_compat_mode() -> None:
    """Test that compat mode coerces DTEND to non-inclusive next day DATE."""
    with enable_compat_mode(EDLIO_MULTI_DAY_ICS) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.dtstart == datetime.date(2026, 5, 26)
    assert event.dtend == datetime.date(2026, 5, 30)
    assert event.computed_duration == datetime.timedelta(days=4)

    # Test round-trip serialization and re-parsing
    output_ics = IcsCalendarStream.calendar_to_ics(calendar)
    reparsed = IcsCalendarStream.calendar_from_ics(output_ics)
    assert reparsed.events[0].dtstart == datetime.date(2026, 5, 26)
    assert reparsed.events[0].dtend == datetime.date(2026, 5, 30)


def test_single_day_end_time_compat_mode() -> None:
    """Test single day event with end time 23:59:59 becomes 1 day all-day event."""
    with dtstart_dtend_compat.enable_dtstart_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(SINGLE_DAY_END_TIME_ICS)

    event = calendar.events[0]
    assert event.dtstart == datetime.date(2026, 5, 26)
    assert event.dtend == datetime.date(2026, 5, 27)
    assert event.computed_duration == datetime.timedelta(days=1)


def test_midnight_end_time_compat_mode() -> None:
    """Test event with midnight end time 00:00:00 keeps the date unchanged."""
    with dtstart_dtend_compat.enable_dtstart_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(MIDNIGHT_END_TIME_ICS)

    event = calendar.events[0]
    assert event.dtstart == datetime.date(2026, 5, 26)
    assert event.dtend == datetime.date(2026, 5, 29)
    assert event.computed_duration == datetime.timedelta(days=3)


def test_datetime_start_date_end_same_day_compat_mode() -> None:
    """Test timed start with same-day date end converts to next-day midnight datetime."""
    with dtstart_dtend_compat.enable_dtstart_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(
            DATETIME_START_DATE_END_SAME_DAY_ICS
        )

    event = calendar.events[0]
    assert event.dtstart == datetime.datetime(
        2026, 5, 26, 10, 0, tzinfo=datetime.timezone.utc
    )
    assert event.dtend == datetime.datetime(
        2026, 5, 27, 0, 0, tzinfo=datetime.timezone.utc
    )
    assert event.computed_duration == datetime.timedelta(hours=14)


def test_datetime_start_date_end_next_day_compat_mode() -> None:
    """Test timed start with future date end converts to midnight datetime on that date."""
    with dtstart_dtend_compat.enable_dtstart_dtend_compat():
        calendar = IcsCalendarStream.calendar_from_ics(
            DATETIME_START_DATE_END_NEXT_DAY_ICS
        )

    event = calendar.events[0]
    assert event.dtstart == datetime.datetime(
        2026, 5, 26, 10, 0, tzinfo=datetime.timezone.utc
    )
    assert event.dtend == datetime.datetime(
        2026, 5, 28, 0, 0, tzinfo=datetime.timezone.utc
    )
    assert event.computed_duration == datetime.timedelta(days=1, hours=14)


def test_compat_context_manager() -> None:
    """Test that context manager properly toggles the flag."""
    assert not dtstart_dtend_compat.is_dtstart_dtend_compat_enabled()
    with dtstart_dtend_compat.enable_dtstart_dtend_compat():
        assert dtstart_dtend_compat.is_dtstart_dtend_compat_enabled()
    assert not dtstart_dtend_compat.is_dtstart_dtend_compat_enabled()
