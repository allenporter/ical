"""Tests for timeline related calendar eents."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest
from ical.exceptions import CalendarParseError

from ical.calendar import Calendar
from ical.component import ComponentModel
from ical.exceptions import RecurrenceError
from ical.event import Event
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.parsing.component import parse_content
from ical.timeline import Timeline
from ical.todo import Todo
from ical.types.recur import Frequency, Recur, RecurrenceId, Weekday, WeekdayValue
from ical.recurrence import Recurrences


def test_from_contentlines() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART;TZID=America/New_York:20220802T060000",
            "RRULE:FREQ=DAILY;COUNT=3",
        ]
    )
    assert recurrences.rrule == [
        Recur(
            freq=Frequency.DAILY,
            count=3,
        )
    ]
    assert recurrences.dtstart == datetime.datetime(
        2022, 8, 2, 6, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
    )


def test_from_contentlines_rdate() -> None:
    """Test parsing a recurrence rule with RDATE from a string."""

    lines = [
        "RRULE:FREQ=DAILY;COUNT=3",
        "RDATE;VALUE=DATE:20220803,20220804",
        "IGNORED:20250806",
    ]

    # parse using full ical parser
    content = [
        "BEGIN:RECURRENCE",
        *lines,
        "END:RECURRENCE",
    ]
    component = parse_content("\n".join(content))
    assert component
    orig_recurrences = Recurrences.parse_obj(component[0].as_dict())
    recurrences = Recurrences.from_basic_contentlines(lines)
    assert recurrences.rrule == [
        Recur(
            freq=Frequency.DAILY,
            count=3,
        )
    ]
    assert recurrences.rdate == [
        datetime.date(2022, 8, 3),
        datetime.date(2022, 8, 4),
    ]


@pytest.mark.parametrize("property", ["RDATE", "EXDATE"])
@pytest.mark.parametrize(
    ("date_value", "expected"),
    [
        ("{property}:20220803T060000", [datetime.datetime(2022, 8, 3, 6, 0, 0)]),
        (
            "{property}:20220803T060000,20220804T060000",
            [
                datetime.datetime(2022, 8, 3, 6, 0, 0),
                datetime.datetime(2022, 8, 4, 6, 0, 0),
            ],
        ),
        ("{property}:20220803", [datetime.date(2022, 8, 3)]),
        (
            "{property}:20220803,20220804",
            [datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)],
        ),
        (
            "{property};VALUE=DATE:20220803,20220804",
            [datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)],
        ),
        (
            "{property};VALUE=DATE-TIME:20220803T060000,20220804T060000",
            [
                datetime.datetime(2022, 8, 3, 6, 0, 0),
                datetime.datetime(2022, 8, 4, 6, 0, 0),
            ],
        ),
        (
            "{property}:20220803T060000Z,20220804T060000Z",
            [
                datetime.datetime(2022, 8, 3, 6, 0, 0, tzinfo=datetime.UTC),
                datetime.datetime(2022, 8, 4, 6, 0, 0, tzinfo=datetime.UTC),
            ],
        ),
        (
            "{property};TZID=America/New_York:19980119T020000",
            [
                datetime.datetime(
                    1998, 1, 19, 2, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
                )
            ],
        ),
    ],
)
def test_from_contentlines_date_values(
    property: str, date_value: str, expected: list[datetime.datetime | datetime.date]
) -> None:
    """Test parsing a recurrence rule with RDATE from a string."""
    lines = [
        "RRULE:FREQ=DAILY;COUNT=3",
        date_value.format(property=property),
    ]

    # Parse using full ical parser with a fake component
    content = [
        "BEGIN:RECURRENCE",
        *lines,
        "END:RECURRENCE",
    ]
    # assert content == 'a'
    component = parse_content("\n".join(content))
    assert component
    orig_recurrences = Recurrences.parse_obj(component[0].as_dict())

    # Parse using optimized parser
    recurrences = Recurrences.from_basic_contentlines(lines)

    # Compare both approaches
    assert orig_recurrences == recurrences

    # Additionally assert expected values from test parameters
    assert recurrences.rrule == [
        Recur(
            freq=Frequency.DAILY,
            count=3,
        )
    ]
    attr = property.lower()
    assert getattr(recurrences, attr) == expected


@pytest.mark.parametrize(
    "contentlines",
    [
        ["RRULE;COUNT=3"],
        ["RRULE:COUNT=3;FREQ=invalid"],
        ["EXDATE"],
        ["RDATE"],
        ["RRULE;COUNT=3", "EXDATE"],
        ["EXDATE", "RDATE"],
        ["EXDATE:20220803T060000", "RDATE:"],
    ],
)
def test_from_invalid_contentlines(contentlines: list[str]) -> None:
    """Test parsing content lines that are not valid."""
    with pytest.raises(CalendarParseError):
        Recurrences.from_basic_contentlines(contentlines)


def test_as_rrule() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220802T060000Z",
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE:20220803T060000Z",
        ]
    )
    assert list(recurrences.as_rrule()) == [
        datetime.datetime(2022, 8, 2, 6, 0, 0, tzinfo=datetime.UTC),
        datetime.datetime(2022, 8, 4, 6, 0, 0, tzinfo=datetime.UTC),
    ]


def test_as_rrule_with_rdate() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220801",
            "RDATE:20220803",
            "RDATE:20220804",
            "RDATE:20220805",
        ]
    )
    assert list(recurrences.as_rrule()) == [
        datetime.date(2022, 8, 3),
        datetime.date(2022, 8, 4),
        datetime.date(2022, 8, 5),
    ]


def test_as_rrule_with_date() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE:20220803T060000Z",
        ]
    )
    assert list(recurrences.as_rrule(datetime.datetime(2022, 8, 2, 6, 0, 0, tzinfo=datetime.UTC))) == [
        datetime.datetime(2022, 8, 2, 6, 0, 0, tzinfo=datetime.UTC),
        datetime.datetime(2022, 8, 4, 6, 0, 0, tzinfo=datetime.UTC),
    ]


def test_as_rrule_without_date() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE:20220803T060000Z",
        ]
    )
    with pytest.raises(ValueError, match="dtstart is required"):
        list(recurrences.as_rrule())


def test_rrule_failure() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220802T060000Z",
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE:20220803T060000",
        ]
    )
    with pytest.raises(RecurrenceError, match="can't compare offset-naive"):
        list(recurrences.as_rrule())


def test_ics() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220802T060000Z",
            "RRULE:FREQ=DAILY;COUNT=3",
            "EXDATE:20220803T060000Z",
        ]
    )
    assert recurrences.ics() == [
        "DTSTART:20220802T060000Z",
        "RRULE:FREQ=DAILY;COUNT=3",
        "EXDATE:20220803T060000Z",
    ]



def test_mismatch_date_and_datetime_types() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220801T060000Z",
            "RDATE:20220803",
            "RDATE:20220804T060000Z",
            "RDATE:20220805",
        ]
    )
    with pytest.raises(RecurrenceError):
        list(recurrences.as_rrule())
