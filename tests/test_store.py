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
from syrupy import SnapshotAssertion

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.todo import Todo
from ical.store import EventStore, TodoStore, StoreError
from ical.types.recur import Range, Recur
from ical.types import RelationshipType, RelatedTo

TZ = zoneinfo.ZoneInfo("America/Los_Angeles")

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
    return TodoStore(calendar, tzinfo=TZ)


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
    todo_store: TodoStore,
) -> Callable[..., list[dict[str, Any]]]:
    """Fixture to return todos on the calendar."""

    def _func(keys: set[str] | None = None) -> list[dict[str, Any]]:
        return [compact_dict(todo.dict(), keys) for todo in todo_store.todo_list()]

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
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events() == snapshot
    store.delete("mock-uid-1")
    assert fetch_events() == []


def test_edit_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test editing an event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events() == snapshot

    frozen_time.tick(delta=datetime.timedelta(seconds=10))

    # Set event start time 5 minutes later
    store.edit(
        "mock-uid-1",
        Event(start="2022-08-29T09:05:00", summary="Monday meeting (Delayed)"),
    )
    assert fetch_events() == snapshot


def test_edit_event_invalid_uid(store: EventStore) -> None:
    """Edit an event that does not exist."""
    with pytest.raises(StoreError, match="No existing"):
        store.edit("mock-uid-1", Event(start="2022-08-29T09:05:00", summary="Delayed"))


