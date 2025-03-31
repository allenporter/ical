"""Tests for timeline related calendar events."""

from collections.abc import Generator
import itertools
import json
import textwrap
import pathlib

import pytest
from syrupy import SnapshotAssertion

from ical.exceptions import CalendarParseError
from ical.calendar_stream import CalendarStream, IcsCalendarStream
from ical.store import TodoStore

MAX_ITERATIONS = 30
TESTDATA_PATH = pathlib.Path("tests/testdata/")
TESTDATA_FILES = list(TESTDATA_PATH.glob("*.ics"))
TESTDATA_IDS = [x.stem for x in TESTDATA_FILES]


def test_empty_ics(mock_prodid: Generator[None, None, None]) -> None:
    """Test serialization of an empty ics file."""
    calendar = IcsCalendarStream.calendar_from_ics("")
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert ics == textwrap.dedent(
        """\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.3
            VERSION:2.0
            END:VCALENDAR"""
    )

    calendar.prodid = "-//example//1.2.4"
    ics = IcsCalendarStream.calendar_to_ics(calendar)
    assert ics == textwrap.dedent(
        """\
            BEGIN:VCALENDAR
            PRODID:-//example//1.2.4
            VERSION:2.0
            END:VCALENDAR"""
    )


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_parse(
    filename: pathlib.Path, snapshot: SnapshotAssertion, json_encoder: json.JSONEncoder
) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(filename.read_text())
    data = json.loads(
        cal.json(exclude_unset=True, exclude_none=True, encoder=json_encoder.default)
    )
    assert snapshot == data

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


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_serialize(filename: pathlib.Path, snapshot: SnapshotAssertion) -> None:
    """Fixture to read golden file and compare to golden output."""
    with filename.open() as f:
        cal = IcsCalendarStream.from_ics(f.read())
    assert cal.ics() == snapshot


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_timeline_iteration(filename: pathlib.Path) -> None:
    """Fixture to ensure all calendar events are valid and support iteration."""
    with filename.open() as f:
        cal = IcsCalendarStream.from_ics(f.read())
    for calendar in cal.calendars:
        # Iterate over the timeline to ensure events are valid. There is a max
        # to handle recurring events that may repeat forever.
        for event in itertools.islice(calendar.timeline, MAX_ITERATIONS):
            assert event is not None


@pytest.mark.parametrize("filename", TESTDATA_FILES, ids=TESTDATA_IDS)
def test_todo_list_iteration(filename: pathlib.Path) -> None:
    """Fixture to read golden file and compare to golden output."""
    cal = CalendarStream.from_ics(filename.read_text())
    if not cal.calendars:
        return
    calendar = cal.calendars[0]
    tl = TodoStore(calendar).todo_list()
    for todo in itertools.islice(tl, MAX_ITERATIONS):
        assert todo is not None


def test_invalid_ics() -> None:
    """Test parsing failures for ics content."""
    with pytest.raises(CalendarParseError, match="^Failed to parse calendar contents"):
        IcsCalendarStream.calendar_from_ics("invalid")


def test_component_failure() -> None:
    with pytest.raises(
        CalendarParseError,
        match="^Failed to parse calendar EVENT component: Unexpected dtstart value '2022-07-24 12:00:00' was datetime but dtend value '2022-07-24' was not datetime$",
    ):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent(
                """\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                BEGIN:VEVENT
                DTSTART:20220724T120000
                DTEND:20220724
                END:VEVENT
                END:VCALENDAR
            """
            )
        )


def test_multiple_calendars() -> None:
    with pytest.raises(CalendarParseError, match="more than one calendar"):
        IcsCalendarStream.calendar_from_ics(
            textwrap.dedent(
                """\
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
                BEGIN:VCALENDAR
                PRODID:-//example//1.2.3
                VERSION:2.0
                END:VCALENDAR
            """
            )
        )
