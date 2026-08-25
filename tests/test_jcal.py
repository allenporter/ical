"""Tests for RFC 7265 (jCal) model serialization and parsing."""

import datetime
from typing import Any
import pytest

from ical.calendar import Calendar
from ical.calendar_stream import CalendarStream, JcalCalendarStream
from ical.event import Event
from ical.todo import Todo
from ical.exceptions import CalendarParseError

FIXED_DTSTAMP = datetime.datetime(2026, 8, 24, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.mark.parametrize(
    ("calendar", "expected_jcal"),
    [
        # 1. Minimal Calendar envelope
        (
            Calendar(prodid="-//Example Corp.//EN", version="2.0"),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [],
            ],
        ),
        # 2. Calendar with Event (text, date-time, and integer properties)
        (
            Calendar(
                prodid="-//Example Corp.//EN",
                version="2.0",
                vevent=[
                    Event(
                        dtstamp=FIXED_DTSTAMP,
                        uid="event-123",
                        summary="Architecture Review",
                        description="Review jCal design with team",
                        sequence=1,
                    )
                ],
            ),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [
                    [
                        "vevent",
                        [
                            ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                            ["uid", {}, "text", "event-123"],
                            ["summary", {}, "text", "Architecture Review"],
                            ["description", {}, "text", "Review jCal design with team"],
                            ["sequence", {}, "integer", 1],
                        ],
                        [],
                    ]
                ],
            ],
        ),
        # 3. Calendar with Todo and multi-valued text categories
        (
            Calendar(
                prodid="-//Example Corp.//EN",
                version="2.0",
                vtodo=[
                    Todo(
                        dtstamp=FIXED_DTSTAMP,
                        uid="todo-456",
                        summary="Write tests",
                        categories=["Work", "Python"],
                    )
                ],
            ),
            [
                "vcalendar",
                [
                    ["prodid", {}, "text", "-//Example Corp.//EN"],
                    ["version", {}, "text", "2.0"],
                ],
                [
                    [
                        "vtodo",
                        [
                            ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                            ["uid", {}, "text", "todo-456"],
                            ["categories", {}, "text", "Work", "Python"],
                            ["summary", {}, "text", "Write tests"],
                        ],
                        [],
                    ]
                ],
            ],
        ),
    ],
    ids=[
        "minimal_calendar",
        "calendar_with_event",
        "calendar_with_todo_and_categories",
    ],
)
def test_calendar_as_jcal(calendar: Calendar, expected_jcal: list[Any]) -> None:
    """Test serializing Calendar model instances to jCal format."""
    assert calendar.as_jcal() == expected_jcal


def test_jcal_stream_roundtrip() -> None:
    """Test parsing jCal into Calendar model and re-encoding."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["summary", {}, "text", "Architecture Review"],
                    ["description", {}, "text", "Review jCal design with team"],
                    ["sequence", {}, "integer", 1],
                ],
                [],
            ]
        ],
    ]

    cal = JcalCalendarStream.calendar_from_jcal(jcal_input)
    assert cal.prodid == "-//Example Corp.//EN"
    assert cal.version == "2.0"
    assert len(cal.events) == 1
    assert cal.events[0].dtstamp == FIXED_DTSTAMP
    assert cal.events[0].uid == "event-123"
    assert cal.events[0].summary == "Architecture Review"
    assert cal.events[0].description == "Review jCal design with team"
    assert cal.events[0].sequence == 1

    # Re-encode to jCal
    assert JcalCalendarStream.calendar_to_jcal(cal) == jcal_input


def test_ics_to_jcal_model_bridge() -> None:
    """Test reading ICS content and generating jCal output via CalendarStream."""
    ics_content = (
        "BEGIN:VCALENDAR\n"
        "PRODID:-//Example Corp.//EN\n"
        "VERSION:2.0\n"
        "BEGIN:VEVENT\n"
        "DTSTAMP:20260824T120000Z\n"
        "UID:event-123\n"
        "SUMMARY:Meeting with Fred\n"
        "END:VEVENT\n"
        "END:VCALENDAR"
    )

    stream = CalendarStream.from_ics(ics_content)
    jcal_output = stream.jcal()

    assert jcal_output == [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["summary", {}, "text", "Meeting with Fred"],
                ],
                [],
            ]
        ],
    ]


def test_jcal_date_and_extra_properties() -> None:
    """Test parsing and serialization of jCal DATE and extra/extension properties."""
    jcal_input = [
        "vcalendar",
        [
            ["prodid", {}, "text", "-//Example Corp.//EN"],
            ["version", {}, "text", "2.0"],
        ],
        [
            [
                "vevent",
                [
                    ["dtstamp", {}, "date-time", "2026-08-24T12:00:00Z"],
                    ["uid", {}, "text", "event-123"],
                    ["dtstart", {}, "date", "2026-08-24"],
                    ["x-coffee-data", {"origin": "Guinea"}, "unknown", "Stenophylla"],
                ],
                [],
            ]
        ],
    ]

    cal = Calendar.from_jcal(jcal_input)
    assert len(cal.events) == 1
    event = cal.events[0]
    assert event.dtstart == datetime.date(2026, 8, 24)
    assert len(event.extras) == 1
    assert event.extras[0].name == "x-coffee-data"
    assert event.extras[0].value == "Stenophylla"
    assert event.extras[0].params[0].name == "ORIGIN"
    assert event.extras[0].params[0].values == ["Guinea"]

    # Re-encode to jCal
    assert cal.as_jcal() == jcal_input


@pytest.mark.parametrize(
    ("invalid_input", "error_match"),
    [
        ([], "Invalid jCal data"),
        (["vevent", []], "Invalid jCal component structure"),
        (["vevent", "not-a-list", []], "Invalid jCal component properties"),
        (["vevent", [], "not-a-list"], "Invalid jCal component properties"),
        (["vevent", [["summary"]], []], "Invalid jCal property structure"),
    ],
    ids=[
        "empty_stream",
        "missing_subcomponents",
        "properties_not_a_list",
        "subcomponents_not_a_list",
        "property_too_short",
    ],
)
def test_jcal_invalid_structures(invalid_input: list[Any], error_match: str) -> None:
    """Test validation and error handling on malformed jCal structures."""
    with pytest.raises(CalendarParseError, match=error_match):
        CalendarStream.from_jcal(invalid_input)
