"""Tests for the iter library."""

from __future__ import annotations

import copy
import datetime
import itertools
import random
from collections.abc import Generator
from typing import Any, Iterable, Iterator

import pytest
from dateutil import rrule

from ical.iter import (
    CachedTransitionTimeline,
    MergedIterable,
    MergedIterator,
    RecurIterable,
    RecurrenceError,
    RulesetIterable,
)

EMPTY_LIST: list[bool] = []
EMPTY_ITERATOR_LIST: list[Iterator[bool]] = []
EMPTY_ITERABLE_LIST: list[Iterable[bool]] = []


def test_merged_empty() -> None:
    """Test iterating over an empty input."""

    with pytest.raises(StopIteration):
        next(iter(MergedIterable(EMPTY_ITERABLE_LIST)))

    with pytest.raises(StopIteration):
        next(iter(MergedIterator(EMPTY_ITERATOR_LIST)))

    with pytest.raises(StopIteration):
        next(MergedIterator(EMPTY_ITERATOR_LIST))

    with pytest.raises(StopIteration):
        next(MergedIterator([iter(EMPTY_LIST), iter(EMPTY_LIST)]))


def test_merge_is_sorted() -> None:
    """Test that the merge result of two sorted inputs is sorted."""
    merged_it = MergedIterable([[1, 3, 5], [2, 4, 6]])
    assert list(merged_it) == [1, 2, 3, 4, 5, 6]


def test_recur_empty() -> None:
    """Test recur with an empty input."""

    def _is_even_year(value: datetime.date) -> bool:
        return value.year % 2 == 0

    input_dates = [
        datetime.date(2022, 1, 1),
        datetime.date(2023, 1, 1),
        datetime.date(2024, 1, 1),
    ]
    recur_it = RecurIterable(_is_even_year, input_dates)
    assert list(recur_it) == [True, False, True]
    # an iterator is an iterable
    assert list(iter(iter(recur_it))) == [True, False, True]


def test_merge_false_values() -> None:
    """Test the merged iterator can handle values evaluating to False."""
    merged_it: Iterable[float | int] = MergedIterable([[0, 1], [-2, 0, 0.5, 2]])
    assert list(merged_it) == [-2, 0, 0, 0.5, 1, 2]


def test_merge_none_values() -> None:
    """Test the merged iterator can handle None values."""
    merged_it = MergedIterable([[None, None], [None]])
    assert list(merged_it) == [None, None, None]


@pytest.mark.parametrize(
    "num_iters,num_objects",
    [
        (10, 10),
        (10, 100),
        (10, 1000),
        (100, 10),
        (100, 100),
    ],
)
def test_benchmark_merged_iter(
    num_iters: int, num_objects: int, benchmark: Any
) -> None:
    """Add a benchmark for the merged iterator."""

    def gen_items() -> Generator[float, None, None]:
        nonlocal num_objects
        for _ in range(num_objects):
            yield random.random()

    def exhaust() -> int:
        nonlocal num_iters
        merged_it = MergedIterable([gen_items() for _ in range(num_iters)])
        return sum(1 for _ in merged_it)

    result = benchmark(exhaust)
    assert result == num_iters * num_objects


def test_debug_invalid_rules() -> None:
    """Exercise debug information by creating rules not supported by dateutil."""
    recur_iter = RulesetIterable(
        datetime.datetime(2022, 12, 19, 5, 0, 0),
        [
            rrule.rrule(
                freq=rrule.DAILY,
                dtstart=datetime.datetime(2022, 12, 19, 5, 0, 0),
                count=3,
            )
        ],
        [datetime.date(2022, 12, 22)],
        [datetime.date(2022, 12, 23)],
    )
    with pytest.raises(RecurrenceError) as exc_info:
        list(recur_iter)

    assert exc_info.value.args[0].startswith(
        "Error evaluating recurrence rule (RulesetIterable(dtstart=2022-12-19 05:00:00, "
        "rrule=['DTSTART:20221219T050000\\nRRULE:FREQ=DAILY;COUNT=3'], "
        "rdate=[datetime.date(2022, 12, 22)], "
        "exdate=[datetime.date(2022, 12, 23)]))"
    )


