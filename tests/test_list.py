"""Tests for list view of todo items."""

import datetime

import freezegun
import pytest

from ical.list import todo_list_view
from ical.todo import Todo
from ical.types.recur import Recur


def test_empty_list() -> None:
    """Test an empty list."""
    view = todo_list_view([])
    assert list(view) == []


@pytest.mark.parametrize(
    ("status"),
    [
        ("NEEDS-ACTION"),
        ("IN-PROCESS"),
    ],
)
def test_daily_recurring_item_due_today_incomplete(status: str) -> None:
    """Test a daily recurring item that is due today ."""
    with freezegun.freeze_time("2024-01-10T10:05:00-05:00"):
        todo = Todo(
            dtstart=datetime.date.today() - datetime.timedelta(days=1),
            summary="Daily incomplete",
            due=datetime.date.today(),
            rrule=Recur.from_rrule("FREQ=DAILY"),
            status=status,
        )
        view = list(todo_list_view([todo]))

    assert len(view) == 1
    assert view[0].summary == todo.summary
    assert view[0].dtstart == datetime.date(2024, 1, 10)
    assert view[0].due == datetime.date(2024, 1, 11)
    assert view[0].recurrence_id == "20240110"


@pytest.mark.parametrize(
    ("status"),
    [
        ("NEEDS-ACTION"),
        ("IN-PROCESS"),
    ],
)
def test_daily_recurring_item_due_tomorrow(status: str) -> None:
    """Test a daily recurring item that is due tomorrow."""
    with freezegun.freeze_time("2024-01-10T10:05:00-05:00"):
        todo = Todo(
            dtstart=datetime.date.today(),
            summary="Daily incomplete",
            due=datetime.date.today() + datetime.timedelta(days=1),
            rrule=Recur.from_rrule("FREQ=DAILY"),
            status=status,
        )
        view = list(todo_list_view([todo]))

    assert len(view) == 1
    assert view[0].summary == todo.summary
    assert view[0].dtstart == datetime.date(2024, 1, 10)
    assert view[0].due == datetime.date(2024, 1, 11)
    assert view[0].recurrence_id == "20240110"


@pytest.mark.parametrize(
    ("status"),
    [
        ("NEEDS-ACTION"),
        ("IN-PROCESS"),
    ],
)
def test_daily_recurring_item_due_yesterday(status: str) -> None:
    """Test a daily recurring item that is due yesterday ."""

    with freezegun.freeze_time("2024-01-10T10:05:00-05:00"):
        todo = Todo(
            dtstart=datetime.date.today() - datetime.timedelta(days=1),
            summary="Daily incomplete",
            due=datetime.date.today(),
            rrule=Recur.from_rrule("FREQ=DAILY"),
            status=status,
        )
        view = list(todo_list_view([todo]))

    # The item should be returned with a recurrence_id of today
    assert len(view) == 1
    assert view[0].summary == todo.summary
    assert view[0].dtstart == datetime.date(2024, 1, 10)
    assert view[0].due == datetime.date(2024, 1, 11)
    assert view[0].recurrence_id == "20240110"
    assert view[0].status == status

    with freezegun.freeze_time("2024-01-11T08:05:00-05:00"):
        view = list(todo_list_view([todo]))

    assert len(view) == 1
    assert view[0].summary == todo.summary
    assert view[0].dtstart == datetime.date(2024, 1, 11)
    assert view[0].due == datetime.date(2024, 1, 12)
    assert view[0].recurrence_id == "20240111"
    assert view[0].status == status
