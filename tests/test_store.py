"""Tests for the event store."""

# pylint: disable=too-many-lines

from __future__ import annotations

import datetime
import zoneinfo
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import patch

import pytest
from freezegun import freeze_time
from freezegun.api import FrozenDateTimeFactory

from ical.calendar import Calendar
from ical.event import Event
from ical.todo import Todo
from ical.store import EventStore, TodoStore, StoreError
from ical.types.recur import Range, Recur


@pytest.fixture(name="calendar")
def mock_calendar() -> Calendar:
    """Fixture to create a calendar."""
    return Calendar()


@pytest.fixture(name="store")
def mock_store(calendar: Calendar) -> EventStore:
    """Fixture to create an event store."""
    return EventStore(calendar)


@pytest.fixture(name="todo_store")
def mock_todo_store(calendar: Calendar) -> TodoStore:
    """Fixture to create an event store."""
    return TodoStore(calendar)


@pytest.fixture(name="_uid", autouse=True)
def mock_uid() -> Generator[None, None, None]:
    """Patch out uuid creation with a fixed value."""
    counter = 0

    def func() -> str:
        nonlocal counter
        counter += 1
        return f"mock-uid-{counter}"

    with patch("ical.event.uid_factory", new=func), patch(
        "ical.todo.uid_factory", new=func
    ):
        yield


def compact_dict(data: dict[str, Any], keys: set[str] | None = None) -> dict[str, Any]:
    """Convert pydantic dict values to text."""
    for key, value in list(data.items()):
        if value is None or isinstance(value, list) and not value or value == "":
            del data[key]
        elif keys and key not in keys:
            del data[key]
        elif isinstance(value, datetime.datetime):
            data[key] = value.isoformat()
        elif isinstance(value, datetime.date):
            data[key] = value.isoformat()
    return data


@pytest.fixture(name="fetch_events")
def mock_fetch_events(
    calendar: Calendar,
) -> Callable[..., list[dict[str, Any]]]:
    """Fixture to return events on the calendar."""

    def _func(keys: set[str] | None = None) -> list[dict[str, Any]]:
        return [compact_dict(event.dict(), keys) for event in calendar.timeline]

    return _func


@pytest.fixture(name="fetch_todos")
def mock_fetch_todos(
    calendar: Calendar,
) -> Callable[..., list[dict[str, Any]]]:
    """Fixture to return todos on the calendar."""

    def _func(keys: set[str] | None = None) -> list[dict[str, Any]]:
        return [compact_dict(todo.dict(), keys) for todo in calendar.todos]

    return _func


@pytest.fixture(name="frozen_time", autouse=True)
def mock_frozen_time() -> Generator[FrozenDateTimeFactory, None, None]:
    """Fixture to freeze time to a specific point."""
    with freeze_time("2022-09-03T09:38:05") as freeze:
        with patch("ical.event.dtstamp_factory", new=freeze):
            yield freeze


def test_empty_store(fetch_events: Callable[..., list[dict[str, Any]]]) -> None:
    """Test iteration over an empty calendar."""
    assert fetch_events() == []


def test_add_and_delete_event(
    store: EventStore, fetch_events: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events() == [
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "dtstart": "2022-08-29T09:00:00",
            "dtend": "2022-08-29T09:30:00",
            "summary": "Monday meeting",
            "sequence": 0,
        },
    ]
    store.delete("mock-uid-1")
    assert fetch_events() == []


def test_edit_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing an event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events() == [
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "dtstart": "2022-08-29T09:00:00",
            "dtend": "2022-08-29T09:30:00",
            "summary": "Monday meeting",
            "sequence": 0,
        },
    ]

    frozen_time.tick(delta=datetime.timedelta(seconds=10))

    # Set event start time 5 minutes later
    store.edit(
        "mock-uid-1",
        Event(start="2022-08-29T09:05:00", summary="Monday meeting (Delayed)"),
    )
    assert fetch_events() == [
        {
            "dtstamp": "2022-09-03T09:38:15",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "dtstart": "2022-08-29T09:05:00",
            "dtend": "2022-08-29T09:30:00",
            "summary": "Monday meeting (Delayed)",
            "sequence": 1,
            "last_modified": "2022-09-03T09:38:15",
        },
    ]


def test_edit_event_invalid_uid(store: EventStore) -> None:
    """Edit an event that does not exist."""
    with pytest.raises(StoreError, match="No existing"):
        store.edit("mock-uid-1", Event(start="2022-08-29T09:05:00", summary="Delayed"))


