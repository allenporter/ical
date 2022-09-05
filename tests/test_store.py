"""Tests for the event store."""

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
from ical.store import EventStore
from ical.types.recur import Range, Recur


@pytest.fixture(name="calendar")
def mock_calendar() -> Calendar:
    """Fixture to create a calendar."""
    return Calendar()


@pytest.fixture(name="store")
def mock_store(calendar: Calendar) -> EventStore:
    """Fixture to create an event store."""
    return EventStore(calendar)


@pytest.fixture(name="_uid", autouse=True)
def mock_uid() -> Generator[None, None, None]:
    """Patch out uuid creation with a fixed value."""
    counter = 0

    def func() -> str:
        nonlocal counter
        counter += 1
        return f"mock-uid-{counter}"

    with patch("ical.event.uid_factory", new=func):
        yield


@pytest.fixture(name="fetch_events")
def mock_fetch_events(
    calendar: Calendar,
) -> Callable[..., list[dict[str, Any]]]:
    """Fixture to return events on the calendar."""

    def _func(keys: set[str] | None = None) -> list[dict[str, Any]]:
        result = []
        for event in calendar.timeline:
            data = event.dict()
            for key, value in list(data.items()):
                if value is None or isinstance(value, list) and not value:
                    del data[key]
                elif keys and key not in keys:
                    del data[key]
                elif isinstance(value, datetime.datetime):
                    data[key] = value.isoformat()
                elif isinstance(value, datetime.date):
                    data[key] = value.isoformat()
            result.append(data)
        return result

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


def test_add_and_cancel_event(
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
    store.cancel("mock-uid-1")
    assert fetch_events() == []


def test_edit_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    frozen_time: FrozenDateTimeFactory,
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
    with pytest.raises(ValueError, match="No existing"):
        store.edit("mock-uid-1", Event(start="2022-08-29T09:05:00", summary="Delayed"))


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and canceling the entire series."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
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
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220919T090000",
            "dtstart": "2022-09-19T09:00:00",
            "summary": "Monday meeting",
        },
        {
            "uid": "mock-uid-1",
            "recurrence_id": "20220926T090000",
            "dtstart": "2022-09-26T09:00:00",
            "summary": "Monday meeting",
        },
    ]
    store.cancel("mock-uid-1")
    assert fetch_events(None) == []


@pytest.mark.parametrize(
    "recur",
    [
        Recur.from_rrule("FREQ=WEEKLY;UNTIL=20220926T090000"),
        Recur.from_rrule("FREQ=WEEKLY;COUNT=5"),
    ],
)
def test_cancel_partial_recurring_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and cancelling part of the series."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    store.cancel(uid="mock-uid-1", recurrence_id="20220905T090000")
    store.cancel(uid="mock-uid-1", recurrence_id="20220919T090000")
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
def test_cancel_this_and_future_event(
    store: EventStore,
    fetch_events: Callable[..., list[dict[str, Any]]],
    recur: Recur,
) -> None:
    """Test adding a recurring event and cancelling events after one event."""
    store.add(
        Event(
            summary="Monday meeting",
            start="2022-08-29T09:00:00",
            end="2022-08-29T09:30:00",
            rrule=recur,
        )
    )
    store.cancel(
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
def test_edit_recurring_event_instance(
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


def test_add_and_cancel_event_date(
    store: EventStore, fetch_events: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test adding an event to the store and retrieval."""
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
    store.cancel("mock-uid-1")
    assert fetch_events() == []


def test_cancel_event_date_recurring(
    store: EventStore, fetch_events: Callable[..., list[dict[str, Any]]]
) -> None:
    """Test adding an event to the store and retrieval."""
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

    store.cancel("mock-uid-1", recurrence_id="20220905")
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


def test_invalid_uid(
    store: EventStore,
) -> None:
    """Test iteration over an empty calendar."""
    with pytest.raises(ValueError, match=r"No existing event with uid"):
        store.edit("invalid", Event(summary="example summary"))

    with pytest.raises(ValueError, match=r"No existing event with uid"):
        store.cancel("invalid")


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

    with pytest.raises(ValueError, match=r"event is not recurring"):
        store.cancel("mock-uid-1", recurrence_id="invalid")

    with pytest.raises(ValueError, match=r"event is not recurring"):
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
