"""Library for iterators used in ical.

These iterators are primarily used for implementing recurrence rules where an
object should be returned for a series of date/time, with some modification
based on that date/time. Additionally, it is often necessary to handle multiple
recurrence rules together as a single view of recurring date/times.

Some of the iterators here are primarily used to extend functionality of `dateutil.rrule`
and work around some of the limitations when building real world calendar applications
such as the ability to make recurring all day events.

Most of the things in this library should not be consumed directly by calendar users,
but instead for implementing another calendar library as they support behind the
scenes things like timelines. These internals may be subject to a higher degree of
backwards incompatibility due to the internal nature.
"""

from __future__ import annotations

import bisect
from collections import OrderedDict
import datetime
import heapq
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Generic, TypeVar, Union

from dateutil import rrule

from .timespan import Timespan
from .util import normalize_datetime
from .types.recur import Recur
from .types.period import Period
from .exceptions import CalendarParseError, RecurrenceError

__all__ = [
    "RecurrenceError",
    "RulesetIterable",
    "SeekableIterable",
    "SortableItemTimeline",
    "SortableItem",
    "SortableItemValue",
    "SortedItemIterable",
    "MergedIterable",
    "RecurIterable",
    "ItemAdapter",
    "LazySortableItem",
    "CachedTransitionTimeline",
    "LazyCachedIterable",
]

_LOGGER = logging.getLogger(__name__)

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

    __slots__ = ("_key",)

    def __init__(self, key: K) -> None:
        """Initialize SortableItem."""
        self._key = key

    @property
    def key(self) -> K:
        """Return the sort key."""
        return self._key

    @property
    def item(self) -> T:
        """Return the underlying item."""
        raise NotImplementedError

    def __lt__(self, other: Any) -> bool:
        """Compare sortable items together."""
        if not isinstance(other, SortableItem):
            return NotImplemented
        return bool(self._key < other._key)


SpanOrderedItem = SortableItem[Timespan, T]
"""A sortable item with a timespan as the key."""


class SeekableIterable(Iterable[T]):
    """An iterable that supports fast-forwarding past a lower bound.

    ``iter_after`` is a conservative optimization hint: implementations may
    skip historical items known to end on or before ``cutoff``, while still
    yielding some earlier items when exact bounds cannot be determined ahead
    of time. Callers must still apply their own range predicates.
    """

    def iter_after(self, cutoff: datetime.datetime) -> Iterator[T]:
        """Return an iterator guaranteed to include all items ending after ``cutoff``."""
        raise NotImplementedError


class SortableItemValue(SortableItem[K, T]):
    """Concrete value implementation of SortableItem."""

    __slots__ = ("_value",)

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

    __slots__ = ("_item_cb",)

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


def _defloat(
    dt: datetime.datetime | datetime.date,
) -> datetime.datetime | datetime.date:
    """Convert a datetime to a floating time."""
    if isinstance(dt, datetime.datetime) and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


