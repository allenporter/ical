"""Tests for the timeline library."""

import datetime
import random
import zoneinfo
from typing import Any
from unittest.mock import patch

import pytest

from ical.calendar import Calendar
from ical.event import Event
from ical.journal import Journal
from ical.types.recur import Recur
from ical.timeline import generic_timeline, materialize_timeline, calendar_timeline

TZ = zoneinfo.ZoneInfo("America/Regina")


@pytest.fixture(name="calendar")
def fake_calendar(num_events: int, num_instances: int) -> Calendar:
    """Fixture for creating a fake calendar of items."""
    cal = Calendar()
    for i in range(num_events):
        delta = datetime.timedelta(days=int(365 * random.random()))
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.date(2022, 2, 1) + delta,
                end=datetime.date(2000, 2, 2) + delta,
                rrule=Recur.from_rrule(f"FREQ=DAILY;COUNT={num_instances}"),
            )
        )
    return cal


@pytest.mark.parametrize(
    "num_events,num_instances",
    [
        (10, 10),
        (10, 100),
        (10, 1000),
        (100, 10),
        (100, 100),
    ],
)
@pytest.mark.benchmark(min_rounds=1, cprofile=True, warmup=False)
def test_benchmark_merged_iter(
    calendar: Calendar, num_events: int, num_instances: int, benchmark: Any
) -> None:
    """Add a benchmark for the merged iterator."""

    def exhaust() -> int:
        nonlocal calendar
        return sum(1 for _ in calendar.timeline_tz(TZ))

    result = benchmark(exhaust)
    assert result == num_events * num_instances


def test_journal_timeline() -> None:
    """Test journal entries on a timeline."""

    journal = Journal(
        summary="Example",
        start=datetime.date(2022, 8, 7),
        rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
    )
    assert journal.recurring

    with (
        patch(
            "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
        ),
        patch(
            "ical.journal.local_timezone",
            return_value=zoneinfo.ZoneInfo("America/Regina"),
        ),
    ):
        timeline = generic_timeline([journal], TZ)
        assert list(timeline) == [
            Journal.model_copy(journal, update={"recurrence_id": "20220807"}),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 8),
                    "recurrence_id": "20220808",
                },
            ),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 9),
                    "recurrence_id": "20220809",
                },
            ),
        ]
        assert list(
            timeline.overlapping(datetime.date(2022, 8, 7), datetime.date(2022, 8, 9))
        ) == [
            Journal.model_copy(journal, update={"recurrence_id": "20220807"}),
            Journal.model_copy(
                journal,
                update={
                    "dtstart": datetime.date(2022, 8, 8),
                    "recurrence_id": "20220808",
                },
            ),
        ]


def test_materialize_timeline_empty() -> None:
    """Test materializing an empty timeline."""
    cal = Calendar()
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
    )
    assert list(materialized) == []


def test_materialize_timeline_events() -> None:
    """Test materializing a timeline with events."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 2",
            start=datetime.datetime(2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 2, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 3",
            start=datetime.datetime(2022, 1, 3, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 3, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 3, tzinfo=datetime.timezone.utc),
    )
    events = list(materialized)
    assert len(events) == 2
    assert events[0].summary == "Event 1"
    assert events[1].summary == "Event 2"

    # Verify that the events are the same object when iterating multiple times
    assert list(materialized) == events
    assert list(materialized)[0] is events[0]
    assert list(materialized)[1] is events[1]


def test_materialize_recurring_timeline() -> None:
    """Test materializing a timeline with recurring events."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=3"),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 3, tzinfo=datetime.timezone.utc),
    )
    events = list(materialized)
    assert len(events) == 2
    assert events[0].summary == "Event 1"
    assert events[0].start == datetime.datetime(
        2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc
    )
    assert events[1].summary == "Event 1"
    assert events[1].start == datetime.datetime(
        2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc
    )


def test_benchmark_materialize_timeline() -> None:
    """Benchmark materializing a timeline."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.date(2022, 1, 1),
            end=datetime.date(2022, 1, 2),
            rrule=Recur.from_rrule("FREQ=DAILY;COUNT=1000"),
        )
    )
    timeline = calendar_timeline(cal.events, zoneinfo.ZoneInfo("UTC"))

    materialize_timeline(
        timeline,
        datetime.date(2022, 1, 1),
        datetime.date(2022, 4, 1),
    )


def test_materialize_timeline_max_events() -> None:
    """Test materializing a timeline with a maximum number of events."""
    cal = Calendar()
    for i in range(10):
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.datetime(
                    2022, 1, 1, 8 + i, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2022, 1, 1, 9 + i, 0, tzinfo=datetime.timezone.utc
                ),
            )
        )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # Test with limit of 5
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
        max_number_of_events=5,
    )
    events = list(materialized)
    assert len(events) == 5
    assert [e.summary for e in events] == [f"Event {i}" for i in range(5)]

    # Test with limit of 15 (more than available)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        datetime.datetime(2022, 1, 2, tzinfo=datetime.timezone.utc),
        max_number_of_events=15,
    )
    events = list(materialized)
    assert len(events) == 10


def test_materialize_timeline_no_stop() -> None:
    """Test materializing a timeline without a stop time."""
    cal = Calendar()
    cal.events.append(
        Event(
            summary="Event 1",
            start=datetime.datetime(2022, 1, 1, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 1, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    cal.events.append(
        Event(
            summary="Event 2",
            start=datetime.datetime(2022, 1, 2, 8, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2022, 1, 2, 9, 0, tzinfo=datetime.timezone.utc),
        )
    )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # No stop specified should return all events active after start
    # (max_number_of_events is required when stop is None)
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, 12, 0, tzinfo=datetime.timezone.utc),
        max_number_of_events=1,
    )
    events = list(materialized)
    assert len(events) == 1
    assert events[0].summary == "Event 2"


def test_materialize_timeline_no_exit_condition() -> None:
    """Test that materialize_timeline raises ValueError without an exit condition."""
    cal = Calendar()
    timeline = generic_timeline(cal.events, datetime.timezone.utc)
    with pytest.raises(
        ValueError, match="Either stop or max_number_of_events must be specified"
    ):
        materialize_timeline(
            timeline,
            datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        )


def test_materialize_timeline_no_stop_max_events() -> None:
    """Test materializing a timeline without a stop time and a limit."""
    cal = Calendar()
    for i in range(10):
        cal.events.append(
            Event(
                summary=f"Event {i}",
                start=datetime.datetime(
                    2022, 1, 1 + i, 8, 0, tzinfo=datetime.timezone.utc
                ),
                end=datetime.datetime(
                    2022, 1, 1 + i, 9, 0, tzinfo=datetime.timezone.utc
                ),
            )
        )
    timeline = generic_timeline(cal.events, datetime.timezone.utc)

    # No stop specified, limit 3
    materialized = materialize_timeline(
        timeline,
        datetime.datetime(2022, 1, 1, tzinfo=datetime.timezone.utc),
        max_number_of_events=3,
    )
    events = list(materialized)
    assert len(events) == 3
    assert [e.summary for e in events] == ["Event 0", "Event 1", "Event 2"]
