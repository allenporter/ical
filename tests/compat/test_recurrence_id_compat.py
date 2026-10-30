"""Exchange midnight exception identifiers should replace timed occurrences."""

import datetime

import pytest

from ical.calendar_stream import IcsCalendarStream
from ical.compat import enable_compat_mode


def feed(
    recurrence_id: str = "20261030T000000",
    exception_start: str = "20261030T080000",
    rule: str = "FREQ=DAILY;COUNT=5",
    master_start: str = "20261029T080000",
    timezone: str = "America/Chicago",
    extra: str = "",
) -> str:
    """Build synthetic data; no private published-calendar data is included."""
    return f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:Microsoft Exchange Server 2010
BEGIN:VEVENT
UID:series@example.com
DTSTART;TZID={timezone}:{master_start}
DURATION:PT30M
RRULE:{rule}
{extra}SUMMARY:Original
END:VEVENT
BEGIN:VEVENT
UID:series@example.com
RECURRENCE-ID;TZID={timezone}:{recurrence_id}
DTSTART;TZID={timezone}:{exception_start}
DURATION:PT30M
SUMMARY:Exception
END:VEVENT
END:VCALENDAR"""


def occurrences(ics: str, compat: bool = True) -> list[tuple[str, str | None]]:
    """Expand after leaving the parsing context, as Home Assistant does."""
    if compat:
        with enable_compat_mode(ics) as text:
            calendar = IcsCalendarStream.calendar_from_ics(text)
    else:
        calendar = IcsCalendarStream.calendar_from_ics(ics)
    return [(str(e.start), e.summary) for e in calendar.timeline]


def test_midnight_exception() -> None:
    """The overridden instance appears once, with the exception's content."""
    events = occurrences(feed())
    assert len(events) == 5
    assert ("2026-10-30 08:00:00-05:00", "Exception") in events
    assert ("2026-10-30 08:00:00-05:00", "Original") not in events


def test_moved_exception() -> None:
    """Match using RECURRENCE-ID's day, not the moved DTSTART."""
    events = occurrences(feed(exception_start="20261031T120000"))
    assert len(events) == 5
    assert ("2026-10-31 12:00:00-05:00", "Exception") in events
    assert ("2026-10-30 08:00:00-05:00", "Original") not in events


def test_dst_transition() -> None:
    """Use the series' wall-clock time on the exception date across DST."""
    events = occurrences(feed(recurrence_id="20261102T000000"))
    assert len(events) == 5
    assert ("2026-11-02 08:00:00-06:00", "Original") not in events


@pytest.mark.parametrize("compat", [False, True])
def test_valid_identifier(compat: bool) -> None:
    """Valid timed exceptions retain their existing behavior."""
    assert len(occurrences(feed(recurrence_id="20261030T080000"), compat)) == 5


def test_strict_and_other_provider() -> None:
    """The heuristic is opt-in and Exchange-specific; its context is reset."""
    assert len(occurrences(feed(), False)) == 6
    assert (
        len(occurrences(feed().replace("Microsoft Exchange Server 2010", "Other"))) == 6
    )
    assert len(occurrences(feed())) == 5
    assert len(occurrences(feed(), False)) == 6


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rule": "FREQ=HOURLY;COUNT=50"},
        {"rule": "FREQ=DAILY;COUNT=5;BYHOUR=8,12"},
        {"recurrence_id": "20261110T000000"},
        {"recurrence_id": "20261030T010000"},
        {"extra": "RDATE;TZID=America/Chicago:20261030T120000\n"},
        {"master_start": "20261029T000000"},
    ],
)
def test_do_not_guess(kwargs: dict[str, str]) -> None:
    """Preserve ambiguous, non-midnight, and out-of-range identifiers."""
    assert occurrences(feed(**kwargs)) == occurrences(feed(**kwargs), False)


def test_cancelled_exception() -> None:
    """A cancellation suppresses the generated occurrence too."""
    ics = feed().replace("SUMMARY:Exception", "STATUS:CANCELLED\nSUMMARY:Exception")
    with enable_compat_mode(ics) as text:
        calendar = IcsCalendarStream.calendar_from_ics(text)
    events = list(calendar.timeline)
    assert len(events) == 5
    assert sum(e.status == "CANCELLED" for e in events) == 1


def test_all_day_unchanged() -> None:
    """All-day recurrence identifiers are not interpreted as timed exceptions."""
    ics = feed().replace(";TZID=America/Chicago", ";VALUE=DATE")
    ics = ics.replace("20261029T080000", "20261029").replace(
        "20261030T080000", "20261030"
    )
    ics = ics.replace("20261030T000000", "20261030").replace("PT30M", "P1D")
    assert occurrences(ics) == occurrences(ics, False)


def test_multiple_masters_unchanged() -> None:
    """Do not choose between multiple masters sharing a UID."""
    ics = feed()
    master = ics.split("BEGIN:VEVENT", 1)[1].split("END:VEVENT", 1)[0]
    ics = ics.replace("END:VCALENDAR", f"BEGIN:VEVENT{master}END:VEVENT\nEND:VCALENDAR")
    assert occurrences(ics) == occurrences(ics, False)


def test_different_timezone_unchanged() -> None:
    """Do not reinterpret midnight in a different timezone."""
    ics = feed().replace(
        "RECURRENCE-ID;TZID=America/Chicago", "RECURRENCE-ID;TZID=America/New_York"
    )
    assert occurrences(ics) == occurrences(ics, False)


def test_excluded_occurrence() -> None:
    """An explicit EXDATE already removes the original; retain the exception."""
    ics = feed(extra="EXDATE;TZID=America/Chicago:20261030T080000\n")
    assert len(occurrences(ics)) == 5
