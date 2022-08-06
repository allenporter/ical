"""Tests for Event library."""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ical.event import Event

SUMMARY = "test summary"
LOS_ANGELES = zoneinfo.ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    "begin,end,duration",
    [
        (
            datetime.fromisoformat("2022-09-16 12:00"),
            datetime.fromisoformat("2022-09-16 12:30"),
            timedelta(minutes=30),
        ),
        (
            date.fromisoformat("2022-09-16"),
            date.fromisoformat("2022-09-17"),
            timedelta(hours=24),
        ),
        (
            datetime.fromisoformat("2022-09-16 06:00"),
            datetime.fromisoformat("2022-09-17 08:30"),
            timedelta(days=1, hours=2, minutes=30),
        ),
    ],
)
def test_start_end_duration(
    begin: datetime, end: datetime, duration: timedelta
) -> None:
    """Test event duration calculation."""
    event = Event(summary=SUMMARY, start=begin, end=end)
    assert event.computed_duration == duration
    assert not event.duration


@pytest.mark.parametrize(
    "event1_start,event1_end,event2_start,event2_end",
    [
        (date(2022, 9, 6), date(2022, 9, 7), date(2022, 9, 8), date(2022, 9, 10)),
        (
            datetime(2022, 9, 6, 6, 0, 0),
            datetime(2022, 9, 6, 7, 0, 0),
            datetime(2022, 9, 6, 8, 0, 0),
            datetime(2022, 9, 6, 8, 30, 0),
        ),
        (
            datetime(2022, 9, 6, 6, 0, 0, tzinfo=timezone.utc),
            datetime(2022, 9, 6, 7, 0, 0, tzinfo=timezone.utc),
            datetime(2022, 9, 6, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2022, 9, 6, 8, 30, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2022, 9, 6, 6, 0, 0, tzinfo=LOS_ANGELES),
            datetime(2022, 9, 6, 7, 0, 0, tzinfo=LOS_ANGELES),
            datetime(2022, 9, 7, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2022, 9, 7, 8, 30, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2022, 9, 6, 6, 0, 0, tzinfo=LOS_ANGELES),
            datetime(2022, 9, 6, 7, 0, 0, tzinfo=LOS_ANGELES),
            datetime(2022, 9, 8, 8, 0, 0),
            datetime(2022, 9, 8, 8, 30, 0),
        ),
    ],
)
def test_comparisons(
    event1_start: datetime | date,
    event1_end: datetime | date,
    event2_start: datetime | date,
    event2_end: datetime | date,
) -> None:
    """Test event comparison methods."""
    event1 = Event(summary=SUMMARY, start=event1_start, end=event1_end)
    event2 = Event(summary=SUMMARY, start=event2_start, end=event2_end)
    assert event1 < event2
    assert event1 <= event2
    assert event2 >= event1
    assert event2 > event1

    assert event1 <= event2
    assert event2 >= event1
    assert event2 > event1


def test_invalid_comparisons() -> None:
    """Test event comparisons that are not valid."""
    event1 = Event(summary=SUMMARY, start=date(2022, 9, 6), end=date(2022, 9, 7))

    with pytest.raises(TypeError):
        assert event1 < "example"

    with pytest.raises(TypeError):
        assert event1 <= "example"

    with pytest.raises(TypeError):
        assert event1 > "example"

    with pytest.raises(TypeError):
        assert event1 >= "example"


def test_within_and_includes() -> None:
    """Test more complex comparison methods."""
    event1 = Event(summary=SUMMARY, start=date(2022, 9, 6), end=date(2022, 9, 10))
    event2 = Event(summary=SUMMARY, start=date(2022, 9, 7), end=date(2022, 9, 8))
    event3 = Event(summary=SUMMARY, start=date(2022, 9, 9), end=date(2022, 9, 11))

    assert not event1.starts_within(event2)
    assert not event1.starts_within(event3)
    assert event2.starts_within(event1)
    assert not event2.starts_within(event3)
    assert event3.starts_within(event1)
    assert not event3.starts_within(event2)

    assert not event1.ends_within(event2)
    assert event1.ends_within(event3)
    assert event2.ends_within(event1)
    assert not event2.ends_within(event3)
    assert not event3.ends_within(event1)
    assert not event3.ends_within(event2)
    assert event2 > event1

    assert event1.includes(event2)
    assert not event1.includes(event3)
    assert not event2.includes(event1)
    assert not event2.includes(event3)
    assert not event3.includes(event1)
    assert not event3.includes(event2)

    assert not event1.is_included_in(event2)
    assert not event1.is_included_in(event3)
    assert event2.is_included_in(event1)
    assert not event2.is_included_in(event3)
    assert not event3.is_included_in(event1)
    assert not event3.is_included_in(event2)


