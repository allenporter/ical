"""Library for iterators used in ical.

These iterators are primarily used for implementing recurrence rules where an
object should be returned for a series of date/time, with some modification
based on that date/time. Additionally, it is often necessary to handle multiple
recurrence rules together as a single view of recurring date/times.
"""

from __future__ import annotations

import datetime
import heapq
from abc import abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Generic, TypeVar, Union, cast

T = TypeVar("T")
K = TypeVar("K")

ItemAdapter = Callable[[Union[datetime.datetime, datetime.date]], T]
"""An adapter for an object in a sorted container (iterator).

The adapter is invoked with the date/time of the current instance and
the callback returns an object at that time (e.g. event with updated time)
"""


class SortableItem(Generic[K, T]):
    """A SortableItem is used to sort an item by an arbitrary key.

    This object is used as a holder of the actual event or recurring event
    such that the sort key used is independent of the event to avoid extra
    copies and comparisons of a large event object.
    """

    def __init__(self, key: K) -> None:
        """Initialize SortableItem."""
        self._key = key

    @property
    def key(self) -> K:
        """Return the sort key."""
        return self._key

    @property
    @abstractmethod
    def item(self) -> T:
        """Return the underlying item."""

    def __lt__(self, other: Any) -> bool:
        """Compare sortable items together."""
        if not isinstance(other, SortableItem):
            return NotImplemented
        return cast(bool, self._key < other.key)


class SortableItemValue(SortableItem[K, T]):
    """Concrete value implementation of SortableItem."""

    def __init__(self, key: K, value: T) -> None:
        """Initialize SortableItemValue."""
        super().__init__(key)
        self._value = value

    @property
    def item(self) -> T:
        """Return the underlying item."""
        return self._value


class LazySortableItem(SortableItem[K, T]):
    """A SortableItem that has its value built lazily."""

    def __init__(
        self,
        key: K,
        item_cb: Callable[[], T],
    ) -> None:
        """Initialize SortableItemValue."""
        super().__init__(key)
        self._item_cb = item_cb

    @property
    def item(self) -> T:
        """Return the underlying item."""
        return self._item_cb()


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
        for dtvalue in self._recur:
            yield self._item_cb(dtvalue)


class MergedIterator(Iterator[T]):
    """An iterator with a merged sorted view of the underlying sorted iterators."""

    def __init__(self, iters: list[Iterator[T]]):
        """Initialize MergedIterator."""
        self._iters = iters
        self._heap: list[tuple[T, int]] | None = None

    def __iter__(self) -> Iterator[T]:
        """Return this iterator."""
        return self

    def _make_heap(self) -> None:
        self._heap = []
        for iter_index, iterator in enumerate(self._iters):
            try:
                next_item = next(iterator)
            except StopIteration:
                pass
            else:
                heapq.heappush(self._heap, (next_item, iter_index))

    def __next__(self) -> T:
        """Produce the next item from the merged set."""

        if self._heap is None:
            self._make_heap()

        if not self._heap:
            raise StopIteration()

        (item, iter_index) = heapq.heappop(self._heap)
        iterator = self._iters[iter_index]
        try:
            next_item = next(iterator)
        except StopIteration:
            pass  # Iterator not added back to heap
        else:
            heapq.heappush(self._heap, (next_item, iter_index))
        return item


class MergedIterable(Iterable[T]):
    """An iterator that merges results from underlying sorted iterables."""

    def __init__(self, iters: list[Iterable[T]]) -> None:
        """Initialize MergedIterable."""
        self._iters = iters

    def __iter__(self) -> Iterator[T]:
        return MergedIterator([iter(it) for it in self._iters])
