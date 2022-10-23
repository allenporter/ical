"""Library for iterators used in ical.

These iterators are primarily used for implementing recurrence rules where an
object should be returned for a series of date/time, with some modification
based on that date/time. Additionally, it is often necessary to handle multiple
recurrence rules together as a single view of recurring date/times.
"""

from __future__ import annotations

import datetime
import heapq
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Generic, TypeVar, Union, cast

from .timespan import Timespan
from .util import normalize_datetime

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")
K = TypeVar("K")

ItemAdapter = Callable[[Union[datetime.datetime, datetime.date]], T]
"""An adapter for an object in a sorted container (iterator).

The adapter is invoked with the date/time of the current instance and
the callback returns an object at that time (e.g. event with updated time)
"""


class SortableItem(Generic[K, T], ABC):
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


class SortedItemIterable(Iterable[SortableItem[K, T]]):
    """Iterable that returns sortable items in sortered order.

    This is useful when iterating over a subset of non-recurring events.
    """

    def __init__(
        self,
        iterable: Callable[[], Iterable[SortableItem[K, T]]],
        tzinfo: datetime.tzinfo,
    ) -> None:
        """Initialize timeline."""
        self._iterable = iterable
        self._tzinfo = tzinfo

    def __iter__(self) -> Iterator[SortableItem[K, T]]:
        """Return an iterator as a traversal over events in chronological order."""
        # Using a heap is faster than sorting if the number of events (n) is
        # much bigger than the number of events we extract from the iterator (k).
        # Complexity: O(n + k log n).
        heap: list[SortableItem[K, T]] = []
        for item in self._iterable():
            heapq.heappush(heap, item)
        while heap:
            yield heapq.heappop(heap)


class SortableItemTimeline(Iterable[T]):
    """A set of components on a calendar."""

    def __init__(self, iterable: Iterable[SortableItem[Timespan, T]]) -> None:
        self._iterable = iterable

    def __iter__(self) -> Iterator[T]:
        """Return an iterator as a traversal over events in chronological order."""
        for item in iter(self._iterable):
            yield item.item

    def included(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[T]:
        """Return an iterator for all events active during the timespan.

        The end date is exclusive.
        """
        timespan = Timespan.of(start, end)
        for item in self._iterable:
            if item.key.is_included_in(timespan):
                yield item.item
            elif item.key > timespan:
                break

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[T]:
        """Return an iterator containing events active during the timespan.

        The end date is exclusive.
        """
        timespan = Timespan.of(start, end)
        for item in self._iterable:
            if item.key.intersects(timespan):
                yield item.item
            elif item.key > timespan:
                break

    def start_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[T]:
        """Return an iterator containing events starting after the specified time."""
        instant_value = normalize_datetime(instant)
        if not instant_value.tzinfo:
            raise ValueError("Expected tzinfo to be set on normalized datetime")
        for item in self._iterable:
            if item.key.start > instant_value:
                yield item.item

    def active_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[T]:
        """Return an iterator containing events active after the specified time."""
        instant_value = normalize_datetime(instant)
        if not instant_value.tzinfo:
            raise ValueError("Expected tzinfo to be set on normalized datetime")
        for item in self._iterable:
            if item.key.start > instant_value or item.key.end > instant_value:
                yield item.item

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[T]:  # pylint: disable
        """Return an iterator containing events starting after the specified time."""
        timespan = Timespan.of(instant, instant)
        for item in self._iterable:
            if item.key.includes(timespan):
                yield item.item
            elif item.key > timespan:
                break

    def on_date(self, day: datetime.date) -> Iterator[T]:  # pylint: disable
        """Return an iterator containing all events active on the specified day."""
        return self.overlapping(day, day + datetime.timedelta(days=1))

    def today(self) -> Iterator[T]:
        """Return an iterator containing all events active on the specified day."""
        return self.on_date(datetime.date.today())

    def now(self) -> Iterator[T]:
        """Return an iterator containing all events active on the specified day."""
        return self.at_instant(datetime.datetime.now())
