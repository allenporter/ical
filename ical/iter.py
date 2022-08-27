"""Library for iterators used in ical.

These iterators are primarily used for implementing recurrence rules where an
object should be returned for a series of date/time, with some modification
based on that date/time. Additionally, it is often necessary to handle multiple
recurrence rules together as a single view of recurring date/times.
"""

from __future__ import annotations

import datetime
import heapq
from collections.abc import Callable, Iterable, Iterator
from typing import TypeVar, Union

T = TypeVar("T")

ItemAdapter = Callable[[Union[datetime.datetime, datetime.date]], T]
"""An adapter for an object in a sorted container (iterator).

The adapter is invoked with the date/time of the current instance and
the callback returns an object at that time (e.g. event with updated time)
"""


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
    """A series of events from a recurring event.

    The inputs are a callback that creates objects at a specific date/time, and an iterable
    of all the relevant date/times (typically a dateutil.rrule or dateutil.rruleset).
    """

    def __init__(
        self,
        item_cb: ItemAdapter[T],
        recur: Iterable[datetime.datetime | datetime.date],
    ) -> None:
        """Initialize timeline."""
        self._item_cb = item_cb
        self._recur = recur

    def __iter__(self) -> Iterator[T]:
        """Return an iterator as a traversal over events in chronological order."""
        return RecurIterator(self._item_cb, iter(self._recur))


class PeekingIterator(Iterator[T]):
    """An iterator with a preview of the next item.

    The primary purpose is to implement a merged iterator where it is needed to
    see the next item in the iterator in order to decide which child iterator
    to pull from.
    """

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
