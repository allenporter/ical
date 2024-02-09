"""Tests for Todo component."""

from __future__ import annotations

import datetime
import zoneinfo
from typing import Any
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from ical.exceptions import CalendarParseError
from ical.todo import Todo
from ical.types.recur import Recur

_TEST_TZ = datetime.timezone(datetime.timedelta(hours=1))


def test_empty() -> None:
    """Test that in practice a Todo requires no fields."""
    todo = Todo()
    assert not todo.summary


def test_todo() -> None:
    """Test a valid Todo object."""
    todo = Todo(summary="Example", due=datetime.date(2022, 8, 7))
    assert todo.summary == "Example"
    assert todo.due == datetime.date(2022, 8, 7)


def test_duration() -> None:
    """Test relationship between the due and duration fields."""

    todo = Todo(start=datetime.date(2022, 8, 7), duration=datetime.timedelta(days=1))
    assert todo.start
    assert todo.duration

    # Both due and Duration can't be set
    with pytest.raises(CalendarParseError):
        Todo(
            start=datetime.date(2022, 8, 7),
            duration=datetime.timedelta(days=1),
            due=datetime.date(2022, 8, 8),
        )

    # Duration requires start date
    with pytest.raises(CalendarParseError):
        Todo(duration=datetime.timedelta(days=1))

    todo = Todo(start=datetime.date(2022, 8, 7), due=datetime.date(2022, 8, 8))
    assert todo.start
    assert todo.due
    assert todo.start_datetime

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert todo.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"


@pytest.mark.parametrize(
    ("params"),
    [
        ({}),
        (
            {
                "start": datetime.datetime(2022, 9, 6, 6, 0, 0),
            }
        ),
        (
            {
                "due": datetime.datetime(2022, 9, 6, 6, 0, 0),
            }
        ),
        (
            {
                "start": datetime.datetime(2022, 9, 6, 6, 0, 0),
                "due": datetime.datetime(2022, 9, 6, 6, 0, 0),
            }
        ),
        (
            {
                "start": datetime.datetime(2022, 9, 6, 6, 0, 0),
                "due": datetime.datetime(2022, 9, 7, 6, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Regina")),
            }
        ),
        (
            {
                "start": datetime.date(2022, 9, 6),
                "due": datetime.datetime(2022, 9, 7, 6, 0, 0),
            }
        ),
        (
            {
                "start": datetime.datetime(2022, 9, 6, 6, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Regina")),
                "due": datetime.datetime(2022, 9, 7, 6, 0, 0),  # floating
            }
        ),
        (
            {
                "start": datetime.date(2022, 9, 6),
                "due": datetime.date(2022, 9, 6),
            }
        ),
        (
            {
                "duration": datetime.timedelta(hours=1),
            }
        ),
    ],
)
def test_validate_rrule_required_fields(params: dict[str, Any]) -> None:
    """Test that a Todo with an rrule requires a dtstart."""
    with pytest.raises(CalendarParseError):
        todo = Todo(
            summary="Todo 1",
            rrule=Recur.from_rrule("FREQ=WEEKLY;BYDAY=WE,MO,TU,TH,FR;COUNT=3"),
            **params,
        )
        todo.as_rrule()

def test_is_recurring() -> None:
    """Test that a Todo with an rrule requires a dtstart."""
    todo = Todo(
        summary="Todo 1",
        rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        dtstart="2024-02-02",
        due="2024-02-03",
    )
    assert todo.recurring
    assert todo.computed_duration == datetime.timedelta(days=1)
    assert list(todo.as_rrule()) == [
        datetime.date(2024, 2, 2),
        datetime.date(2024, 2, 3),
        datetime.date(2024, 2, 4),
    ]


def test_timestamp_start_due() -> None:
    """Test a timespan of a Todo with a start and due date."""
    todo = Todo(
        summary="Example",
        dtstart=datetime.date(2022, 8, 1),
        due=datetime.date(2022, 8, 7),
    )

    with patch("ical.todo.local_timezone", return_value=zoneinfo.ZoneInfo("CET")):
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-08-01T00:00:00+02:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00+02:00"

    ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-08-01T00:00:00-06:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00-06:00"


def test_timespan_missing_dtstart() -> None:
    """Test a timespan of a Todo without a dtstart."""
    todo = Todo(summary="Example", due=datetime.date(2022, 8, 7))

    with patch("ical.todo.local_timezone", return_value=zoneinfo.ZoneInfo("Pacific/Honolulu")):
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-08-07T00:00:00-10:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00-10:00"

    ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-08-07T00:00:00-06:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00-06:00"


def test_timespan_fallback() -> None:
    """Test a timespan of a Todo with no explicit dtstart and due date"""

    with freeze_time("2022-09-03T09:38:05", tz_offset=10), patch("ical.todo.local_timezone", return_value=zoneinfo.ZoneInfo("Pacific/Honolulu")):
        todo = Todo(summary="Example")
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-09-03T00:00:00-10:00"
    assert ts.end.isoformat() == "2022-09-04T00:00:00-10:00"

    with freeze_time("2022-09-03T09:38:05", tz_offset=10), patch("ical.todo.local_timezone", return_value=zoneinfo.ZoneInfo("Pacific/Honolulu")):
        ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-09-03T00:00:00-06:00"
    assert ts.end.isoformat() == "2022-09-04T00:00:00-06:00"


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (datetime.date(2022, 9, 6), True),
        (datetime.date(2022, 9, 7), True),
        (datetime.date(2022, 9, 8), False),
        (datetime.date(2022, 9, 9), False),
        (datetime.datetime(2022, 9, 7, 6, 0, 0, tzinfo=_TEST_TZ), True),
        (datetime.datetime(2022, 9, 7, 12, 0, 0, tzinfo=_TEST_TZ), False),
        (datetime.datetime(2022, 9, 8, 6, 0, 0, tzinfo=_TEST_TZ), False),
    ],
)
@freeze_time("2022-09-07T09:38:05", tz_offset=1)
def test_is_due(due: datetime.date | datetime.datetime, expected: bool) -> None:
    """Test that a Todo is due."""
    todo = Todo(
        summary="Example",
        due=due,
    )
    assert todo.is_due(tzinfo=_TEST_TZ) == expected


def test_is_due_default_timezone() -> None:
    """Test a Todo is due with the default timezone."""
    todo = Todo(
        summary="Example",
        due=datetime.date(2022, 9, 6),
    )
    assert todo.is_due()
