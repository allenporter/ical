"""Tests for Todo component."""

from __future__ import annotations

import datetime
import zoneinfo
from unittest.mock import patch

import pytest
try:
    from pydantic.v1 import ValidationError
except ImportError:
    from pydantic import ValidationError

from ical.todo import Todo


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
    with pytest.raises(ValidationError):
        Todo(
            start=datetime.date(2022, 8, 7),
            duration=datetime.timedelta(days=1),
            due=datetime.date(2022, 8, 8),
        )

    # Duration requires start date
    with pytest.raises(ValidationError):
        Todo(duration=datetime.timedelta(days=1))

    todo = Todo(start=datetime.date(2022, 8, 7), due=datetime.date(2022, 8, 8))
    assert todo.start
    assert todo.due
    assert todo.start_datetime

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ):
        assert todo.start_datetime.isoformat() == "2022-08-07T06:00:00+00:00"