@pytest.mark.parametrize(
    ("start", "end", "recur", "results"),
    [
        (
            datetime.datetime(2022, 8, 29, 9, 0),
            datetime.datetime(2022, 8, 29, 9, 30),
            Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
            [
                "2022-08-29T09:00:00",
                "2022-09-05T09:00:00",
                "2022-09-12T09:00:00",
                "2022-09-19T09:00:00",
                "2022-09-26T09:00:00",
            ],
        ),
        (
            datetime.datetime(2022, 8, 29, 9, 0),
            datetime.datetime(2022, 8, 29, 9, 30),
            Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
            [
                "2022-08-29T09:00:00",
                "2022-09-05T09:00:00",
                "2022-09-12T09:00:00",
                "2022-09-19T09:00:00",
                "2022-09-26T09:00:00",
            ],
        ),
        (
            datetime.datetime(
                2022, 8, 29, 9, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            datetime.datetime(
                2022, 8, 29, 9, 30, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
            [
                "2022-08-29T09:00:00-07:00",
                "2022-09-05T09:00:00-07:00",
                "2022-09-12T09:00:00-07:00",
                "2022-09-19T09:00:00-07:00",
                "2022-09-26T09:00:00-07:00",
            ],
        ),
    ],
)
def test_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    start: datetime.datetime,
    end: datetime.datetime,
    recur: Recur,
    results: list[str],
) -> None:
    """Test adding a recurring event and deleting the entire series."""
    store.add(
        Event(
            summary="Monday meeting",
            start=start,
            end=end,
            rrule=recur,
        )
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": results[0],
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220905T090000",
            "dtstart": results[1],
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912T090000",
            "dtstart": results[2],
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220919T090000",
            "dtstart": results[3],
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220926T090000",
            "dtstart": results[4],
            "summary": "Monday meeting",
        },
    ]
    store.delete("mock-uid-1")
    assert fetch_events(None) == []


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_deletel_partial_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and deleting part of the series."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    store.delete(uid="mock-uid-1", recurrence_id="20220905T090000")
    store.delete(uid="mock-uid-1", recurrence_id="20220919T090000")
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912T090000",
            "dtstart": "2022-09-12T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220926T090000",
            "dtstart": "2022-09-26T09:00:00",
            "summary": "Monday meeting",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_delete_this_and_future_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and deleting events after one event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    store.delete(
        uid="mock-uid-1",
        recurrence_id="20220919T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220905T090000",
            "dtstart": "2022-09-05T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912T090000",
            "dtstart": "2022-09-12T09:00:00",
            "summary": "Monday meeting",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_delete_this_and_future_all_day_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and deleting events after one event."""
    store.add(
        Event(
            summary="Mondays",
            start="2022-08-29",
            end="2022-08-30",
            rrule=recur,
        )
    )
    store.delete(
        uid="mock-uid-1",
        recurrence_id="20220919",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829",
            "dtstart": "2022-08-29",
            "summary": "Mondays",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220905",
            "dtstart": "2022-09-05",
            "summary": "Mondays",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912",
            "dtstart": "2022-09-12",
            "summary": "Mondays",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_delete_this_and_future_event_with_first_instance(
    calendar: Calendar,
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test deleting this and future for the first instance."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    assert len(calendar.events) == 1
    store.delete(
        uid="mock-uid-1",
        recurrence_id="20220829T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == []
    assert len(calendar.events) == 0


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_delete_this_and_future_all_day_event_with_first_instance(
    calendar: Calendar,
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test deleting this and future for the first instance."""
    store.add(
        Event(
            summary="Mondays",
            start="2022-08-29",
            end="2022-08-29",
            rrule=recur,
        )
    )
    assert len(calendar.events) == 1
    store.delete(
        uid="mock-uid-1",
        recurrence_id="20220829",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == []
    assert len(calendar.events) == 0


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220913T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    ],
)
def test_edit_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    recur: Recur,
) -> None:
    """Test editing all instances of a recurring event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(start="2022-08-30T09:00:00", summary="Tuesday meeting"),
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220830T090000",
            "dtstart": "2022-08-30T09:00:00",
            "summary": "Tuesday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220906T090000",
            "dtstart": "2022-09-06T09:00:00",
            "summary": "Tuesday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220913T090000",
            "dtstart": "2022-09-13T09:00:00",
            "summary": "Tuesday meeting",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220912T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    ],
)
def test_edit_recurring_all_day_event_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    recur: Recur,
) -> None:
    """Test editing a single instance of a recurring all day event."""
    store.add(
        Event(
            summary="Monday event",
            start="2022-08-29",
            end="2022-08-30",
            rrule=recur,
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(start="2022-09-06", summary="Tuesday event"),
        recurrence_id="20220905",
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829",
            "dtstart": "2022-08-29",
            "summary": "Monday event",
        },
        {
            "uid": "mock-uid-2",
            "dtstart": "2022-09-06",
            "summary": "Tuesday event",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912",
            "dtstart": "2022-09-12",
            "summary": "Monday event",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220912T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    ],
)
def test_edit_recurring_event_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    recur: Recur,
) -> None:
    """Test editing a single instance of a recurring event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(start="2022-09-06T09:00:00", summary="Tuesday meeting"),
        recurrence_id="20220905T090000",
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-2",
            "dtstart": "2022-09-06T09:00:00",
            "summary": "Tuesday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220912T090000",
            "dtstart": "2022-09-12T09:00:00",
            "summary": "Monday meeting",
        },
    ]