def test_debug_invalid_rule_without_recur() -> None:
    """Test debugging information for another variation of unsupported ruleset."""
    recur_iter = RulesetIterable(
        datetime.datetime(2022, 12, 19, 5, 0, 0),
        [],
        [datetime.date(2022, 12, 22)],
        [datetime.datetime(2022, 12, 23, 5, 0, 0)],
    )
    with pytest.raises(RecurrenceError) as exc_info:
        list(recur_iter)

    assert exc_info.value.args[0].startswith(
        "Error evaluating recurrence rule (RulesetIterable(dtstart=2022-12-19 05:00:00, "
        "rrule=[], "
        "rdate=[datetime.date(2022, 12, 22)], "
        "exdate=[datetime.datetime(2022, 12, 23, 5, 0)]))"
    )


class _YearTransitions:
    """Re-iterable source of ``(Jan 1 of 2000 + i, i)`` transitions, ascending.

    Tracks how many times it is iterated and how many items are pulled so tests
    can assert lazy, single consumption via public behavior alone.
    """

    def __init__(self, count: int | None = None) -> None:
        self.count = count
        self.iterations = 0
        self.pulls = 0

    def __iter__(self) -> Iterator[tuple[datetime.datetime, int]]:
        self.iterations += 1
        indices: Iterable[int] = (
            itertools.count() if self.count is None else range(self.count)
        )

        def _gen() -> Iterator[tuple[datetime.datetime, int]]:
            for i in indices:
                self.pulls += 1
                yield (datetime.datetime(2000 + i, 1, 1), i)

        return _gen()


def _year(value: int) -> datetime.datetime:
    return datetime.datetime(value, 6, 1)


def test_cached_transition_timeline_active_at() -> None:
    """Test resolving items across an unbounded sorted transition source."""
    timeline: CachedTransitionTimeline[int] = CachedTransitionTimeline(
        _YearTransitions()
    )

    # Before the first onset there is no active item.
    assert timeline.active_at(_year(1999)) is None
    # Latest onset at or before the value wins, in any query order.
    assert timeline.active_at(_year(2003)) == 3
    assert timeline.active_at(_year(2001)) == 1
    assert timeline.active_at(_year(2010)) == 10
    # An onset exactly equal to the value is inclusive.
    assert timeline.active_at(datetime.datetime(2007, 1, 1)) == 7


@pytest.mark.parametrize(
    "queries",
    [
        pytest.param([2003, 2001, 2010, 2005], id="out-of-order"),
        pytest.param([2010, 2008, 2006, 2004, 2002], id="descending"),
        pytest.param([2002, 2004, 2006, 2008, 2010], id="ascending"),
        pytest.param([2005, 2005, 2005], id="repeated"),
        pytest.param([2010, 2001, 2010, 2001], id="interleaved-extremes"),
    ],
)
def test_cached_transition_timeline_request_order(queries: list[int]) -> None:
    """Results are correct regardless of the order values are requested in."""
    timeline: CachedTransitionTimeline[int] = CachedTransitionTimeline(
        _YearTransitions()
    )
    # The active item for June of year N is N - 2000 (the Jan 1 onset of year N).
    assert [timeline.active_at(_year(year)) for year in queries] == [
        year - 2000 for year in queries
    ]


def test_cached_transition_timeline_caches_transitions() -> None:
    """The transition source is iterated once and consumed lazily."""
    source = _YearTransitions()
    timeline: CachedTransitionTimeline[int] = CachedTransitionTimeline(source)
    for _ in range(100):
        assert timeline.active_at(_year(2005)) == 5

    # Iterated once, and only far enough to resolve 2005 (not the whole source).
    assert source.iterations == 1
    assert source.pulls <= 8


def test_cached_transition_timeline_deepcopy() -> None:
    """A deep copy resolves independently by re-iterating the shared source."""
    source = _YearTransitions()
    timeline: CachedTransitionTimeline[int] = CachedTransitionTimeline(source)
    assert timeline.active_at(_year(2005)) == 5

    clone = copy.deepcopy(timeline)
    assert clone.active_at(_year(2010)) == 10
    # The original keeps working independently of the copy.
    assert timeline.active_at(_year(2020)) == 20
    # The copy took its own fresh iterator from the shared source.
    assert source.iterations == 2
