"""Tests for the timespan library."""

import datetime
import zoneinfo

import pytest

from ical.timespan import Timespan

UTC = datetime.timezone.utc
LOS_ANGELES = zoneinfo.ZoneInfo("America/Los_Angeles")


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


def test_dst_fallback_ordering_and_predicates() -> None:
    """Test ordering, predicates, and duration across a DST fall-back fold."""
    # 2023-11-05 in America/Los_Angeles: 02:00 PDT (-07:00) falls back to 01:00 PST (-08:00)
    first = Timespan(
        datetime.datetime(2023, 11, 5, 1, 45, tzinfo=LOS_ANGELES, fold=0),  # 08:45Z
        datetime.datetime(2023, 11, 5, 1, 55, tzinfo=LOS_ANGELES, fold=0),  # 08:55Z
    )
    second = Timespan(
        datetime.datetime(2023, 11, 5, 1, 15, tzinfo=LOS_ANGELES, fold=1),  # 09:15Z
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=1),  # 09:30Z
    )
    assert first < second
    assert first <= second
    assert second > first
    assert second >= first
    assert sorted([second, first]) == [first, second]

    # Preserves original local tzinfo and fold on .start / .end while exposing UTC
    assert first.tzinfo is LOS_ANGELES
    assert second.start.fold == 1
    assert first.start_utc == datetime.datetime(2023, 11, 5, 8, 45, tzinfo=UTC)
    assert second.start_utc == datetime.datetime(2023, 11, 5, 9, 15, tzinfo=UTC)

    # Same wall-clock time in different folds (01:30 PDT vs 01:30 PST)
    fold0 = Timespan(
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=0),
        datetime.datetime(2023, 11, 5, 1, 45, tzinfo=LOS_ANGELES, fold=0),
    )
    fold1 = Timespan(
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=1),
        datetime.datetime(2023, 11, 5, 1, 45, tzinfo=LOS_ANGELES, fold=1),
    )
    assert fold0 < fold1
    assert not fold0.intersects(fold1)

    # Query window straddling 02:00 PDT -> 01:00 PST: [01:55 PDT (08:55Z), 01:20 PST (09:20Z))
    straddle_window = Timespan(
        datetime.datetime(2023, 11, 5, 1, 55, tzinfo=LOS_ANGELES, fold=0),
        datetime.datetime(2023, 11, 5, 1, 20, tzinfo=LOS_ANGELES, fold=1),
    )
    assert straddle_window.duration == datetime.timedelta(minutes=25)
    assert not first.intersects(straddle_window)
    assert second.intersects(straddle_window)
    assert second.starts_within(straddle_window)
    assert not second.ends_within(straddle_window)
    assert not second.is_included_in(straddle_window)

    # Event straddling the transition from 01:45 PDT (08:45Z) to 01:15 PST (09:15Z)
    across_fold = Timespan(
        datetime.datetime(2023, 11, 5, 1, 45, tzinfo=LOS_ANGELES, fold=0),
        datetime.datetime(2023, 11, 5, 1, 15, tzinfo=LOS_ANGELES, fold=1),
    )
    assert across_fold.duration == datetime.timedelta(minutes=30)
    assert across_fold.intersects(straddle_window)


def test_dst_spring_forward_and_all_day_durations() -> None:
    """Test elapsed duration across spring-forward and DST transition all-day spans."""
    # 2023-03-12 in America/Los_Angeles: 02:00 PST (-08:00) springs forward to 03:00 PDT (-07:00)
    across_gap = Timespan(
        datetime.datetime(2023, 3, 12, 1, 30, tzinfo=LOS_ANGELES),
        datetime.datetime(2023, 3, 12, 3, 30, tzinfo=LOS_ANGELES),
    )
    assert across_gap.duration == datetime.timedelta(hours=1)

    spring_day = Timespan.of(
        datetime.date(2023, 3, 12), datetime.date(2023, 3, 13), LOS_ANGELES
    )
    fall_day = Timespan.of(
        datetime.date(2023, 11, 5), datetime.date(2023, 11, 6), LOS_ANGELES
    )
    assert spring_day.duration == datetime.timedelta(hours=23)
    assert fall_day.duration == datetime.timedelta(hours=25)


def test_dst_cross_timezone_fold_equality_and_tie_break() -> None:
    """Test cross-zone comparisons at an ambiguous fold instant (PEP 495 == is False)."""
    # 01:30 PDT (fold=0) == 08:30Z in UTC, even though Python's raw `==` returns False
    local_short = Timespan(
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=0),
        datetime.datetime(2023, 11, 5, 1, 45, tzinfo=LOS_ANGELES, fold=0),
    )
    utc_long = Timespan(
        datetime.datetime(2023, 11, 5, 8, 30, tzinfo=UTC),
        datetime.datetime(2023, 11, 5, 9, 0, tzinfo=UTC),
    )
    assert local_short < utc_long
    assert utc_long > local_short

    local_zero = Timespan(
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=0),
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=0),
    )
    utc_instant = Timespan(
        datetime.datetime(2023, 11, 5, 8, 30, tzinfo=UTC),
        datetime.datetime(2023, 11, 5, 8, 30, tzinfo=UTC),
    )
    local_zero_fold1 = Timespan(
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=1),
        datetime.datetime(2023, 11, 5, 1, 30, tzinfo=LOS_ANGELES, fold=1),
    )
    assert local_zero.includes(utc_instant)
    assert not local_zero.includes(local_zero_fold1)
    assert local_zero == utc_instant
    assert hash(local_zero) == hash(utc_instant)
    assert local_zero != local_zero_fold1


def test_timespan_requires_end_tzinfo() -> None:
    """Test that Timespan requires a timezone-aware end datetime."""
    with pytest.raises(ValueError, match="End time did not have a timezone"):
        Timespan(
            datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
            datetime.datetime(2025, 5, 1, 10, 0),
        )


def test_timespan_rejects_uninitialized_tzinfo() -> None:
    """Test that Timespan rejects a tzinfo whose utcoffset() is None or raises."""

    class _NullOffsetTz(datetime.tzinfo):
        def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
            return None

        def dst(self, dt: datetime.datetime | None) -> datetime.timedelta | None:
            return None

        def tzname(self, dt: datetime.datetime | None) -> str | None:
            return None

    with pytest.raises(ValueError, match="Start time did not have a timezone"):
        Timespan(
            datetime.datetime(2025, 5, 1, 9, 0, tzinfo=_NullOffsetTz()),
            datetime.datetime(2025, 5, 1, 10, 0, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="End time did not have a timezone"):
        Timespan(
            datetime.datetime(2025, 5, 1, 9, 0, tzinfo=UTC),
            datetime.datetime(2025, 5, 1, 10, 0, tzinfo=_NullOffsetTz()),
        )
