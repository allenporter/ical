"""Tests for timeline related calendar events."""

from collections.abc import Generator
import itertools
import json
import textwrap

import pytest
from pytest_golden.plugin import GoldenTestFixture

from ical.exceptions import CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream

MAX_ITERATIONS = 30


def test_empty_ics(mock_prodid: Generator[None, None, None]) -> None:
    """Test serialization of an empty ics file."""
    calendar = IcsCalendarStream.calendar_from_ics("")
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert (
        ics
        == textwrap.dedent("""\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.3
            VERSION:2.0
            END:VCALENDAR"""
    ))

    calendar.prodid = "-//example//1.2.4"
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert (
        ics
        == textwrap.dedent("""\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.4
            VERSION:2.0
            END:VCALENDAR""")
    )


@pytest.mark.golden_test("testdata/*.yaml")
def test_parse(golden: GoldenTestFixture, json_encoder: json.JSONEncoder) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(golden["input"])
    data = json.loads(
        cal.json(exclude_unset=True, exclude_none=True, encoder=json_encoder.default)
    )
    assert data == golden.out["output"]

    # Re-parse the data object to verify we get the original data values
    # back. This effectively confirms that all fields can be parsed from the
    # python native format in addition to rfc5545.
    cal_reparsed = CalendarStream.parse_obj(data)
    data_reparsed = json.loads(
        cal_reparsed.json(
            exclude_unset=True, exclude_none=True, encoder=json_encoder.default
        )
    )
    assert data_reparsed == data


@pytest.mark.golden_test("testdata/*.yaml")
def test_serialize(golden: GoldenTestFixture) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = IcsCalendarStream.from_ics(golden["input"])
    assert cal.ics() == golden.get("encoded", golden["input"])


@pytest.mark.golden_test("testdata/*.yaml")
def test_iteration(golden: GoldenTestFixture) -> None:
    """Fixture to ensure all calendar events are valid and support iteration."""
    cal = IcsCalendarStream.from_ics(golden["input"])
    for calendar in cal.calendars:
        # Iterate over the timeline to ensure events are valid. There is a max
        # to handle recurring events that may repeat forever.
        for event in itertools.islice(calendar.timeline, MAX_ITERATIONS):
            assert event is not None


def test_invalid_ics() -> None:
    """Test parsing failures for ics content."""
    with pytest.raises(CalendarParseError, match="Failed to parse calendar stream"):
        IcsCalendarStream.calendar_from_ics("invalid")


def test_component_failure() -> None:
    with pytest.raises(CalendarParseError, match="Failed to parse component"):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent("""\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                BEGIN:VEVENT
                DTSTART:20220724T120000
                DTEND:20220724
                END:VEVENT
                END:VCALENDAR
            """))
        

def test_multiple_calendars() -> None:
    with pytest.raises(CalendarParseError, match="more than one calendar"):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent("""\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
            """))