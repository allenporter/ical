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
from ical.timeline import generic_timeline

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

    with patch(
        "ical.util.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")
    ), patch("ical.journal.local_timezone", return_value=zoneinfo.ZoneInfo("America/Regina")):
        timeline = generic_timeline([journal], TZ)
        assert list(timeline) == [
            Journal.copy(journal, update={"recurrence_id": "20220807"}),
            Journal.copy(
                journal,
                update={"dtstart": datetime.date(2022, 8, 8), "recurrence_id": "20220808"},
            ),
            Journal.copy(
                journal,
                update={"dtstart": datetime.date(2022, 8, 9), "recurrence_id": "20220809"},
            ),
        ]
        assert list(
            timeline.overlapping(datetime.date(2022, 8, 7), datetime.date(2022, 8, 9))
        ) == [
            Journal.copy(journal, update={"recurrence_id": "20220807"}),
            Journal.copy(
                journal,
                update={"dtstart": datetime.date(2022, 8, 8), "recurrence_id": "20220808"},
            ),
        ]
