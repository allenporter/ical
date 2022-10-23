"""Tests for the timeline library."""

import datetime
import random
import zoneinfo
from typing import Any

import pytest

from ical.calendar import Calendar
from ical.event import Event
from ical.types.recur import Recur

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