def test_cant_change_recurrence_for_event_instance(
    store: EventStore,
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing all instances of a recurring event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
        )
    )

    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    with pytest.raises(StoreError, match="single instance with rrule"):
        store.edit(
            "mock-uid-1",
            Event(
                start="2022-09-06T09:00:00",
                summary="Tuesday meeting",
                rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
            ),
            recurrence_id="20220905T090000",
        )


def test_convert_single_instance_to_recurring(
    store: EventStore,
    frozen_time: FrozenDateTimeFactory,
    fetch_events: Callable[..., list[dict[str, Any]]],
) -> None:
    """Test editing all instances of a recurring event."""
    store.add(
        Event(
            summary="Daily meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Daily meeting",
        },
    ]

    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            summary="Daily meeting",
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        ),
    )

    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Daily meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220830T090000",
            "dtstart": "2022-08-30T09:00:00",
            "summary": "Daily meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220831T090000",
            "dtstart": "2022-08-31T09:00:00",
            "summary": "Daily meeting",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220912T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    ],
)
def test_edit_recurring_event_this_and_future(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    recur: Recur,
) -> None:
    """Test editing future instance of a recurring event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(summary="Team meeting"),
        recurrence_id="20220905T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-2",
            "dtstart": "2022-09-05T09:00:00",
            "recurrence_id": "20220905T090000",
            "summary": "Team meeting",
        },
        {
            "uid": "mock-uid-2",
            "recurrence_id": "20220912T090000",
            "dtstart": "2022-09-12T09:00:00",
            "summary": "Team meeting",
        },
    ]


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220912"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    ],
)
def test_edit_recurring_all_day_event_this_and_future(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    recur: Recur,
) -> None:
    """Test editing future instance of a recurring event."""
    store.add(
        Event(
            summary="Monday",
            start="2022-08-29",
            end="2022-08-30",
            rrule=recur,
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(summary="Mondays [edit]"),
        recurrence_id="20220905",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829",
            "dtstart": "2022-08-29",
            "summary": "Monday",
        },
        {
            "uid": "mock-uid-2",
            "dtstart": "2022-09-05",
            "recurrence_id": "20220905",
            "summary": "Mondays [edit]",
        },
        {
            "uid": "mock-uid-2",
            "recurrence_id": "20220912",
            "dtstart": "2022-09-12",
            "summary": "Mondays [edit]",
        },
    ]


def test_delete_all_day_event(
    store: EventStore, fetch_events: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test deleting a single all day event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29",
            end="2022-08-29",
        )
    )
    assert fetch_events() == [
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "dtstart": "2022-08-29",
            "dtend": "2022-08-29",
            "summary": "Monday meeting",
            "sequence": 0,
        },
    ]
    store.delete("mock-uid-1")
    assert fetch_events() == []


def test_delete_all_day_recurring(
    store: EventStore, fetch_events: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test deleting all instances of a recurring all day event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29",
            end="2022-08-29",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
        )
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-08-29",
            "summary": "Monday meeting",
            "recurrence_id": "20220829",
        },
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-09-05",
            "summary": "Monday meeting",
            "recurrence_id": "20220905",
        },
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-09-12",
            "summary": "Monday meeting",
            "recurrence_id": "20220912",
        },
    ]

    store.delete("mock-uid-1", recurrence_id="20220905")
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-08-29",
            "summary": "Monday meeting",
            "recurrence_id": "20220829",
        },
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-09-12",
            "summary": "Monday meeting",
            "recurrence_id": "20220912",
        },
    ]


def test_edit_recurrence_rule_this_and_future(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing future instances of a recurring event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(
            summary="Team meeting",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3;INTERVAL=2"),
        ),
        recurrence_id="20220905T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220829T090000",
            "dtstart": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-2",
            "dtstart": "2022-09-05T09:00:00",
            "recurrence_id": "20220905T090000",
            "summary": "Team meeting",
        },
        {
            "uid": "mock-uid-2",
            "recurrence_id": "20220919T090000",
            "dtstart": "2022-09-19T09:00:00",
            "summary": "Team meeting",
        },
    ]


def test_edit_recurrence_rule_this_and_future_all_day_first_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing future instances starting at the first instance."""
    store.add(
        Event(
            summary="Monday",
            start="2022-08-29",
            end="2022-08-30",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(
            summary="Mondays [edit]",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3;INTERVAL=2"),
        ),
        recurrence_id="20220829",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-08-29",
            "recurrence_id": "20220829",
            "summary": "Mondays [edit]",
        },
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-09-12",
            "recurrence_id": "20220912",
            "summary": "Mondays [edit]",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220926",
            "dtstart": "2022-09-26",
            "summary": "Mondays [edit]",
        },
    ]


