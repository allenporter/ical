"""The BYxxx rule parts that were parsed but never applied.

rfc5545 section 3.3.10 defines fourteen recurrence rule parts. Five of them
were carried through the model and re-serialised without ever reaching the
expansion, so an event fired at whatever `DTSTART` happened to say and the
file round-tripped unchanged.

Each case is asserted against `dateutil.rrule` given the same arguments,
rather than against a hand-written list: the expansion engine is the same
one the library uses, so a hand-written expectation would only restate what
the implementation does.
"""

import datetime

import pytest
from dateutil import rrule as dateutil_rrule

from ical.calendar_stream import IcsCalendarStream
from ical.exceptions import CalendarParseError

UTC = datetime.timezone.utc
DTSTART = datetime.datetime(2025, 7, 15, 14, 0, tzinfo=UTC)

_ICS = """BEGIN:VCALENDAR
PRODID:-//Example//Example//EN
VERSION:2.0
BEGIN:VEVENT
DTSTAMP:20250715T100000Z
UID:1
DTSTART:20250715T140000Z
DTEND:20250715T150000Z
{rule}
SUMMARY:Standup
END:VEVENT
END:VCALENDAR
"""


def _occurrences(rule: str) -> list[datetime.datetime]:
    """Expand the rule. Every case here uses a DATE-TIME DTSTART."""
    calendar = IcsCalendarStream.calendar_from_ics(_ICS.format(rule=rule))
    occurrences = []
    for event in calendar.timeline.included(
        datetime.datetime(2025, 1, 1, tzinfo=UTC),
        datetime.datetime(2026, 12, 31, tzinfo=UTC),
    ):
        assert isinstance(event.start, datetime.datetime)
        occurrences.append(event.start)
    return occurrences


def _rrule_line(rule: str) -> str:
    calendar = IcsCalendarStream.calendar_from_ics(_ICS.format(rule=rule))
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    return next(line for line in ics.splitlines() if line.startswith("RRULE"))


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (
            "RRULE:FREQ=DAILY;COUNT=3;BYHOUR=9,17",
            dateutil_rrule.rrule(
                dateutil_rrule.DAILY, dtstart=DTSTART, count=3, byhour=(9, 17)
            ),
        ),
        (
            "RRULE:FREQ=HOURLY;COUNT=4;BYMINUTE=0,30",
            dateutil_rrule.rrule(
                dateutil_rrule.HOURLY, dtstart=DTSTART, count=4, byminute=(0, 30)
            ),
        ),
        (
            "RRULE:FREQ=MINUTELY;COUNT=3;BYSECOND=0,30",
            dateutil_rrule.rrule(
                dateutil_rrule.MINUTELY, dtstart=DTSTART, count=3, bysecond=(0, 30)
            ),
        ),
        (
            "RRULE:FREQ=YEARLY;COUNT=2;BYYEARDAY=200",
            dateutil_rrule.rrule(
                dateutil_rrule.YEARLY, dtstart=DTSTART, count=2, byyearday=(200,)
            ),
        ),
        (
            "RRULE:FREQ=YEARLY;COUNT=2;BYWEEKNO=30;BYDAY=MO",
            dateutil_rrule.rrule(
                dateutil_rrule.YEARLY,
                dtstart=DTSTART,
                count=2,
                byweekno=(30,),
                byweekday=dateutil_rrule.MO,
            ),
        ),
    ],
    ids=["byhour", "byminute", "bysecond", "byyearday", "byweekno"],
)
def test_by_part_is_applied(rule: str, expected: dateutil_rrule.rrule) -> None:
    """Each part must change the expansion, not merely survive parsing."""
    assert _occurrences(rule) == list(expected)


def test_byhour_moves_the_time_off_dtstart() -> None:
    """The failure this fixes, stated directly: 14:00 was returned for all three."""
    occurrences = _occurrences("RRULE:FREQ=DAILY;COUNT=3;BYHOUR=9,17")

    assert [occurrence.hour for occurrence in occurrences] == [17, 9, 17]


def test_byyearday_moves_the_date_off_dtstart() -> None:
    """Day 200 of 2025 is 19 July; DTSTART is the 15th."""
    (first, _) = _occurrences("RRULE:FREQ=YEARLY;COUNT=2;BYYEARDAY=200")

    assert first.date() == datetime.date(2025, 7, 19)


@pytest.mark.parametrize(
    "rule",
    [
        "RRULE:FREQ=DAILY;COUNT=3;BYHOUR=9,17",
        "RRULE:FREQ=HOURLY;COUNT=4;BYMINUTE=0,30",
        "RRULE:FREQ=MINUTELY;COUNT=3;BYSECOND=0,30",
        "RRULE:FREQ=YEARLY;COUNT=2;BYYEARDAY=200",
    ],
    ids=["byhour", "byminute", "bysecond", "byyearday"],
)
def test_the_part_survives_serialisation(rule: str) -> None:
    """These round-tripped before the fix, and must keep doing so."""
    assert _rrule_line(rule) == rule


def test_a_rule_without_these_parts_is_unchanged() -> None:
    """Adding five optional fields must not alter existing output."""
    rule = "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=TU,TH"

    assert _rrule_line(rule) == rule
    assert len(_occurrences(rule)) == 3


def test_negative_byyearday_counts_from_the_end() -> None:
    """rfc5545 allows -1 to -366; -1 is 31 December."""
    (first,) = _occurrences("RRULE:FREQ=YEARLY;COUNT=1;BYYEARDAY=-1")

    assert first.date() == datetime.date(2025, 12, 31)


@pytest.mark.parametrize(
    "rule",
    [
        "RRULE:FREQ=DAILY;COUNT=1;BYHOUR=24",
        "RRULE:FREQ=DAILY;COUNT=1;BYMINUTE=-5",
        "RRULE:FREQ=YEARLY;COUNT=1;BYYEARDAY=0",
        "RRULE:FREQ=YEARLY;COUNT=1;BYWEEKNO=99",
    ],
    ids=["byhour", "byminute", "byyearday", "byweekno"],
)
def test_out_of_range_is_rejected_at_parse_time(rule: str) -> None:
    """dateutil raises on these during expansion, which is far from the cause.

    Rejecting here matches what `by_month_day` and `by_setpos` already do.
    """
    with pytest.raises(CalendarParseError):
        IcsCalendarStream.calendar_from_ics(_ICS.format(rule=rule))


def test_a_leap_second_is_accepted() -> None:
    """rfc5545 allows BYSECOND=60; dateutil does not, so it folds onto 59."""
    (occurrence,) = _occurrences("RRULE:FREQ=MINUTELY;COUNT=1;BYSECOND=60")

    assert occurrence.second == 59