class LazyCachedIterable(Iterable[T]):
    """A lazily materialized, append-only cached stream over an underlying iterable.

    Iterating over this object yields previously cached values first, and
    advances the underlying iterator only when new values are requested.
    The internal ``_cache`` list is a gapless, contiguous prefix of the
    underlying stream, allowing multiple independent iterations to share the
    same materialized items.

    Threading model:
    - Instances may be shared across threads (e.g. via ``_RECURRENCE_CACHE`` or
      shared ``Timezone`` instances).
    - ``_cache`` is strictly append-only; already-materialized items at
      ``idx < len(_cache)`` are read without locking.
    - Advancing the underlying generator ``_iter`` and appending to ``_cache``
      is serialized by ``_lock``. The lock is never held across ``yield`` so
      paused or abandoned iterators do not block other threads or deadlock.
    """

    def __init__(self, source: Iterable[T]) -> None:
        """Initialize LazyCachedIterable.

        Args:
            source: The underlying iterable to consume and cache lazily.
        """
        self._source = source
        self._cache: list[T] = []
        self._iter: Iterator[T] | None = None
        self._exhausted = False
        self._lock = threading.Lock()

    def extend_through(self, predicate: Callable[[T], bool]) -> None:
        """Advance the iterator until predicate(last_item) is false or exhausted."""
        if not self._exhausted and (not self._cache or predicate(self._cache[-1])):
            with self._lock:
                if not self._exhausted and (
                    not self._cache or predicate(self._cache[-1])
                ):
                    if self._iter is None:
                        self._iter = iter(self._source)
                    while not self._exhausted and (
                        not self._cache or predicate(self._cache[-1])
                    ):
                        try:
                            val = next(self._iter)
                        except StopIteration:
                            self._exhausted = True
                            break
                        except Exception:
                            self._iter = None
                            raise
                        self._cache.append(val)

    def __iter__(self) -> Iterator[T]:
        """Return an iterator over the cached values, advancing as needed."""
        return self._iter_from_index(0)

    def _iter_from_index(self, idx: int) -> Iterator[T]:
        """Yield cached and newly generated items starting at ``idx``."""
        while True:
            if idx < len(self._cache):
                yield self._cache[idx]
                idx += 1
                continue
            with self._lock:
                if idx < len(self._cache):
                    val = self._cache[idx]
                elif self._exhausted:
                    return
                else:
                    if self._iter is None:
                        self._iter = iter(self._source)
                    try:
                        val = next(self._iter)
                    except StopIteration:
                        self._exhausted = True
                        return
                    except Exception:
                        self._iter = None
                        raise
                    self._cache.append(val)
            yield val
            idx += 1

    def iter_from(self, cutoff: T) -> Iterator[T]:
        """Return an iterator over values starting from the first item >= cutoff."""
        self.extend_through(lambda item: bool(item < cutoff))  # ty: ignore[unsupported-operator]
        idx = bisect.bisect_left(self._cache, cutoff)  # ty: ignore[invalid-argument-type]
        return self._iter_from_index(idx)

    def __deepcopy__(self, memo: dict[int, Any]) -> LazyCachedIterable[T]:
        """Return an independent copy with an empty cache."""
        return LazyCachedIterable(self._source)


# Recurrence cache sizing constants (measured via tracemalloc):
# Each cached rule holds ~11-13 KB of suspended dateutil.rrule generator state
# (year/weekday masks and local daysets), plus ~56-64 bytes per materialized
# date/datetime (including object + list pointer).
#
# Full-capacity (1,024 distinct rules) memory usage by workload:
# - Yearly events (100 years, ~100 instances/rule): ~20.5 MB
# - Monthly events (10 years, ~120 instances/rule): ~18.7 MB
# - Daily events (1 year, ~365 instances/rule): ~33.7 MB
_MAX_RECURRENCE_CACHE_RULES = 1024

_RECURRENCE_CACHE: OrderedDict[
    tuple[Any, ...], LazyCachedIterable[datetime.datetime | datetime.date]
] = OrderedDict()
# Protects _RECURRENCE_CACHE lookups, LRU reordering, and eviction across threads.
# Lock ordering: _RECURRENCE_CACHE_LOCK is a leaf lock (never held while advancing
# iterators or acquiring LazyCachedIterable._lock). LazyCachedIterable._lock for
# higher-level streams (e.g. CachedTransitionTimeline) may acquire _RECURRENCE_CACHE_LOCK
# or a child LazyCachedIterable._lock in a strict DAG.
_RECURRENCE_CACHE_LOCK = threading.Lock()


def _dt_cache_key(
    d: datetime.datetime | datetime.date | Period | Any,
) -> tuple[Any, ...]:
    if isinstance(d, Period):
        return (Period, _dt_cache_key(d.start), _dt_cache_key(d.end), d.duration)
    if isinstance(d, datetime.datetime):
        return (
            datetime.datetime,
            d.replace(tzinfo=None),
            d.tzinfo,
            str(d.tzinfo),
            d.fold,
        )
    return (type(d), d)


def _rule_cache_key(
    dtstart: datetime.datetime | datetime.date,
    rrule: Sequence[Any],
    rdate: Sequence[Any],
    exdate: Sequence[Any],
) -> tuple[Any, ...]:
    return (
        _dt_cache_key(dtstart),
        tuple(str(r) for r in rrule),
        tuple(_dt_cache_key(d) for d in rdate),
        tuple(_dt_cache_key(d) for d in exdate),
    )