def test_edit_recurrence_rule_this_and_future_first_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing future instances starting at the first instance."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(
            summary="Team meeting",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3;INTERVAL=2"),
        ),
        recurrence_id="20220829T090000",
        recurrence_range=Range.THIS_AND_FUTURE,
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == [
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-08-29T09:00:00",
            "recurrence_id": "20220829T090000",
            "summary": "Team meeting",
        },
        {
            "uid": "mock-uid-1",
            "dtstart": "2022-09-12T09:00:00",
            "recurrence_id": "20220912T090000",
            "summary": "Team meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220926T090000",
            "dtstart": "2022-09-26T09:00:00",
            "summary": "Team meeting",
        },
    ]


def test_invalid_uid(
    store: EventStore,
) -> None:
    """Test iteration over an empty calendar."""
    with pytest.raises(StoreError, match=r"No existing event with uid"):
        store.edit("invalid", Event(summary="example summary"))

    with pytest.raises(StoreError, match=r"No existing event with uid"):
        store.delete("invalid")


def test_invalid_recurrence_id(
    store: EventStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )

    with pytest.raises(StoreError, match=r"event is not recurring"):
        store.delete("mock-uid-1", recurrence_id="invalid")

    with pytest.raises(StoreError, match=r"event is not recurring"):
        store.edit(
            "mock-uid-1", recurrence_id="invalid", event=Event(summary="invalid")
        )


def test_no_timezone_for_floating(
    calendar: Calendar,
    store: EventStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start=datetime.datetime(2022, 8, 29, 9, 0, 0),
            end=datetime.datetime(2022, 8, 29, 9, 30, 0),
        )
    )
    assert len(calendar.events) == 1
    assert not calendar.timezones


def test_no_timezone_for_utc(
    calendar: Calendar,
    store: EventStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start=datetime.datetime(2022, 8, 29, 9, 0, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 8, 29, 9, 30, 0, tzinfo=datetime.timezone.utc),
        )
    )
    assert len(calendar.events) == 1
    assert not calendar.timezones