def test_start_end_same_type() -> None:
    """Verify that the start and end value are the same type."""

    with pytest.raises(ValidationError):
        Event(
            summary=SUMMARY, start=date(2022, 9, 9), end=datetime(2022, 9, 9, 11, 0, 0)
        )

    with pytest.raises(ValidationError):
        Event(
            summary=SUMMARY, start=datetime(2022, 9, 9, 10, 0, 0), end=date(2022, 9, 9)
        )


def test_start_end_local_time() -> None:
    """Verify that the start and end value are the same type."""

    # Valid
    Event(
        summary=SUMMARY,
        start=datetime(2022, 9, 9, 10, 0, 0),
        end=datetime(2022, 9, 9, 11, 0, 0),
    )
    Event(
        summary=SUMMARY,
        start=datetime(2022, 9, 9, 10, 0, 0, tzinfo=timezone.utc),
        end=datetime(2022, 9, 9, 11, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValidationError):
        Event(
            summary=SUMMARY,
            start=datetime(2022, 9, 9, 10, 0, 0, tzinfo=timezone.utc),
            end=datetime(2022, 9, 9, 11, 0, 0),
        )

    with pytest.raises(ValidationError):
        Event(
            summary=SUMMARY,
            start=datetime(2022, 9, 9, 10, 0, 0),
            end=datetime(2022, 9, 9, 11, 0, 0, tzinfo=timezone.utc),
        )


def test_start_and_duration() -> None:
    """Verify event created with a duration instead of explicit end time."""

    event = Event(summary=SUMMARY, start=date(2022, 9, 9), duration=timedelta(days=3))
    assert event.start == date(2022, 9, 9)
    assert event.end == date(2022, 9, 12)

    with pytest.raises(ValidationError):
        Event(summary=SUMMARY, start=date(2022, 9, 9), duration=timedelta(days=-3))

    with pytest.raises(ValidationError):
        Event(summary=SUMMARY, start=date(2022, 9, 9), duration=timedelta(seconds=60))

    event = Event(
        summary=SUMMARY,
        start=datetime(2022, 9, 9, 10, 0, 0),
        duration=timedelta(seconds=60),
    )
    assert event.start == datetime(2022, 9, 9, 10, 0, 0)
    assert event.end == datetime(2022, 9, 9, 10, 1, 0)
    assert event.duration == timedelta(seconds=60)
    assert event.computed_duration == timedelta(seconds=60)


@pytest.mark.parametrize(
    "range1,range2,expected",
    [
        (
            (date(2022, 8, 1), date(2022, 8, 2)),
            (date(2022, 8, 1), date(2022, 8, 2)),
            True,
        ),
        (
            (date(2022, 8, 1), date(2022, 8, 4)),
            (date(2022, 8, 2), date(2022, 8, 3)),
            True,
        ),
        (
            (date(2022, 8, 1), date(2022, 8, 3)),
            (date(2022, 8, 2), date(2022, 8, 4)),
            True,
        ),
        (
            (date(2022, 8, 2), date(2022, 8, 3)),
            (date(2022, 8, 1), date(2022, 8, 4)),
            True,
        ),
        (
            (date(2022, 8, 3), date(2022, 8, 4)),
            (date(2022, 8, 1), date(2022, 8, 4)),
            True,
        ),
        (
            (date(2022, 8, 2), date(2022, 8, 4)),
            (date(2022, 8, 1), date(2022, 8, 4)),
            True,
        ),
        (
            (date(2022, 8, 1), date(2022, 8, 2)),
            (date(2022, 8, 3), date(2022, 8, 4)),
            False,
        ),
        (
            (date(2022, 8, 3), date(2022, 8, 4)),
            (date(2022, 8, 1), date(2022, 8, 2)),
            False,
        ),
        (
            (date(2022, 8, 1), date(2022, 8, 2)),
            (date(2022, 8, 2), date(2022, 8, 3)),
            False,
        ),
        (
            (date(2022, 8, 2), date(2022, 8, 3)),
            (date(2022, 8, 1), date(2022, 8, 2)),
            False,
        ),
    ],
)
def test_date_intersects(
    range1: tuple[date, date],
    range2: tuple[date, date],
    expected: bool,
) -> None:
    """Test event intersection."""
    event1 = Event(summary=SUMMARY, start=range1[0], end=range1[1])
    event2 = Event(summary=SUMMARY, start=range2[0], end=range2[1])
    assert event1.intersects(event2) == expected