@pytest.mark.parametrize(
    ("start", "end", "recur"),
    [
        (
            datetime.datetime(2022, 8, 29, 9, 0),
            datetime.datetime(2022, 8, 29, 9, 30),
            Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        ),
        (
            datetime.datetime(2022, 8, 29, 9, 0),
            datetime.datetime(2022, 8, 29, 9, 30),
            Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
        ),
        (
            datetime.datetime(
                2022, 8, 29, 9, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            datetime.datetime(
                2022, 8, 29, 9, 30, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
            Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
        ),
    ],
)
def test_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    start: datetime.datetime,
    end: datetime.datetime,
    recur: Recur,
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot
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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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

    assert fetch_events({"uid", "recurrence_id", "sequence", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_edit_recurring_with_same_rrule(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test that changing the rrule to the same value is a no-op."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=2"),
        )
    )
    frozen_time.tick(delta=datetime.timedelta(seconds=10))
    store.edit(
        "mock-uid-1",
        Event(
            start="2022-08-30T09:00:00",
            summary="Tuesday meeting",
            rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=2"),
        ),
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
) -> None:
    """Test editing all instances of a recurring event."""
    store.add(
        Event(
            summary="Daily meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot

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

    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


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
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_delete_all_day_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
) -> None:
    """Test deleting a single all day event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29",
            end="2022-08-29",
        )
    )
    assert fetch_events() == snapshot
    store.delete("mock-uid-1")
    assert fetch_events() == []


def test_delete_all_day_recurring(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot

    store.delete("mock-uid-1", recurrence_id="20220905")
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_edit_recurrence_rule_this_and_future(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_edit_recurrence_rule_this_and_future_all_day_first_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_edit_recurrence_rule_this_and_future_first_instance(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
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
    assert fetch_events({"uid", "recurrence_id", "dtstart", "summary"}) == snapshot


def test_invalid_uid(
    store: EventStore,
) -> None:
    """Test iteration over an empty calendar."""
    with pytest.raises(StoreError, match=r"No existing item with uid"):
        store.edit("invalid", Event(summary="example summary"))

    with pytest.raises(StoreError, match=r"No existing item with uid"):
        store.delete("invalid")


def test_invalid_recurrence_id(
    store: EventStore,
) -> None:
    """Test adding an event to the store and retrieval."""
    store.add(
        Event(
            uid="mock-uid-1",
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
        )
    )

    with pytest.raises(StoreError, match=r"No existing item"):
        store.delete("mock-uid-1", recurrence_id="20220828T090000")

    with pytest.raises(StoreError, match=r"No existing item with"):
        store.edit("mock-uid-1", Event(summary="tuesday"), recurrence_id="20210828")


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
    with pytest.raises(StoreError, match=r"No timezone information available for event: UTC-08:00"):
        store.add(event)
    assert not calendar.events
    assert not calendar.timezones


def test_delete_event_parent_cascade_to_children(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
) -> None:
    """Test deleting a parent event object deletes the children."""
    event1 = store.add(
        Event(
            summary="Submit IRS documents",
            start="2022-08-29T09:00:00",
            duration=datetime.timedelta(minutes=30),
        )
    )
    assert event1.uid == "mock-uid-1"

    event2 = store.add(
        Event(
            summary="Lookup website",
            start="2022-08-29T10:00:00",
            duration=datetime.timedelta(minutes=30),
            related_to=[RelatedTo(uid="mock-uid-1", reltype=RelationshipType.PARENT)],
        )
    )
    assert event2.uid == "mock-uid-2"

    event3 = store.add(
        Event(
            summary="Download forms",
            start="2022-08-29T11:00:00",
            duration=datetime.timedelta(minutes=30),
            related_to=[RelatedTo(uid="mock-uid-1", reltype=RelationshipType.PARENT)],
        )
    )
    assert event3.uid == "mock-uid-3"

    store.add(
        Event(
            summary="Milk",
            start="2022-08-29T12:00:00",
            duration=datetime.timedelta(minutes=30),
        )
    )
    assert [item["uid"] for item in fetch_events()] == snapshot

    # Delete parent and cascade to children
    store.delete("mock-uid-1")
    assert [item["uid"] for item in fetch_events()] == snapshot


@pytest.mark.parametrize(
    "reltype",
    [
        (RelationshipType.SIBBLING),
        (RelationshipType.CHILD),
    ],
)
def test_unsupported_event_reltype(
    store: EventStore,
    reltype: RelationshipType,
) -> None:
    """Test that only PARENT relationships can be managed by the store."""

    with pytest.raises(StoreError, match=r"Unsupported relationship type"):
        store.add(
            Event(
                summary="Lookup website",
                related_to=[RelatedTo(uid="mock-uid-1", reltype=reltype)],
            )
        )

    event1 = store.add(
        Event(
            summary="Parent",
        )
    )
    event2 = store.add(
        Event(
            summary="Future child",
        )
    )
    event2.related_to = [RelatedTo(uid=event1.uid, reltype=reltype)]
    with pytest.raises(StoreError, match=r"Unsupported relationship type"):
        store.edit(event2.uid, event2)


def test_add_and_delete_todo(
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
) -> None:
    """Test adding a todoto the store and retrieval."""
    todo_store.add(
        Todo(
            summary="Monday meeting",
            due="2022-08-29T09:00:00",
        )
    )
    assert fetch_todos() == snapshot
    todo_store.delete("mock-uid-1")
    assert fetch_todos() == []


def test_edit_todo(
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
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
    assert fetch_todos() == snapshot

    frozen_time.tick(delta=datetime.timedelta(seconds=10))

    # Set event start time 5 minutes later
    todo_store.edit(
        "mock-uid-1",
        Todo(due="2022-08-29T09:05:00", summary="Monday morning items (Delayed)"),
    )
    assert fetch_todos() == snapshot


def test_todo_store_invalid_uid(todo_store: TodoStore) -> None:
    """Edit a todo that does not exist."""
    with pytest.raises(StoreError, match="No existing"):
        todo_store.edit(
            "mock-uid-1", Todo(due="2022-08-29T09:05:00", summary="Delayed")
        )
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
            dtstart=datetime.datetime(
                2022, 8, 29, 8, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
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
            dtstart=datetime.datetime(
                2022, 8, 30, 8, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/Los_Angeles")
            ),
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
            dtstart=datetime.datetime(
                2022, 8, 31, 11, 0, 0, tzinfo=zoneinfo.ZoneInfo("America/New_York")
            ),
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
        dtstart=datetime.datetime(2022, 8, 29, 9, 0, 0, tzinfo=tzinfo),
        due=datetime.datetime(2022, 8, 30, 9, 0, 0, tzinfo=tzinfo),
    )
    with pytest.raises(StoreError, match=r"No timezone information"):
        todo_store.add(event)
    assert not calendar.todos
    assert not calendar.timezones


def test_delete_parent_todo_cascade_to_children(
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    snapshot: SnapshotAssertion,
) -> None:
    """Test deleting a parent todo object deletes the children."""
    todo1 = todo_store.add(
        Todo(
            summary="Submit IRS documents",
            due="2022-08-29T09:00:00",
        )
    )
    assert todo1.uid == "mock-uid-1"

    todo2 = todo_store.add(
        Todo(
            summary="Lookup website",
            related_to=[RelatedTo(uid="mock-uid-1", reltype=RelationshipType.PARENT)],
        )
    )
    assert todo2.uid == "mock-uid-2"

    todo3 = todo_store.add(
        Todo(
            summary="Download forms",
            related_to=[RelatedTo(uid="mock-uid-1", reltype=RelationshipType.PARENT)],
        )
    )
    assert todo3.uid == "mock-uid-3"

    todo_store.add(
        Todo(
            summary="Milk",
        )
    )
    assert [item["uid"] for item in fetch_todos()] == snapshot

    # Delete parent and cascade to children
    todo_store.delete("mock-uid-1")
    assert [item["uid"] for item in fetch_todos()] == snapshot


@pytest.mark.parametrize(
    "reltype",
    [
        (RelationshipType.SIBBLING),
        (RelationshipType.CHILD),
    ],
)
def test_unsupported_todo_reltype(
    todo_store: TodoStore,
    reltype: RelationshipType,
) -> None:
    """Test that only PARENT relationships can be managed by the store."""

    with pytest.raises(StoreError, match=r"Unsupported relationship type"):
        todo_store.add(
            Todo(
                summary="Lookup website",
                related_to=[RelatedTo(uid="mock-uid-1", reltype=reltype)],
            )
        )

    todo1 = todo_store.add(
        Todo(
            summary="Parent",
        )
    )
    todo2 = todo_store.add(
        Todo(
            summary="Future child",
        )
    )
    todo2.related_to = [RelatedTo(uid=todo1.uid, reltype=reltype)]
    with pytest.raises(StoreError, match=r"Unsupported relationship type"):
        todo_store.edit(todo2.uid, todo2)


def test_recurring_todo_item_edit_series(
    calendar: Calendar,
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test editing an item that affects the entire series."""

    frozen_time.move_to("2024-01-09T10:00:05")

    # Create a recurring to-do item
    todo_store.add(
        Todo(
            summary="Walk dog",
            dtstart="2024-01-09",
            due="2024-01-10",
            status="NEEDS-ACTION",
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=10"),
        )
    )
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="initial")

    # Mark the entire series as completed
    todo_store.edit("mock-uid-1", Todo(status="COMPLETED"))
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="completed")

    # Advance to the next day.
    frozen_time.move_to("2024-01-10T10:00:00")

    # All instances are completed
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="next_instance")

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot


