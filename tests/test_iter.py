"""Tests for the iter library."""

import datetime
from typing import Iterable, Iterator

import pytest

from ical.iter import MergedIterable, MergedIterator, RecurIterable

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
