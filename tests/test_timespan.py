"""Tests for the timespan library."""

import datetime

import pytest

from ical.timespan import Timespan

UTC = datetime.timezone.utc


def test_timespan_requires_tzinfo() -> None:
    """Test that Timespan requires a timezone-aware start datetime."""
    with pytest.raises(ValueError, match="Start time did not have a timezone"):
        Timespan(
            datetime.datetime(2025, 5, 1, 9, 0),
            datetime.datetime(2025, 5, 1, 10, 0),
        )


def test_timespan_properties() -> None:
    """Test Timespan properties."""
    start = datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC)
    end = datetime.datetime(2025, 5, 1, 10, 30, tzinfo=UTC)
    span = Timespan(start, end)
    assert span.start == start
    assert span.end == end
    assert span.tzinfo == UTC
    assert span.duration == datetime.timedelta(hours=1, minutes=30)


def test_is_included_in_boundary() -> None:
    """Test is_included_in boundary conditions including equal end times."""
    day_span = Timespan.of(datetime.date(2025, 5, 1), datetime.date(2025, 5, 2), UTC)
    assert day_span.is_included_in(day_span)

    sub_start = Timespan(
        datetime.datetime(2025, 5, 1, 0, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 12, 0, tzinfo=UTC),
    )
    sub_end = Timespan(
        datetime.datetime(2025, 5, 1, 12, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 2, 0, 0, tzinfo=UTC),
    )
    assert sub_start.is_included_in(day_span)
    assert sub_end.is_included_in(day_span)

    overflow_end = Timespan(
        datetime.datetime(2025, 5, 1, 12, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 2, 0, 1, tzinfo=UTC),
    )
    assert not overflow_end.is_included_in(day_span)


def test_includes_boundary_and_zero_duration() -> None:
    """Test includes with sub-spans and zero-duration spans."""
    span = Timespan(
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
    )
    # Identical span and sub-spans ending at self.end
    assert span.includes(span)
    sub_end = Timespan(
        datetime.datetime(2025, 5, 1, 9, 30, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
    )
    assert span.includes(sub_end)

    # Instant at start and middle are included, instant at exclusive end is not
    instant_start = Timespan.of(
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
    )
    instant_mid = Timespan.of(
        datetime.datetime(2025, 5, 1, 9, 30, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 9, 30, tzinfo=UTC),
    )
    instant_end = Timespan.of(
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
    )
    assert span.includes(instant_start)
    assert span.includes(instant_mid)
    assert not span.includes(instant_end)

    # Zero-duration event includes the exact same instant, but nothing else
    zero_span = Timespan(
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
    )
    assert zero_span.includes(instant_start)
    assert not zero_span.includes(instant_mid)
    assert not zero_span.includes(span)


def test_ends_within_adjacent_events() -> None:
    """Test ends_within for adjacent back-to-back events."""
    event_a = Timespan(
        datetime.datetime(2025, 5, 1, 8, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
    )
    event_b = Timespan(
        datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
    )
    # event_a ends at 09:00, which is the start of event_b (not within event_b)
    assert not event_a.ends_within(event_b)
    assert not event_b.starts_within(event_a)

    # An event ending at 10:00 ends within [08:00, 10:00)
    combined = Timespan(
        datetime.datetime(2025, 5, 1, 8, 0, tzinfo=UTC),
        datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
    )
    assert event_b.ends_within(combined)
    assert event_a.ends_within(combined)