def test_timezone_for_datetime(
    calendar: Calendar,
    store: EventStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start=datetime.datetime(
                2022, 8, 29, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            end=datetime.datetime(
                2022, 8, 29, 9, 30, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
        )
    )
    assert len(calendar.events) == 1
    assert len(calendar.timezones) == 1
    assert calendar.timezones[0].tz_id == "America/Los_Angeles"

    store.add(
        Event(
            summary="Tuesday meeting",
            start=datetime.datetime(
                2022, 8, 30, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            end=datetime.datetime(
                2022, 8, 30, 9, 30, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
        )
    )
    # Timezone already exists
    assert len(calendar.timezones) == 1

    store.add(
        Event(
            summary="Wednesday meeting",
            start=datetime.datetime(
                2022, 8, 31, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
            ),
            end=datetime.datetime(
                2022, 8, 31, 12, 30, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
            ),
        )
    )
    assert len(calendar.timezones) == 2
    assert calendar.timezones[0].tz_id == "America/Los_Angeles"
    assert calendar.timezones[1].tz_id == "America/New_York"


def test_timezone_offset_not_supported(
    calendar: Calendar,
    store: EventStore,
) -> None:
    """Test adding a datetime for a timestamp that does not have a valid timezone."""
    offset = datetime.timedelta(hours=-8)
    tzinfo = datetime.timezone(offset=offset)
    event = Event(
        summary="Monday meeting",
        start=datetime.datetime(2022, 8, 29, 9, 0, 0, tzinfo=tzinfo),
        end=datetime.datetime(2022, 8, 29, 9, 30, 0, tzinfo=tzinfo),
    )
    with pytest.raises(StoreError, match=r"No timezone information"):
        store.add(event)
    assert not calendar.events
    assert not calendar.timezones


def test_add_and_delete_todo(
    todo_store: TodoStore, fetch_todos: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test adding a todoto the store and retrieval."""
    todo_store.add(
        Todo(
            summary="Monday meeting",
            due="2022-08-29T09:00:00",
        )
    )
    assert fetch_todos() == [
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "due": "2022-08-29T09:00:00",
            "summary": "Monday meeting",
            "sequence": 0,
        },
    ]
    todo_store.delete("mock-uid-1")
    assert fetch_todos() == []


def test_edit_todo(
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test editing an todo preserves order."""
    todo_store.add(
        Todo(
            summary="Monday morning items",
            due="2022-08-29T09:00:00",
        )
    )
    todo_store.add(
        Todo(
            summary="Tuesday morning items",
            due="2022-08-30T09:00:00",
        )
    )
    assert fetch_todos() == [
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "due": "2022-08-29T09:00:00",
            "summary": "Monday morning items",
            "sequence": 0,
        },
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-2",
            "created": "2022-09-03T09:38:05",
            "due": "2022-08-30T09:00:00",
            "summary": "Tuesday morning items",
            "sequence": 0,
        },
    ]

    frozen_time.tick(delta=datetime.timedelta(seconds=10))

    # Set event start time 5 minutes later
    todo_store.edit(
        "mock-uid-1",
        Todo(due="2022-08-29T09:05:00", summary="Monday morning items (Delayed)"),
    )
    assert fetch_todos() == [
        {
            "dtstamp": "2022-09-03T09:38:15",
            "uid": "mock-uid-1",
            "created": "2022-09-03T09:38:05",
            "due": "2022-08-29T09:05:00",
            "summary": "Monday morning items (Delayed)",
            "sequence": 1,
            "last_modified": "2022-09-03T09:38:15",
        },
        {
            "dtstamp": "2022-09-03T09:38:05",
            "uid": "mock-uid-2",
            "created": "2022-09-03T09:38:05",
            "due": "2022-08-30T09:00:00",
            "summary": "Tuesday morning items",
            "sequence": 0,
        },
    ]


def test_todo_store_invalid_uid(todo_store: TodoStore) -> None:
    """Edit a todo that does not exist."""
    with pytest.raises(StoreError, match="No existing"):
        todo_store.edit("mock-uid-1", Todo(due="2022-08-29T09:05:00", summary="Delayed"))
    with pytest.raises(StoreError, match="No existing"):
        todo_store.delete("mock-uid-1")


def test_todo_timezone_for_datetime(
    calendar: Calendar,
    todo_store: TodoStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    todo_store.add(
        Todo(
            summary="Monday meeting",
            due=datetime.datetime(
                2022, 8, 29, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
        )
    )
    assert len(calendar.todos) == 1
    assert len(calendar.timezones) == 1
    assert calendar.timezones[0].tz_id == "America/Los_Angeles"

    todo_store.add(
        Todo(
            summary="Tuesday meeting",
            due=datetime.datetime(
                2022, 8, 30, 9, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
        )
    )
    # Timezone already exists
    assert len(calendar.timezones) == 1

    todo_store.add(
        Todo(
            summary="Wednesday meeting",
            due=datetime.datetime(
                2022, 8, 31, 12, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
            ),
        )
    )
    assert len(calendar.timezones) == 2
    assert calendar.timezones[0].tz_id == "America/Los_Angeles"
    assert calendar.timezones[1].tz_id == "America/New_York"



def test_todo_timezone_offset_not_supported(
    calendar: Calendar,
    todo_store: TodoStore,
) -> None:
    """Test adding a datetime for a timestamp that does not have a valid timezone."""
    offset = datetime.timedelta(hours=-8)
    tzinfo = datetime.timezone(offset=offset)
    event = Todo(
        summary="Monday meeting",
        due=datetime.datetime(2022, 8, 29, 9, 0, 0, tzinfo=tzinfo),
    )
    with pytest.raises(StoreError, match=r"No timezone information"):
        todo_store.add(event)
    assert not calendar.todos
    assert not calendar.timezones