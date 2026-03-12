"""Tests for the DTSTART/UNTIL type mismatch compatibility module.

Some calendar providers (notably Google Calendar) generate iCalendar files
where DTSTART is a DATE-TIME but RRULE UNTIL is a DATE, violating RFC 5545.
This module tests that the compat mode handles this gracefully.
"""

import datetime
import pathlib

import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import dtstart_until_compat, enable_compat_mode
from ical.exceptions import CalendarParseError

TESTDATA_PATH = pathlib.Path("tests/compat/testdata/")
GOOGLE_MISMATCH_ICS = TESTDATA_PATH / "google_dtstart_until_mismatch.ics"


# Minimal ICS with DTSTART as DATE-TIME and UNTIL as DATE
_DATETIME_DTSTART_DATE_UNTIL_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTART:20231005T090000Z
DTEND:20231005T100000Z
RRULE:FREQ=WEEKLY;UNTIL=20231231
UID:test-dtstart-datetime-until-date@example.com
SUMMARY:Weekly Meeting
END:VEVENT
END:VCALENDAR"""

# ICS with DTSTART as DATE-TIME (with timezone) and UNTIL as DATE
_TZID_DTSTART_DATE_UNTIL_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20231005T090000
DTEND;TZID=America/New_York:20231005T100000
RRULE:FREQ=WEEKLY;UNTIL=20231231
UID:test-tzid-dtstart-until-date@example.com
SUMMARY:Weekly Standup
END:VEVENT
END:VCALENDAR"""

# Valid ICS where both DTSTART and UNTIL are DATE-TIME (no mismatch)
_VALID_DATETIME_UNTIL_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTART:20231005T090000Z
DTEND:20231005T100000Z
RRULE:FREQ=WEEKLY;UNTIL=20231231T235959Z
UID:test-valid-until@example.com
SUMMARY:Weekly Meeting Valid
END:VEVENT
END:VCALENDAR"""

# Google Calendar PRODID ICS with DATE-TIME DTSTART and DATE UNTIL
_GOOGLE_PRODID_MISMATCH_ICS = """BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
BEGIN:VEVENT
DTSTART:20231005T090000Z
DTEND:20231005T100000Z
RRULE:FREQ=WEEKLY;UNTIL=20231231
UID:test-google-mismatch@google.com
SUMMARY:Google Recurring Event
END:VEVENT
END:VCALENDAR"""


def test_dtstart_until_compat_context_manager() -> None:
    """Test that the compat context manager properly enables/disables the mode."""
    assert not dtstart_until_compat.is_dtstart_until_compat_enabled()

    with dtstart_until_compat.enable_dtstart_until_compat():
        assert dtstart_until_compat.is_dtstart_until_compat_enabled()

    assert not dtstart_until_compat.is_dtstart_until_compat_enabled()


def test_dtstart_datetime_until_date_fails_without_compat() -> None:
    """Test that DTSTART DATE-TIME with UNTIL DATE raises an error without compat."""
    with pytest.raises(
        CalendarParseError, match="DTSTART was DATE-TIME but UNTIL was DATE"
    ):
        IcsCalendarStream.calendar_from_ics(_DATETIME_DTSTART_DATE_UNTIL_ICS)


def test_dtstart_datetime_until_date_fails_without_compat_tzid() -> None:
    """Test that DTSTART DATE-TIME (with TZID) with UNTIL DATE raises without compat."""
    with pytest.raises(
        CalendarParseError, match="DTSTART was DATE-TIME but UNTIL was DATE"
    ):
        IcsCalendarStream.calendar_from_ics(_TZID_DTSTART_DATE_UNTIL_ICS)


def test_dtstart_datetime_until_date_compat_utc() -> None:
    """Test that DTSTART DATE-TIME UTC with UNTIL DATE is handled with compat mode."""
    with dtstart_until_compat.enable_dtstart_until_compat():
        calendar = IcsCalendarStream.calendar_from_ics(_DATETIME_DTSTART_DATE_UNTIL_ICS)

    assert calendar is not None
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.rrule is not None
    assert event.rrule.until is not None
    # UNTIL should be converted to a datetime matching DTSTART timezone (UTC)
    assert isinstance(event.rrule.until, datetime.datetime)
    assert event.rrule.until == datetime.datetime(
        2023, 12, 31, 0, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_dtstart_datetime_until_date_compat_tzid() -> None:
    """Test that DTSTART DATE-TIME with TZID and UNTIL DATE is handled with compat mode.

    Per RFC 5545, UNTIL must be in UTC when DTSTART has a timezone. The compat
    mode converts UNTIL DATE to midnight UTC DATE-TIME.
    """
    with dtstart_until_compat.enable_dtstart_until_compat():
        calendar = IcsCalendarStream.calendar_from_ics(_TZID_DTSTART_DATE_UNTIL_ICS)

    assert calendar is not None
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.rrule is not None
    assert event.rrule.until is not None
    # UNTIL should be converted to a UTC datetime (RFC 5545 requires UTC for
    # UNTIL when DTSTART has a timezone)
    assert isinstance(event.rrule.until, datetime.datetime)
    assert event.rrule.until == datetime.datetime(
        2023, 12, 31, 0, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_valid_until_datetime_unaffected_by_compat() -> None:
    """Test that valid RRULE with UNTIL as DATE-TIME is unaffected by compat mode."""
    with dtstart_until_compat.enable_dtstart_until_compat():
        calendar = IcsCalendarStream.calendar_from_ics(_VALID_DATETIME_UNTIL_ICS)

    assert calendar is not None
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.rrule is not None
    assert event.rrule.until is not None
    assert isinstance(event.rrule.until, datetime.datetime)
    assert event.rrule.until == datetime.datetime(
        2023, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc
    )


def test_google_calendar_compat_mode_auto_enabled() -> None:
    """Test that enable_compat_mode auto-enables DTSTART/UNTIL compat for Google Calendar."""
    with enable_compat_mode(_GOOGLE_PRODID_MISMATCH_ICS) as compat_ics:
        assert dtstart_until_compat.is_dtstart_until_compat_enabled()
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert calendar is not None
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.rrule is not None
    assert event.rrule.until is not None
    assert isinstance(event.rrule.until, datetime.datetime)


def test_google_calendar_compat_not_enabled_for_other_prodid() -> None:
    """Test that DTSTART/UNTIL compat is NOT enabled for non-Google calendars."""
    non_google_ics = _GOOGLE_PRODID_MISMATCH_ICS.replace(
        "Google Inc//Google Calendar 70.9054", "Some Other Calendar"
    )
    with enable_compat_mode(non_google_ics):
        assert not dtstart_until_compat.is_dtstart_until_compat_enabled()


def test_google_calendar_ics_file_compat() -> None:
    """Test parsing a Google Calendar ICS file with DTSTART/UNTIL mismatch."""
    ics_content = GOOGLE_MISMATCH_ICS.read_text(encoding="utf-8")
    with enable_compat_mode(ics_content) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert calendar is not None
    assert len(calendar.events) == 1
    event = calendar.events[0]
    assert event.summary == "Weekly Meeting (Google Calendar UNTIL mismatch)"
    assert event.rrule is not None
    assert event.rrule.until is not None
    # UNTIL should have been converted from DATE to DATE-TIME
    assert isinstance(event.rrule.until, datetime.datetime)
    assert event.rrule.until.date() == datetime.date(2023, 12, 31)
