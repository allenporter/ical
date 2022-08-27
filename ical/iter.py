"""Library for iterators used in ical.."""

from __future__ import annotations

import datetime
import heapq
from collections.abc import Callable, Iterable, Iterator
from typing import TypeVar, Union

from dateutil import rrule

T = TypeVar("T")

ItemAdapter = Callable[[Union[datetime.datetime, datetime.date]], T]
"""An adapter for an object in a sorted container (iterator)."""


class RecurIterator(Iterator[T]):
    """An iterator for a recurrence rule."""

    def __init__(
        self,
        item_cb: ItemAdapter[T],
        recur: Iterator[datetime.datetime | datetime.date],
    ):
        """Initialize the RecurIterator."""
        self._item_cb = item_cb
        self._recur = recur

    def __iter__(self) -> Iterator[T]:
        return self

    def __next__(self) -> T:
        """Return the next event in the recurrence."""
        dtstart: datetime.datetime | datetime.date = next(self._recur)
        return self._item_cb(dtstart)


class RecurIterable(Iterable[T]):
    """A series of events from a recurring event."""

    def __init__(
        self, item_cb: ItemAdapter[T], recur: rrule.rrule | rrule.rruleset
    ) -> None:
        """Initialize timeline."""
        self._item_cb = item_cb
        self._recur = recur

    def __iter__(self) -> Iterator[T]:
        """Return an iterator as a traversal over events in chronological order."""
        return RecurIterator(self._item_cb, iter(self._recur))


class PeekingIterator(Iterator[T]):
    """An iterator with a preview of the next item."""

    def __init__(self, iterator: Iterator[T]):
        """Initialize PeekingIterator."""
        self._iterator = iterator
        self._next = next(self._iterator, None)

    def __iter__(self) -> Iterator[T]:
        """Return this iterator."""
        return self

    def peek(self) -> T | None:
        """Peek at the next item without consuming."""
        return self._next

    def __next__(self) -> T:
        """Produce the next item from the merged set."""
        result = self._next
        self._next = next(self._iterator, None)
        if result is None:
            raise StopIteration()
        return result


class MergedIterator(Iterator[T]):
    """An iterator with a merged sorted view of the underlying sorted iterators."""

    def __init__(self, iters: list[Iterator[T]]):
        """Initialize MergedIterator."""
        self._iters = [PeekingIterator(iterator) for iterator in iters]

    def __iter__(self) -> Iterator[T]:
        """Return this iterator."""
        return self

    def __next__(self) -> T:
        """Produce the next item from the merged set."""
        heap: list[tuple[T, PeekingIterator[T]]] = []
        for iterator in self._iters:
            peekd: T | None = iterator.peek()
            if peekd:
                heapq.heappush(heap, (peekd, iterator))
        if not heap:
            raise StopIteration()
        (_, iterator) = heapq.heappop(heap)
        return next(iterator)


class MergedIterable(Iterable[T]):
    """An iterator that merges results from underlying sorted iterables."""

    def __init__(self, iters: list[Iterable[T]]) -> None:
        """Initialize MergedIterable."""
        self._iters = iters

    def __iter__(self) -> Iterator[T]:
        return MergedIterator([iter(it) for it in self._iters])
