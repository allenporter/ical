"""Tests for Todo component."""

from __future__ import annotations

import datetime
import zoneinfo
from typing import Any
from unittest.mock import patch

import pytest
from freezegun import freeze_time

from ical.exceptions import CalendarParseError
from ical.todo import Todo
from ical.types.recur import Recur


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
    """Test a timespan of a Todo."""
    todo = Todo(
        summary="Example",
        dtstart=datetime.date(2022, 8, 1),
        due=datetime.date(2022, 8, 7),
    )

    with patch("ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("CET")):
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-08-01T00:00:00+02:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00+02:00"

    ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-08-01T00:00:00-06:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00-06:00"


def test_implicit_timespan() -> None:
    """Test a timespan of a Todo."""
    todo = Todo(summary="Example", due=datetime.date(2022, 8, 7))

    with patch("ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("CET")):
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-08-06T00:00:00+02:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00+02:00"

    ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-08-06T00:00:00-06:00"
    assert ts.end.isoformat() == "2022-08-07T00:00:00-06:00"


def test_timespan_dtstart_fallback() -> None:
    """Test a timespan of a Todo."""

    with freeze_time("2022-09-03T09:38:05"):
        todo = Todo(summary="Example")

    with patch("ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("CET")):
        ts = todo.timespan
    assert ts.start.isoformat() == "2022-09-03T09:38:05+02:00"
    assert ts.end.isoformat() == "2022-09-03T09:38:05+02:00"

    with freeze_time("2022-09-03T09:38:05"):
        ts = todo.timespan_of(zoneinfo.ZoneInfo("America/Regina"))
    assert ts.start.isoformat() == "2022-09-03T09:38:05-07:00"
    assert ts.end.isoformat() == "2022-09-03T09:38:05-07:00"
