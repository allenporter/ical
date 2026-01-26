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
def test_wkst(wkst: str, expected: list[datetime.datetime | date]) -> None:
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


# ============================================================================
# THISANDFUTURE Tests
# ============================================================================


class TestThisAndFutureTimeline:
    """Tests for RANGE=THISANDFUTURE timeline expansion."""

    def test_thisandfuture_basic(self) -> None:
        """Test basic THISANDFUTURE modification propagates to subsequent instances."""
        from ical.types.recur import Range

        # Create a recurring event
        base_event = Event(
            uid="test-uid",
            summary="Original Event",
            dtstart=datetime.date(2025, 5, 5),
            dtend=datetime.date(2025, 5, 6),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=7"),
            location="Room A",
        )

        # Create a THISANDFUTURE edit for May 8
        edit_event = Event(
            uid="test-uid",
            summary="Modified Event",
            dtstart=datetime.date(2025, 5, 8),
            dtend=datetime.date(2025, 5, 9),
            recurrence_id=RecurrenceId("20250508", range=Range.THIS_AND_FUTURE),
            location="Room B",
        )

        calendar = Calendar(events=[base_event, edit_event])
        events = list(calendar.timeline)

        # Check we have 7 events
        assert len(events) == 7

        # First 3 events should have original properties
        for i, event in enumerate(events[:3]):
            assert event.summary == "Original Event"
            assert event.location == "Room A"
            expected_date = datetime.date(2025, 5, 5) + datetime.timedelta(days=i)
            assert event.dtstart == expected_date

        # Events from May 8 onwards should have modified properties
        for i, event in enumerate(events[3:]):
            assert event.summary == "Modified Event"
            assert event.location == "Room B"
            expected_date = datetime.date(2025, 5, 8) + datetime.timedelta(days=i)
            assert event.dtstart == expected_date

    def test_thisandfuture_with_single_instance_override(self) -> None:
        """Test that single-instance override takes precedence over THISANDFUTURE."""
        from ical.types.recur import Range

        # Create a recurring event
        base_event = Event(
            uid="test-uid",
            summary="Original Event",
            dtstart=datetime.date(2025, 5, 5),
            dtend=datetime.date(2025, 5, 6),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=7"),
        )

        # Create a THISANDFUTURE edit for May 7
        thisandfuture_edit = Event(
            uid="test-uid",
            summary="THISANDFUTURE Modified",
            dtstart=datetime.date(2025, 5, 7),
            dtend=datetime.date(2025, 5, 8),
            recurrence_id=RecurrenceId("20250507", range=Range.THIS_AND_FUTURE),
        )

        # Create a single-instance override for May 9 (should override THISANDFUTURE)
        single_override = Event(
            uid="test-uid",
            summary="Single Instance Override",
            dtstart=datetime.date(2025, 5, 9),
            dtend=datetime.date(2025, 5, 10),
            recurrence_id=RecurrenceId("20250509", range=Range.NONE),
        )

        calendar = Calendar(events=[base_event, thisandfuture_edit, single_override])
        events = list(calendar.timeline)

        assert len(events) == 7

        # May 5-6: Original
        assert events[0].summary == "Original Event"
        assert events[1].summary == "Original Event"

        # May 7-8: THISANDFUTURE modified
        assert events[2].summary == "THISANDFUTURE Modified"
        assert events[3].summary == "THISANDFUTURE Modified"

        # May 9: Single instance override (takes precedence)
        assert events[4].summary == "Single Instance Override"

        # May 10-11: Back to THISANDFUTURE
        assert events[5].summary == "THISANDFUTURE Modified"
        assert events[6].summary == "THISANDFUTURE Modified"

    def test_multiple_thisandfuture_edits(self) -> None:
        """Test that later THISANDFUTURE edits take precedence for their range."""
        from ical.types.recur import Range

        # Create a recurring event
        base_event = Event(
            uid="test-uid",
            summary="Original",
            dtstart=datetime.date(2025, 5, 5),
            dtend=datetime.date(2025, 5, 6),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=10"),
        )

        # First THISANDFUTURE edit for May 7
        edit1 = Event(
            uid="test-uid",
            summary="First Edit",
            dtstart=datetime.date(2025, 5, 7),
            dtend=datetime.date(2025, 5, 8),
            recurrence_id=RecurrenceId("20250507", range=Range.THIS_AND_FUTURE),
        )

        # Second THISANDFUTURE edit for May 10
        edit2 = Event(
            uid="test-uid",
            summary="Second Edit",
            dtstart=datetime.date(2025, 5, 10),
            dtend=datetime.date(2025, 5, 11),
            recurrence_id=RecurrenceId("20250510", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit1, edit2])
        events = list(calendar.timeline)

        assert len(events) == 10

        # May 5-6: Original
        assert events[0].summary == "Original"
        assert events[1].summary == "Original"

        # May 7-9: First Edit applies
        assert events[2].summary == "First Edit"
        assert events[3].summary == "First Edit"
        assert events[4].summary == "First Edit"

        # May 10-14: Second Edit takes precedence
        for event in events[5:]:
            assert event.summary == "Second Edit"

    def test_thisandfuture_with_time_shift(self) -> None:
        """Test that time shifts are applied to subsequent instances."""
        from ical.types.recur import Range

        # Create a recurring event at 9am
        base_event = Event(
            uid="test-uid",
            summary="Morning Meeting",
            dtstart=datetime.datetime(2025, 5, 5, 9, 0),
            dtend=datetime.datetime(2025, 5, 5, 10, 0),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=5"),
        )

        # THISANDFUTURE edit moves May 8 to 2pm (shift of +5 hours)
        edit = Event(
            uid="test-uid",
            summary="Afternoon Meeting",
            dtstart=datetime.datetime(2025, 5, 8, 14, 0),  # 2pm
            dtend=datetime.datetime(2025, 5, 8, 15, 0),
            recurrence_id=RecurrenceId("20250508T090000", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit])
        events = list(calendar.timeline)

        assert len(events) == 5

        # May 5-7: Original time (9am)
        for event in events[:3]:
            assert event.dtstart.hour == 9
            assert event.summary == "Morning Meeting"

        # May 8-9: Shifted to 2pm
        for event in events[3:]:
            assert event.dtstart.hour == 14
            assert event.summary == "Afternoon Meeting"

    def test_thisandfuture_on_first_instance(self) -> None:
        """Test THISANDFUTURE on first instance affects entire series."""
        from ical.types.recur import Range

        base_event = Event(
            uid="test-uid",
            summary="Original",
            dtstart=datetime.date(2025, 5, 5),
            dtend=datetime.date(2025, 5, 6),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=5"),
        )

        # THISANDFUTURE on the very first instance
        edit = Event(
            uid="test-uid",
            summary="Modified All",
            dtstart=datetime.date(2025, 5, 5),
            dtend=datetime.date(2025, 5, 6),
            recurrence_id=RecurrenceId("20250505", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit])
        events = list(calendar.timeline)

        assert len(events) == 5

        # All events should have the modified summary
        for event in events:
            assert event.summary == "Modified All"

    def test_thisandfuture_with_duration_change(self) -> None:
        """Test that duration changes propagate to subsequent instances.

        Per RFC 5545: "if the duration of the given recurrence instance is
        modified, then all subsequent instances are also modified to have
        this same duration."
        """
        from ical.types.recur import Range

        # Create a recurring 1-hour event
        base_event = Event(
            uid="test-uid",
            summary="Meeting",
            dtstart=datetime.datetime(2025, 5, 5, 9, 0),
            dtend=datetime.datetime(2025, 5, 5, 10, 0),  # 1 hour
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=5"),
        )

        # THISANDFUTURE edit changes duration to 2 hours
        edit = Event(
            uid="test-uid",
            summary="Extended Meeting",
            dtstart=datetime.datetime(2025, 5, 8, 9, 0),
            dtend=datetime.datetime(2025, 5, 8, 11, 0),  # 2 hours
            recurrence_id=RecurrenceId("20250508T090000", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit])
        events = list(calendar.timeline)

        assert len(events) == 5

        # May 5-7: Original 1-hour duration
        for event in events[:3]:
            duration = event.dtend - event.dtstart
            assert duration == datetime.timedelta(hours=1)

        # May 8-9: Modified 2-hour duration
        for event in events[3:]:
            duration = event.dtend - event.dtstart
            assert duration == datetime.timedelta(hours=2)

    def test_thisandfuture_with_timezone(self) -> None:
        """Test THISANDFUTURE with timezone-aware datetimes.

        Per RFC 5545: The TZID parameter can be specified on RECURRENCE-ID.
        """
        from ical.types.recur import Range

        tz = zoneinfo.ZoneInfo("America/New_York")

        # Create a recurring event in New York timezone
        base_event = Event(
            uid="test-uid",
            summary="NYC Meeting",
            dtstart=datetime.datetime(2025, 5, 5, 9, 0, tzinfo=tz),
            dtend=datetime.datetime(2025, 5, 5, 10, 0, tzinfo=tz),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=5"),
        )

        # THISANDFUTURE edit (also timezone-aware)
        edit = Event(
            uid="test-uid",
            summary="Modified NYC Meeting",
            dtstart=datetime.datetime(2025, 5, 8, 14, 0, tzinfo=tz),  # 2pm ET
            dtend=datetime.datetime(2025, 5, 8, 15, 0, tzinfo=tz),
            recurrence_id=RecurrenceId("20250508T090000", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit])
        events = list(calendar.timeline)

        assert len(events) == 5

        # May 5-7: Original time (9am ET)
        for event in events[:3]:
            assert event.dtstart.hour == 9
            assert event.summary == "NYC Meeting"

        # May 8-9: Shifted to 2pm ET
        for event in events[3:]:
            assert event.dtstart.hour == 14
            assert event.summary == "Modified NYC Meeting"

    def test_thisandfuture_recurrence_id_matches_original_dtstart(self) -> None:
        """Test that RECURRENCE-ID value must match original DTSTART.

        Per RFC 5545: "The DATE-TIME value is set to the time when the
        original recurrence instance would occur; meaning that if the
        intent is to change a Friday meeting to Thursday, the DATE-TIME
        is still set to the original Friday meeting."
        """
        from ical.types.recur import Range

        # Friday recurring event (May 9, 2025 is a Friday)
        base_event = Event(
            uid="test-uid",
            summary="Friday Meeting",
            dtstart=datetime.date(2025, 5, 9),
            dtend=datetime.date(2025, 5, 10),
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),  # Fridays
        )

        # Move the second Friday (May 16) to Thursday (May 15)
        # RECURRENCE-ID is still 20250516 (the original Friday)
        edit = Event(
            uid="test-uid",
            summary="Moved to Thursday",
            dtstart=datetime.date(2025, 5, 15),  # Thursday
            dtend=datetime.date(2025, 5, 16),
            recurrence_id=RecurrenceId("20250516", range=Range.THIS_AND_FUTURE),
        )

        calendar = Calendar(events=[base_event, edit])
        events = list(calendar.timeline)

        assert len(events) == 3

        # First Friday (May 9) - original
        assert events[0].dtstart == datetime.date(2025, 5, 9)
        assert events[0].summary == "Friday Meeting"

        # Second instance moved to Thursday (May 15)
        assert events[1].dtstart == datetime.date(2025, 5, 15)
        assert events[1].summary == "Moved to Thursday"

        # Third instance also moved (May 22 -> May 21)
        assert events[2].dtstart == datetime.date(2025, 5, 22)
        assert events[2].summary == "Moved to Thursday"