def _get_cached_ruleset(
    dtstart: datetime.datetime | datetime.date,
    rrule: Sequence[Any],
    rdate: Sequence[Any],
    exdate: Sequence[Any],
    ruleset_factory: Callable[[], Iterable[datetime.datetime | datetime.date]],
) -> LazyCachedIterable[datetime.datetime | datetime.date]:
    key = _rule_cache_key(dtstart, rrule, rdate, exdate)
    with _RECURRENCE_CACHE_LOCK:
        if key in _RECURRENCE_CACHE:
            _RECURRENCE_CACHE.move_to_end(key)
            return _RECURRENCE_CACHE[key]

        cached = LazyCachedIterable(ruleset_factory())
        _RECURRENCE_CACHE[key] = cached
        if len(_RECURRENCE_CACHE) > _MAX_RECURRENCE_CACHE_RULES:
            _RECURRENCE_CACHE.popitem(last=False)
        return cached


class RulesetIterable(SeekableIterable[Union[datetime.datetime, datetime.date]]):
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
    _defloat: Callable[
        [datetime.datetime | datetime.date], datetime.datetime | datetime.date
    ]

    def __init__(
        self,
        dtstart: datetime.datetime | datetime.date,
        recur: Sequence[Iterable[datetime.datetime | datetime.date]],
        rdate: Sequence[datetime.datetime | datetime.date | Period],
        exdate: Sequence[datetime.datetime | datetime.date],
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
        if (
            isinstance(self._dtstart, datetime.datetime)
            and self._dtstart.tzinfo is None
        ):
            self._defloat = _defloat
        else:
            self._defloat = lambda x: x

    def _ruleset(self) -> Iterable[datetime.datetime | datetime.date]:
        """Create a dateutil.rruleset."""
        ruleset = rrule.rruleset()
        for rule in self._rrule:
            ruleset.rrule(self._converter(rule))  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        for rdate in self._rdate:
            if isinstance(rdate, Period):
                ruleset.rdate(self._defloat(rdate.start))  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            else:
                ruleset.rdate(self._defloat(rdate))  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        for exdate in self._exdate:
            ruleset.exdate(self._defloat(exdate))  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        return ruleset

    def __iter__(self) -> Iterator[datetime.datetime | datetime.date]:
        """Return an iterator as a traversal over events in chronological order."""
        return self._iter_cached(None)

    def iter_after(
        self, cutoff: datetime.datetime
    ) -> Iterator[datetime.datetime | datetime.date]:
        """Return an iterator fast-forwarded toward ``cutoff``."""
        return self._iter_cached(self._coerce_cutoff(cutoff))

    def _coerce_cutoff(
        self, cutoff: datetime.datetime
    ) -> datetime.datetime | datetime.date | None:
        """Convert cutoff to match the type and timezone of ``self._dtstart``."""
        if any(isinstance(r, Period) for r in self._rdate):
            return None
        safe_cutoff = cutoff - datetime.timedelta(days=2)
        if type(self._dtstart) is datetime.date:
            return safe_cutoff.date()
        if isinstance(self._dtstart, datetime.datetime):
            if self._dtstart.tzinfo is None:
                return safe_cutoff.replace(tzinfo=None)
            if safe_cutoff.tzinfo is not None:
                return safe_cutoff.astimezone(self._dtstart.tzinfo)
        return None

    def _iter_cached(
        self, cutoff: datetime.datetime | datetime.date | None
    ) -> Iterator[datetime.datetime | datetime.date]:
        cached = _get_cached_ruleset(
            self._dtstart,
            self._rrule,
            self._rdate,
            self._exdate,
            self._ruleset,
        )
        try:
            if cutoff is not None and type(cutoff) is type(self._dtstart):
                yield from cached.iter_from(cutoff)
            else:
                yield from cached
        except TypeError as err:
            key = _rule_cache_key(self._dtstart, self._rrule, self._rdate, self._exdate)
            with _RECURRENCE_CACHE_LOCK:
                _RECURRENCE_CACHE.pop(key, None)
            raise RecurrenceError(
                f"Error evaluating recurrence rule ({self}): {str(err)}"
            ) from err

    def __deepcopy__(self, memo: dict[int, Any]) -> RulesetIterable:
        """Return an independent copy with an empty cache."""
        return RulesetIterable(
            self._dtstart,
            self._rrule,
            self._rdate,
            self._exdate,
        )

    def __repr__(self) -> str:
        return (
            f"RulesetIterable(dtstart={self._dtstart}, rrule={[str(r) for r in self._rrule]}, "
            f"rdate={self._rdate}, exdate={self._exdate})"
        )


class RecurIterable(SeekableIterable[T]):
    """A series of events from a recurring event.

    The inputs are a callback that creates objects at a specific date/time, and an iterable
    of all the relevant date/times (typically a dateutil.rrule or dateutil.rruleset).
    """

    def __init__(
        self,
        item_cb: ItemAdapter[T],
        recur: Iterable[datetime.datetime | datetime.date],
        duration: datetime.timedelta | None = None,
    ) -> None:
        """Initialize timeline."""
        self._item_cb = item_cb
        self._recur = recur
        self._duration = duration

    def __iter__(self) -> Iterator[T]:
        """Return an iterator as a traversal over events in chronological order."""
        for dtvalue in self._recur:
            yield self._item_cb(dtvalue)

    def iter_after(self, cutoff: datetime.datetime) -> Iterator[T]:
        """Return an iterator fast-forwarded toward occurrences ending after ``cutoff``."""
        if isinstance(self._recur, SeekableIterable):
            dt_cutoff = cutoff - self._duration if self._duration else cutoff
            dt_iter: Iterable[datetime.datetime | datetime.date] = (
                self._recur.iter_after(dt_cutoff)
            )
        else:
            dt_iter = self._recur
        for dtvalue in dt_iter:
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


class MergedIterable(SeekableIterable[T]):
    """An iterator that merges results from underlying sorted iterables."""

    def __init__(self, iters: Sequence[Iterable[T]]) -> None:
        """Initialize MergedIterable."""
        self._iters = iters

    def __iter__(self) -> Iterator[T]:
        return MergedIterator([iter(it) for it in self._iters])

    def iter_after(self, cutoff: datetime.datetime) -> Iterator[T]:
        """Return a merged iterator fast-forwarded toward ``cutoff``."""
        return MergedIterator(
            [
                it.iter_after(cutoff) if isinstance(it, SeekableIterable) else iter(it)
                for it in self._iters
            ]
        )


class SortedItemIterable(SeekableIterable[SpanOrderedItem[T]]):
    """Iterable that returns sortable items in sorted order.

    This is useful when iterating over a subset of non-recurring events.
    """

    def __init__(
        self,
        iterable: Callable[[], Iterable[SpanOrderedItem[T]]],
        tzinfo: datetime.tzinfo,
    ) -> None:
        """Initialize timeline."""
        self._iterable = iterable
        self._tzinfo = tzinfo

    def __iter__(self) -> Iterator[SpanOrderedItem[T]]:
        """Return an iterator as a traversal over events in chronological order."""
        return iter(sorted(self._iterable()))

    def iter_after(self, cutoff: datetime.datetime) -> Iterator[SpanOrderedItem[T]]:
        """Return an iterator of items ending after ``cutoff`` in sorted order."""
        return iter(sorted(item for item in self._iterable() if item.key.end > cutoff))


class SortableItemTimeline(Iterable[T]):
    """A set of components on a calendar.

    Accepts any ``Iterable[SpanOrderedItem[T]]``. When passed a
    :class:`SeekableIterable`, range queries (such as :meth:`included`,
    :meth:`overlapping`, :meth:`start_after`, :meth:`active_after`, and
    :meth:`at_instant`) automatically use :meth:`SeekableIterable.iter_after`
    to fast-forward past historical events.
    """

    def __init__(
        self,
        iterable: Iterable[SpanOrderedItem[T]],
        tzinfo: datetime.tzinfo | None = None,
    ) -> None:
        self._iterable = iterable
        self._tzinfo = tzinfo

    def _iter_after(self, min_end: datetime.datetime) -> Iterable[SpanOrderedItem[T]]:
        """Return an iterable fast-forwarded toward ``min_end`` when supported.

        Does not strictly filter out items ending on or before ``min_end``;
        callers must still check their own range predicates.
        """
        if isinstance(self._iterable, SeekableIterable):
            return self._iterable.iter_after(min_end)
        return self._iterable

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
        timespan = Timespan.of(start, end, self._tzinfo)
        for item in self._iter_after(timespan.start):
            if item.key.is_included_in(timespan):
                yield item.item
            elif item.key.start > timespan.end:
                break

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[T]:
        """Return an iterator containing events active during the timespan.

        The end date is exclusive.
        """
        timespan = Timespan.of(start, end, self._tzinfo)
        for item in self._iter_after(timespan.start):
            if item.key.intersects(timespan):
                yield item.item
            elif item.key > timespan:
                break

    def start_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[T]:
        """Return an iterator containing events starting after the specified time."""
        instant_value = normalize_datetime(instant, self._tzinfo)
        for item in self._iter_after(instant_value):
            if item.key.start > instant_value:
                yield item.item

    def active_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[T]:
        """Return an iterator containing events active after the specified time."""
        instant_value = normalize_datetime(instant, self._tzinfo)
        for item in self._iter_after(instant_value):
            if item.key.start > instant_value or item.key.end > instant_value:
                yield item.item

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[T]:
        """Return an iterator containing events active at the specified instant."""
        timespan = Timespan.of(instant, instant, self._tzinfo)
        for item in self._iter_after(timespan.start - datetime.timedelta(seconds=1)):
            if item.key.includes(timespan):
                yield item.item
            elif item.key > timespan:
                break

    def on_date(self, day: datetime.date) -> Iterator[T]:
        """Return an iterator containing all events active on the specified day."""
        return self.overlapping(day, day + datetime.timedelta(days=1))

    def today(self) -> Iterator[T]:
        """Return an iterator containing all events active today."""
        if self._tzinfo is not None:
            today = datetime.datetime.now(tz=self._tzinfo).date()
        else:
            today = datetime.date.today()
        return self.on_date(today)

    def now(self, tz: datetime.tzinfo | None = None) -> Iterator[T]:
        """Return an iterator containing all events active at the current instant."""
        return self.at_instant(datetime.datetime.now(tz=tz or self._tzinfo))


def as_rrule(
    rrule: Recur | None,
    rdate: list[datetime.datetime | datetime.date | Period],
    exdate: list[datetime.datetime | datetime.date],
    start: datetime.datetime | datetime.date | None,
) -> Iterable[datetime.datetime | datetime.date] | None:
    """Return an iterable containing the occurrences of a recurring event.

    A recurring event is typically evaluated specially on the timeline. The
    data model has a single event, but the timeline evaluates the recurrence
    to expand and copy the event to multiple places on the timeline.

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


class CachedTransitionTimeline(Generic[T]):
    """A lazily materialized timeline over sorted ``(onset, item)`` transitions.

    Given a re-iterable source of sorted ``(onset, item)`` pairs, ``active_at``
    returns the item of the latest transition whose onset is at or before the
    queried value. Transitions are materialized lazily and appended to a cache
    only as far as the highest value queried so far, so an unbounded recurrence
    (such as a timezone observance rule starting in year 1601) is expanded once
    instead of on every lookup. The source must be re-iterable, since a fresh
    iterator is taken from it after a deep copy.
    """

    def __init__(
        self,
        transitions: Iterable[tuple[datetime.datetime | datetime.date, T]],
    ) -> None:
        """Initialize CachedTransitionTimeline with a sorted transition source."""
        self._cached: LazyCachedIterable[
            tuple[datetime.datetime | datetime.date, T]
        ] = LazyCachedIterable(transitions)

    @property
    def _transitions(self) -> Iterable[tuple[datetime.datetime | datetime.date, T]]:
        return self._cached._source

    @property
    def _cache(self) -> list[tuple[datetime.datetime | datetime.date, T]]:
        return self._cached._cache

    def active_at(self, value: datetime.datetime | datetime.date) -> T | None:
        """Return the item active at ``value`` (latest onset <= value)."""
        # Extend the cache only when the request reaches past what has already
        # been materialized; the iterator is append-only and never restarted.
        self._cached.extend_through(lambda item: item[0] <= value)
        index = bisect.bisect_right(
            self._cached._cache, value, key=lambda item: item[0]
        )
        if index == 0:
            return None
        return self._cached._cache[index - 1][1]

    def __deepcopy__(self, memo: dict[int, Any]) -> CachedTransitionTimeline[T]:
        """Return an independent copy with an empty cache.

        ``dateutil.rrule`` iterators hold non-copyable thread locks, so the
        source is not deep-copied. It is re-iterable and shared, and the copy
        takes its own fresh iterator and rebuilds its cache lazily.
        """
        return CachedTransitionTimeline(self._cached._source)
