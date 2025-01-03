"""Library for iterators used in ical.

These iterators are primarily used for implementing recurrence rules where an
object should be returned for a series of date/time, with some modification
based on that date/time. Additionally, it is often necessary to handle multiple
recurrence rules together as a single view of recurring date/times.

Some of the iterators here are primarily used to extend functionality of `dateutil.rrule`
and work around some of the limitations when building real world calendar applications
such as the ability to make recurrint all day events.

Most of the things in this library should not be consumed directly by calendar users,
but instead for implementing another calendar library as they support behind the
scenes tings like timelines. These internals may be subject to a higher degree of
backwards incompatibility due to the internal nature.
"""

from __future__ import annotations

import datetime
import heapq
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import Any, Generic, TypeVar, Union, cast

from dateutil import rrule

from .timespan import Timespan
from .util import normalize_datetime
from .types.recur import Recur
from .exceptions import CalendarParseError, RecurrenceError

__all__ = [
    "RecurrenceError",
    "RulesetIterable",
    "SortableItemTimeline",
    "SortableItem",
    "SortableItemValue",
    "SortedItemIterable",
    "MergedIterable",
    "RecurIterable",
    "ItemAdapter",
    "LazySortableItem",
]

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


SpanOrderedItem = SortableItem[Timespan, T]
"""A sortable item with a timespan as the key."""


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


class AllDayConverter(Iterable[Union[datetime.date, datetime.datetime]]):
    """An iterable that converts datetimes to all days events."""

    def __init__(self, dt_iter: Iterable[datetime.date | datetime.datetime]):
        """Initialize AllDayConverter."""
        self._dt_iter = dt_iter

    def __iter__(self) -> Iterator[datetime.date | datetime.datetime]:
        """Return an iterator with all day events converted."""
        for value in self._dt_iter:
            # Convert back to datetime.date if needed for the original event
            yield datetime.date.fromordinal(value.toordinal())


class RulesetIterable(Iterable[Union[datetime.datetime, datetime.date]]):
    """A wrapper around the dateutil ruleset library to workaround limitations.

    The `dateutil.rrule` library does not allow iteration in terms of dates and requires
    additional workarounds to support them properly: namely converting back and forth
    between a datetime and a date. It is also very common to have the library throw
    errors that it can't compare properly between dates and times, which are difficult to
    debug. This wrapper is meant to assist with that.
    """

    _converter: Callable[
        [Iterable[Union[datetime.date, datetime.datetime]]],
        Iterable[Union[datetime.date, datetime.datetime]],
    ]

    def __init__(
        self,
        dtstart: datetime.datetime | datetime.date,
        recur: list[Iterable[datetime.datetime | datetime.date]],
        rdate: list[datetime.datetime | datetime.date],
        exdate: list[datetime.datetime | datetime.date],
    ) -> None:
        """Create the RulesetIterable."""
        self._dtstart = dtstart
        self._rrule = recur
        self._rdate = rdate
        self._exdate = exdate
        # dateutil.rrule will convert all input values to datetime even if the
        # input value is a date. If needed, convert back to a date so that
        # comparisons between exdate/rdate as a date in the rruleset will
        # be in the right format.
        if not isinstance(dtstart, datetime.datetime):
            self._converter = AllDayConverter
        else:
            self._converter = lambda x: x

    def _ruleset(self) -> Iterable[datetime.datetime | datetime.date]:
        """Create a dateutil.rruleset."""
        ruleset = rrule.rruleset()
        for rule in self._rrule:
            ruleset.rrule(self._converter(rule))  # type: ignore[arg-type]
        for rdate in self._rdate:
            ruleset.rdate(rdate)  # type: ignore[no-untyped-call]
        for exdate in self._exdate:
            ruleset.exdate(exdate)  # type: ignore[no-untyped-call]
        return ruleset

    def __iter__(self) -> Iterator[datetime.datetime | datetime.date]:
        """Return an iterator as a traversal over events in chronological order."""
        try:
            for value in self._ruleset():
                yield value
        except TypeError as err:
            raise RecurrenceError(
                f"Error evaluating recurrence rule ({self}): {str(err)}"
            ) from err

    def __repr__(self) -> str:
        return (
            f"RulesetIterable(dtstart={self._dtstart}, rrule={[ str(r) for r in self._rrule ]}, "
            f"rdate={self._rdate}, exdate={self._exdate})"
        )


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

    def __init__(self, iterable: Iterable[SpanOrderedItem[T]]) -> None:
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

    def now(self, tz: datetime.tzinfo | None = None) -> Iterator[T]:
        """Return an iterator containing all events active on the specified day."""
        return self.at_instant(datetime.datetime.now(tz=tz))


def as_rrule(
    rrule: Recur | None,
    rdate: list[datetime.datetime | datetime.date],
    exdate: list[datetime.datetime | datetime.date],
    start: datetime.datetime | datetime.date | None,
) -> Iterable[datetime.datetime | datetime.date] | None:
    """Return an iterable containing the occurrences of a recurring event.

    A recurring event is typically evaluated specially on the timeline. The
    data model has a single event, but the timeline evaluates the recurrence
    to expand and copy the the event to multiple places on the timeline.

    This is only valid for events where `recurring` is True.
    """
    if not rrule and not rdate:
        return None
    if not start:
        raise CalendarParseError("Event must have a start date to be recurring")
    return RulesetIterable(
        start,
        [rrule.as_rrule(start)] if rrule else [],
        rdate,
        exdate,
    )
