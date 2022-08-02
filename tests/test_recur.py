"""Tests for timeline related calendar eents."""
from __future__ import annotations

import datetime

import pytest

from ical.event import Event
from ical.timeline import recur_timeline
from ical.types import Frequency, Recur, Weekday


@pytest.mark.parametrize(
    "start,end,rrule,expected",
    [
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, until=datetime.date(2022, 8, 4)),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 2), datetime.date(2022, 8, 3)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
                (datetime.date(2022, 8, 4), datetime.date(2022, 8, 5)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, until=datetime.date(2022, 8, 4), interval=2),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, count=3),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 2), datetime.date(2022, 8, 3)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.DAILY, interval=2, count=3),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 3), datetime.date(2022, 8, 4)),
                (datetime.date(2022, 8, 5), datetime.date(2022, 8, 6)),
            ],
        ),
        (
            datetime.datetime(2022, 8, 1, 9, 30, 0),
            datetime.datetime(2022, 8, 1, 10, 0, 0),
            Recur(freq=Frequency.DAILY, until=datetime.datetime(2022, 8, 4, 9, 30, 0)),
            [
                (
                    datetime.datetime(2022, 8, 1, 9, 30, 0),
                    datetime.datetime(2022, 8, 1, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 2, 9, 30, 0),
                    datetime.datetime(2022, 8, 2, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 3, 9, 30, 0),
                    datetime.datetime(2022, 8, 3, 10, 0, 0),
                ),
                (
                    datetime.datetime(2022, 8, 4, 9, 30, 0),
                    datetime.datetime(2022, 8, 4, 10, 0, 0),
                ),
            ],
        ),
    ],
)
def test_day_iteration(
    start: datetime.datetime | datetime.date,
    end: datetime.datetime | datetime.date,
    rrule: Recur,
    expected: list[tuple[datetime.date, datetime.date]],
) -> None:
    """Test chronological iteration of a timeline."""
    event = Event(
        summary="summary",
        start=start,
        end=end,
        rrule=rrule,
    )
    timeline = recur_timeline(event)
    assert [(e.start, e.end) for e in timeline] == expected


@pytest.mark.parametrize(
    "start,end,rrule,expected",
    [
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                until=datetime.date(2022, 9, 6),
                by_week_day=[Weekday.MONDAY],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 8), datetime.date(2022, 8, 9)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 22), datetime.date(2022, 8, 23)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
                (datetime.date(2022, 9, 5), datetime.date(2022, 9, 6)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY,
                until=datetime.date(2022, 9, 6),
                interval=2,
                by_week_day=[Weekday.MONDAY],
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(freq=Frequency.WEEKLY, count=3, by_week_day=[Weekday.MONDAY]),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 8), datetime.date(2022, 8, 9)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
            ],
        ),
        (
            datetime.date(2022, 8, 1),
            datetime.date(2022, 8, 2),
            Recur(
                freq=Frequency.WEEKLY, interval=2, count=3, by_week_day=[Weekday.MONDAY]
            ),
            [
                (datetime.date(2022, 8, 1), datetime.date(2022, 8, 2)),
                (datetime.date(2022, 8, 15), datetime.date(2022, 8, 16)),
                (datetime.date(2022, 8, 29), datetime.date(2022, 8, 30)),
            ],
        ),
    ],
)
def test_weekly_iteration(
    start: datetime.date | datetime.date,
    end: datetime.date | datetime.date,
    rrule: Recur,
    expected: list[tuple[datetime.date, datetime.date]],
) -> None:
    """Test chronological iteration of a timeline."""
    event = Event(
        summary="summary",
        start=start,
        end=end,
        rrule=rrule,
    )
    timeline = recur_timeline(event)
    assert [(e.start, e.end) for e in timeline] == expected