def test_recurring_todo_item_edit_single(
    calendar: Calendar,
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test editing a single recurring item."""

    frozen_time.move_to("2024-01-09T10:00:05")

    # Create a recurring to-do item
    todo_store.add(
        Todo(
            summary="Walk dog",
            dtstart="2024-01-09",
            due="2024-01-10",
            status="NEEDS-ACTION",
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=10"),
        )
    )
    # There is a single underlying instance
    assert len(calendar.todos) == 1
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="initial")

    # Mark a single instance as completed
    todo_store.edit("mock-uid-1", Todo(status="COMPLETED"), recurrence_id="20240109")
    # There are now two underlying instances
    assert len(calendar.todos) == 2

    # Collapsed view of a single item
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="completed")

    # Advance to the next day and a new incomplete instance appears
    frozen_time.move_to("2024-01-10T10:00:00")
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="next_instance")

    # Mark the new instance as completed
    todo_store.edit("mock-uid-1", Todo(status="COMPLETED"), recurrence_id="20240110")
    assert len(calendar.todos) == 3
    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot(name="result_ics")

    # Also edit the instance summary and verify that it can be modified again
    todo_store.edit("mock-uid-1", Todo(summary="Walk cat"), recurrence_id="20240110")
    assert len(calendar.todos) == 3
    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot(name="result_ics_modified")

    # Collapsed view of the same item
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="next_instance_completed")

    # Delete a single instance and the following days instance appears. This is
    # not really a common operation, but still worth exercsing the behavior.
    todo_store.delete("mock-uid-1", recurrence_id="20240110")

    # Now only two underlying objects
    # The prior instance is the latest on the list
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name="next_instance_deleted")

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot(name="next_instance_deleted_ics")

    # Delete the entire series
    todo_store.delete("mock-uid-1")
    assert not calendar.todos
    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot(name="deleted_series_ics")


def test_delete_todo_series(
    calendar: Calendar,
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
) -> None:
    """Test deleting a recurring todo item with edits applied."""
    # Create a recurring to-do item
    todo_store.add(
        Todo(
            summary="Walk dog",
            dtstart="2024-01-09",
            due="2024-01-10",
            status="NEEDS-ACTION",
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=10"),
        )
    )
    # Mark instances as completed
    todo_store.edit("mock-uid-1", Todo(status="COMPLETED"), recurrence_id="20240109")
    # Delete all the items
    todo_store.delete("mock-uid-1")
    assert not calendar.todos


def test_delete_instance_in_todo_series(
    calendar: Calendar,
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test deleting a single instance of a recurring todo item."""
    # Create a recurring to-do item
    todo_store.add(
        Todo(
            summary="Walk dog",
            dtstart="2024-01-09",
            due="2024-01-10",
            status="NEEDS-ACTION",
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=10"),
        )
    )
    raw_ids = [
        (item.dtstart.isoformat(), item.recurrence_id, item.rrule)
        for item in calendar.todos
    ]
    assert raw_ids == snapshot

    # Mark instances as completed
    todo_store.edit("mock-uid-1", Todo(status="COMPLETED"), recurrence_id="20240109")
    raw_ids = [
        (item.dtstart.isoformat(), item.recurrence_id, item.rrule, item.exdate)
        for item in calendar.todos
    ]
    assert raw_ids == snapshot

    # Delete a another instance
    todo_store.delete("mock-uid-1", recurrence_id="20240110")

    raw_ids = [
        (item.dtstart.isoformat(), item.recurrence_id, item.rrule, item.exdate)
        for item in calendar.todos
    ]
    assert raw_ids == snapshot

    # Advance to the next day.
    frozen_time.move_to("2024-01-10T10:00:00")

    # Previous item is still marked completed and new item has not started yet
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot

    # Advance to the next day and New item appears.
    frozen_time.move_to("2024-01-11T10:00:00")
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot

    # Advance to the next day and New item appears.
    frozen_time.move_to("2024-01-12T10:00:00")
    assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot


def test_modify_todo_rrule_for_this_and_future(
    calendar: Calendar,
    todo_store: TodoStore,
    fetch_todos: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
    snapshot: SnapshotAssertion,
) -> None:
    """Test modify an rrule in the middle of the series."""
    # Create a recurring to-do item to wash the card every Saturday
    todo_store.add(
        Todo(
            summary="Wash car (Sa)",
            dtstart="2024-01-06",
            due="2024-01-07",
            status="NEEDS-ACTION",
            rrule=Recur.from_rrule("FREQ=WEEKLY;BYDAY=SA;COUNT=10"),
        )
    )

    # Move the item to Sunday going forward
    todo_store.edit(
        "mock-uid-1",
        Todo(
            summary="Wash car (Su)",
            dtstart="2024-01-21",
            due="2024-01-22",
            rrule=Recur.from_rrule("FREQ=WEEKLY;BYDAY=SU;COUNT=10")
        ),
        recurrence_id="20240120",
        recurrence_range=Range.THIS_AND_FUTURE
    )

    assert IcsCalendarStream.calendar_to_ics(calendar) == snapshot(name="ics")

    for date in ("2024-01-05", "2024-01-12", "2024-01-19", "2024-01-26"):
        frozen_time.move_to(date)
        assert fetch_todos(["uid", "recurrence_id", "due", "summary", "status"]) == snapshot(name=date)



def test_modify_todo_due_without_dtstart(
    calendar: Calendar,
    todo_store: TodoStore,
) -> None:
    """Validate that a due date modification without updating dtstart will be repaired."""
    # Create a recurring to-do item to wash the card every Saturday
    todo_store.add(
        Todo(
            summary="Wash car",
            dtstart="2024-01-06",
            due="2024-01-07",
        )
    )

    # Move the due date to be before the dtstart and change to a datetime.
    todo_store.edit(
        "mock-uid-1",
        Todo(
            summary="Wash car",
            due="2024-01-01T10:00:00Z",
        ),
    )

    todos = list(todo_store.todo_list())
    assert len(todos) == 1
    todo = todos[0]
    assert todo.due == datetime.datetime(2024, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    assert isinstance(todo.dtstart, datetime.datetime)
    assert todo.dtstart < todo.due
             

@pytest.mark.parametrize(
        ("due", "expected_tz"),
        [
            (None, TZ),
            ("2024-01-07T10:00:00Z", datetime.timezone.utc),
            ("2024-01-07T10:00:00-05:00", zoneinfo.ZoneInfo("America/New_York")),
        ],
)
def test_dtstart_timezone(
    calendar: Calendar,
    todo_store: TodoStore,
    due: str | None,
    expected_tz: zoneinfo.ZoneInfo,
) -> None:
    """Validate that a due date modification without updating dtstart will be repaired."""
    # Create a recurring to-do item to wash the card every Saturday
    todo_store.add(
        Todo(
            summary="Wash car",
        )
    )
    todos = list(todo_store.todo_list())
    assert len(todos) == 1
    todo = todos[0]
    assert todo.due is None
    assert todo.dtstart.tzinfo == TZ
                                        