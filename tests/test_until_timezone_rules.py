"""A naive UNTIL against a timezone-aware DTSTART (#70).

rfc5545 section 3.3.10 requires UNTIL in UTC when DTSTART carries a timezone.
A naive UNTIL used to validate cleanly and then fail much later, inside the
recurrence iterator, with an error that names neither the event nor the rule.
"""

import datetime
import zoneinfo

import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import enable_compat_mode
from ical.exceptions import CalendarParseError

UTC = datetime.timezone.utc
DENVER = zoneinfo.ZoneInfo("America/Denver")

_GOOGLE = "-//Google Inc//Google Calendar 70.9054//EN"


def _ics(dtstart: str, until: str, prodid: str = "-//Example//Example//EN") -> str:
    return f"""BEGIN:VCALENDAR
PRODID:{prodid}
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
{dtstart}
RRULE:FREQ=DAILY;UNTIL={until}
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""


def _until(calendar) -> datetime.datetime | datetime.date:
    """Read UNTIL off the first event, asserting the rule survived parsing."""
    rrule = calendar.events[0].rrule
    assert rrule is not None
    assert rrule.until is not None
    return rrule.until


def _occurrences(calendar) -> list[datetime.datetime]:
    return [
        event.start
        for event in calendar.timeline.included(
            datetime.datetime(2025, 7, 1, tzinfo=UTC),
            datetime.datetime(2025, 8, 1, tzinfo=UTC),
        )
    ]


def test_naive_until_against_utc_dtstart_is_rejected() -> None:
    """It was accepted, then blew up on iteration instead."""
    with pytest.raises(CalendarParseError, match="UNTIL must be specified in UTC"):
        IcsCalendarStream.calendar_from_ics(
            _ics("DTSTART:20250715T140000Z", "20250718T140000")
        )


def test_naive_until_against_a_tzid_dtstart_is_rejected() -> None:
    """A TZID reference is timezone-aware too, so the same rule applies."""
    with pytest.raises(CalendarParseError, match="UNTIL must be specified in UTC"):
        IcsCalendarStream.calendar_from_ics(
            _ics("DTSTART;TZID=America/Denver:20250715T140000", "20250718T140000")
        )


def test_compat_reads_a_naive_until_as_utc() -> None:
    """Producers that omit the Z mean UTC; the calendar should still work."""
    ics = _ics("DTSTART:20250715T140000Z", "20250718T140000", _GOOGLE)

    with enable_compat_mode(ics) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=UTC)
    assert len(_occurrences(calendar)) == 4


def test_a_conforming_calendar_is_untouched() -> None:
    """The valid case has to keep working, or this trades one break for another."""
    ics = _ics("DTSTART:20250715T140000Z", "20250718T140000Z")

    calendar = IcsCalendarStream.calendar_from_ics(ics)

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=UTC)
    assert len(_occurrences(calendar)) == 4


def test_a_floating_dtstart_still_takes_a_floating_until() -> None:
    """Both naive is the other legal combination, and must not be caught."""
    ics = _ics("DTSTART:20250715T140000", "20250718T140000")

    calendar = IcsCalendarStream.calendar_from_ics(ics)

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0)


def test_compat_leaves_a_conforming_until_alone() -> None:
    """Compat must not rewrite what was already correct."""
    ics = _ics("DTSTART:20250715T140000Z", "20250718T140000Z", _GOOGLE)

    with enable_compat_mode(ics) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    assert _until(calendar) == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=UTC)


TODO_ICS = """BEGIN:VCALENDAR
PRODID:{prodid}
VERSION:2.0
BEGIN:VTODO
DTSTAMP:20250715T100000Z
UID:1
SUMMARY:Water the plants
DTSTART:20250715T140000Z
DUE:20250715T150000Z
RRULE:FREQ=DAILY;UNTIL={until}
END:VTODO
END:VCALENDAR
"""


def test_the_rule_applies_to_a_todo_as_well() -> None:
    """`validate_until_dtstart` is shared by VEVENT, VTODO and VJOURNAL."""
    with pytest.raises(CalendarParseError, match="UNTIL must be specified in UTC"):
        IcsCalendarStream.calendar_from_ics(
            TODO_ICS.format(prodid="-//Example//Example//EN", until="20250718T140000")
        )


def test_compat_reads_a_todo_until_as_utc_too() -> None:
    ics = TODO_ICS.format(prodid=_GOOGLE, until="20250718T140000")

    with enable_compat_mode(ics) as compat_ics:
        calendar = IcsCalendarStream.calendar_from_ics(compat_ics)

    rrule = calendar.todos[0].rrule
    assert rrule is not None
    assert rrule.until == datetime.datetime(2025, 7, 18, 14, 0, tzinfo=UTC)


RECUR_DATE_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
{dtstart}
RRULE:FREQ=DAILY;COUNT=3
{recur_date}
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""


def _recur_occurrences(dtstart: str, recur_date: str) -> list[datetime.datetime]:
    calendar = IcsCalendarStream.calendar_from_ics(
        RECUR_DATE_ICS.format(dtstart=dtstart, recur_date=recur_date)
    )
    return _occurrences(calendar)


def test_a_naive_exdate_against_an_aware_dtstart_still_excludes() -> None:
    """It raised RecurrenceError out of the iterator instead of excluding."""
    occurrences = _recur_occurrences(
        "DTSTART:20250715T140000Z", "EXDATE:20250716T140000"
    )

    assert occurrences == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=UTC),
        datetime.datetime(2025, 7, 17, 14, 0, tzinfo=UTC),
    ]


def test_a_naive_exdate_against_a_tzid_dtstart() -> None:
    """A TZID reference is aware too, so it hit the same failure."""
    occurrences = _recur_occurrences(
        "DTSTART;TZID=America/Denver:20250715T140000", "EXDATE:20250716T140000"
    )

    assert [occurrence.date() for occurrence in occurrences] == [
        datetime.date(2025, 7, 15),
        datetime.date(2025, 7, 17),
    ]


def test_a_naive_rdate_against_an_aware_dtstart_still_adds() -> None:
    """RDATE took the whole expansion down the same way EXDATE did."""
    occurrences = _recur_occurrences(
        "DTSTART:20250715T140000Z", "RDATE:20250720T140000"
    )

    assert datetime.datetime(2025, 7, 20, 14, 0, tzinfo=UTC) in occurrences


def test_an_aware_exdate_against_a_naive_dtstart() -> None:
    """The mirror case, which happened to work; it must keep working."""
    occurrences = _recur_occurrences(
        "DTSTART:20250715T140000", "EXDATE:20250716T140000Z"
    )

    assert len(occurrences) == 2


def test_a_conforming_exdate_is_untouched() -> None:
    """Matching awareness must not be rewritten."""
    occurrences = _recur_occurrences(
        "DTSTART:20250715T140000Z", "EXDATE:20250716T140000Z"
    )

    assert occurrences == [
        datetime.datetime(2025, 7, 15, 14, 0, tzinfo=UTC),
        datetime.datetime(2025, 7, 17, 14, 0, tzinfo=UTC),
    ]


def test_an_exdate_in_another_zone_still_matches_by_instant() -> None:
    """A different TZID is legal and already worked; it compares absolutely."""
    occurrences = _recur_occurrences(
        "DTSTART:20250715T140000Z", "EXDATE;TZID=America/Denver:20250716T080000"
    )

    assert len(occurrences) == 2
