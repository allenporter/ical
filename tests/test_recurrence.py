"""Tests for timeline related calendar eents."""

from __future__ import annotations

import datetime
import zoneinfo

import pytest
from ical.exceptions import CalendarParseError

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.component import ComponentModel
from ical.exceptions import RecurrenceError
from ical.event import Event
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.parsing.component import parse_content
from ical.timeline import Timeline
from ical.todo import Todo
from ical.types.recur import Frequency, Recur, RecurrenceId, Weekday, WeekdayValue
from ical.recurrence import Recurrences
from ical.types import Period


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
    orig_recurrences = Recurrences.model_validate(component[0].as_dict())
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
    orig_recurrences = Recurrences.model_validate(component[0].as_dict())

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
    assert list(
        recurrences.as_rrule(
            datetime.datetime(2022, 8, 2, 6, 0, 0, tzinfo=datetime.UTC)
        )
    ) == [
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


@pytest.mark.parametrize(
    ("wkst", "expected"),
    [
        (
            "WKST=MO",
            [
                datetime.datetime(1997, 8, 5, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 10, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 19, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 24, 0, 0, tzinfo=datetime.timezone.utc),
            ],
        ),
        (
            "WKST=SU",
            [
                datetime.datetime(1997, 8, 5, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 17, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 19, 0, 0, tzinfo=datetime.timezone.utc),
                datetime.datetime(1997, 8, 31, 0, 0, tzinfo=datetime.timezone.utc),
            ],
        ),
    ],
)
def test_wkst(wkst: str, expected: list[datetime.datetime | datetime.date]) -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART;TZID=America/New_York:19970805T090000",
            f"RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=4;BYDAY=TU,SU;{wkst}",
        ]
    )
    assert (
        list(
            recurrences.as_rrule(
                datetime.datetime(1997, 8, 5, 0, 0, 0, tzinfo=datetime.UTC)
            )
        )
        == expected
    )


def test_ics_wkst() -> None:
    """Test parsing a recurrence rule from a string."""
    recurrences = Recurrences.from_basic_contentlines(
        [
            "DTSTART:20220802T060000Z",
            "RRULE:FREQ=WEEKLY;COUNT=3;WKST=SU",
        ]
    )
    assert recurrences.ics() == [
        "DTSTART:20220802T060000Z",
        "RRULE:FREQ=WEEKLY;COUNT=3;WKST=SU",
    ]


def test_parse_rdate_period_naive() -> None:
    """Test parsing naive RDATE periods."""
    lines = [
        "DTSTART:19960403T020000",
        "RDATE;VALUE=PERIOD:19960403T020000/19960403T040000,19960404T020000/PT3H",
    ]
    recurrences = Recurrences.from_basic_contentlines(lines)
    assert len(recurrences.rdate) == 2

    p1 = recurrences.rdate[0]
    assert isinstance(p1, Period)
    assert p1.start == datetime.datetime(1996, 4, 3, 2, 0, 0)
    assert p1.end == datetime.datetime(1996, 4, 3, 4, 0, 0)
    assert p1.duration is None
    assert p1.end_value == datetime.datetime(1996, 4, 3, 4, 0, 0)

    p2 = recurrences.rdate[1]
    assert isinstance(p2, Period)
    assert p2.start == datetime.datetime(1996, 4, 4, 2, 0, 0)
    assert p2.end is None
    assert p2.duration == datetime.timedelta(hours=3)
    assert p2.end_value == datetime.datetime(1996, 4, 4, 5, 0, 0)


def test_parse_rdate_period_tzid() -> None:
    """Test parsing RDATE periods with a timezone (TZID)."""
    lines = [
        "DTSTART;TZID=America/New_York:19960403T020000",
        "RDATE;VALUE=PERIOD;TZID=America/New_York:19960403T020000/19960403T040000",
    ]
    recurrences = Recurrences.from_basic_contentlines(lines)
    assert len(recurrences.rdate) == 1

    p1 = recurrences.rdate[0]
    assert isinstance(p1, Period)
    tz = zoneinfo.ZoneInfo("America/New_York")
    assert p1.start == datetime.datetime(1996, 4, 3, 2, 0, 0, tzinfo=tz)
    assert p1.end == datetime.datetime(1996, 4, 3, 4, 0, 0, tzinfo=tz)


def test_rdate_period_serialization() -> None:
    """Test serializing RDATE properties with PERIOD values."""
    event = Event(
        summary="Test Serialization",
        dtstart=datetime.datetime(2022, 8, 7, 9, 0, 0),
        dtend=datetime.datetime(2022, 8, 7, 10, 0, 0),
        rdate=[
            Period(
                start=datetime.datetime(2022, 8, 8, 10, 0, 0),
                end=datetime.datetime(2022, 8, 8, 12, 0, 0),
            )
        ],
    )
    calendar = Calendar(vevent=[event])
    ics_content = IcsCalendarStream.calendar_to_ics(calendar)

    assert "RDATE;VALUE=PERIOD:20220808T100000/20220808T120000" in ics_content


def test_parse_rdate_list_strings() -> None:
    """Test before validator parse_rdate_list with strings."""
    recurrences = Recurrences(
        dtstart=datetime.datetime(2022, 8, 3, 6, 0, 0),
        rdate=[  # type: ignore
            "20220804T100000/20220804T120000",  # Period format
            "20220805T060000Z",  # Datetime format
            "20220806",  # Date format
        ],
    )
    assert len(recurrences.rdate) == 3
    assert isinstance(recurrences.rdate[0], Period)
    assert isinstance(recurrences.rdate[1], datetime.datetime)
    assert isinstance(recurrences.rdate[2], datetime.date)


def test_parse_rdate_mixed() -> None:
    """Test parsing a recurrence rule with mixed RDATE value types."""
    lines = [
        "DTSTART:19960403T020000",
        "RDATE;VALUE=DATE:19960404,19960405",
        "RDATE;VALUE=PERIOD:19960406T020000/PT3H",
        "RDATE:19960407T020000",
    ]
    recurrences = Recurrences.from_basic_contentlines(lines)
    assert len(recurrences.rdate) == 4
    assert isinstance(recurrences.rdate[0], datetime.date)
    assert isinstance(recurrences.rdate[1], datetime.date)
    assert isinstance(recurrences.rdate[2], Period)
    assert isinstance(recurrences.rdate[3], datetime.datetime)
