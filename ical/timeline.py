"""A Timeline is a set of events on a calendar."""

from __future__ import annotations

import datetime
import heapq
import logging
from collections.abc import Iterable, Iterator

from dateutil import rrule

from .event import Event
from .types import Frequency, Recur, Weekday
from .util import normalize_datetime

_LOGGER = logging.getLogger(__name__)


class Timeline(Iterable[Event]):
    """A set of events on a calendar."""

    def __init__(self, iterable: Iterable[Event]) -> None:
        """Initialize timeline."""
        self._iterable = iterable

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""
        return iter(self._iterable)

    def included(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator for all events active during the timespan.

        The end date is exclusive.
        """
        timespan = Event(summary="", start=start, end=end)
        for event in self:
            if event.is_included_in(timespan):
                yield event
            elif event > timespan:
                break

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator containing events active during the timespan.

        The end date is exclusive.
        """
        timespan = Event(summary="", start=start, end=end)
        for event in self:
            if event.intersects(timespan):
                yield event
            elif event > timespan:
                break

    def start_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events starting after the specified time."""
        instant_value = normalize_datetime(instant)
        for event in self:
            if event.start_datetime > instant_value:
                yield event

    def active_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events active after the specified time."""
        instant_value = normalize_datetime(instant)
        for event in self:
            if event.start_datetime > instant or event.end_datetime > instant_value:
                yield event

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing events starting after the specified time."""
        timespan = Event(summary="", start=instant, end=instant)
        for event in self:
            if event.includes(timespan):
                yield event
            elif event > timespan:
                break

    def on_date(self, day: datetime.date) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing all events active on the specified day."""
        return self.overlapping(day, day + datetime.timedelta(days=1))

    def today(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.on_date(datetime.date.today())

    def now(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.at_instant(datetime.datetime.now())


class EventIterable(Iterable[Event]):
    """Iterable that returns events in sorted order."""

    def __init__(self, iterable: Iterable[Event]) -> None:
        """Initialize timeline."""
        self._iterable = iterable

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""
        # Using a heap is faster than sorting if the number of events (n) is
        # much bigger than the number of events we extract from the iterator (k).
        # Complexity: O(n + k log n).
        heap: list[tuple[datetime.date | datetime.datetime, Event]] = []
        for event in iter(self._iterable):
            if event.rrule or event.rdate:
                continue
            heapq.heappush(heap, (event.start_datetime, event))
        while heap:
            (_, event) = heapq.heappop(heap)
            yield event


class RecurIterator(Iterator[Event]):
    """An iterator for a recurrence rule."""

    def __init__(
        self, event: Event, recur: Iterator[datetime.datetime | datetime.date]
    ):
        """Initialize the RecurIterator."""
        self._event = event
        self._event_duration = event.computed_duration
        self._recur = recur
        self._is_all_day = not isinstance(self._event.dtstart, datetime.datetime)

    def __iter__(self) -> Iterator[Event]:
        return self

    def __next__(self) -> Event:
        """Return the next event in the recurrence."""
        dtstart: datetime.datetime | datetime.date = next(self._recur)
        if self._is_all_day and isinstance(dtstart, datetime.datetime):
            dtstart = dtstart.date()
        return self._event.copy(
            deep=True,
            update={
                "dtstart": dtstart,
                "dtend": dtstart + self._event_duration,
            },
        )


class RecurIterable(Iterable[Event]):
    """A series of events from a recurring event."""

    def __init__(self, event: Event, recur: rrule.rrule | rrule.rruleset) -> None:
        """Initialize timeline."""
        self._event = event
        self._recur = recur

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""
        return RecurIterator(self._event, iter(self._recur))


RRULE_FREQ = {
    Frequency.DAILY: rrule.DAILY,
    Frequency.WEEKLY: rrule.WEEKLY,
    Frequency.MONTHLY: rrule.MONTHLY,
    Frequency.YEARLY: rrule.YEARLY,
}
RRULE_WEEKDAY = {
    Weekday.MONDAY: rrule.MO,
    Weekday.TUESDAY: rrule.TU,
    Weekday.WEDNESDAY: rrule.WE,
    Weekday.THURSDAY: rrule.TH,
    Weekday.FRIDAY: rrule.FR,
    Weekday.SATURDAY: rrule.SA,
    Weekday.SUNDAY: rrule.SU,
}


def _create_rrule(
    dtstart: datetime.datetime | datetime.date, rule: Recur
) -> rrule.rrule:
    """Create a dateutil rrule for the specified event."""
    if (freq := RRULE_FREQ.get(rule.freq)) is None:
        raise ValueError(f"Unsupported frequency in rrule: {rule.freq}")

    byweekday: list[rrule.weekday] | None = None
    if rule.by_weekday:
        byweekday = [
            RRULE_WEEKDAY[weekday.weekday](
                1 if weekday.occurrence is None else weekday.occurrence
            )
            for weekday in rule.by_weekday
        ]
    return rrule.rrule(
        freq=freq,
        dtstart=dtstart,
        interval=rule.interval,
        count=rule.count,
        until=rule.until,
        byweekday=byweekday,
        bymonthday=rule.by_month_day if rule.by_month_day else None,
        bymonth=rule.by_month if rule.by_month else None,
        cache=True,
    )


class PeekingIterator(Iterator[Event]):
    """An iterator with a preview of the next item."""

    def __init__(self, iterator: Iterator[Event]):
        """Initialize PeekingIterator."""
        self._iterator = iterator
        self._next = next(self._iterator, None)

    def __iter__(self) -> Iterator[Event]:
        """Return this iterator."""
        return self

    def peek(self) -> Event | None:
        """Peek at the next item without consuming."""
        return self._next

    def __next__(self) -> Event:
        """Produce the next item from the merged set."""
        result = self._next
        self._next = next(self._iterator, None)
        if result is None:
            raise StopIteration()
        return result


class MergedIterator(Iterator[Event]):
    """An iterator with a merged sorted view of the underlying sorted iterators."""

    def __init__(self, iters: list[Iterator[Event]]):
        """Initialize MergedIterator."""
        self._iters = [PeekingIterator(iterator) for iterator in iters]

    def __iter__(self) -> Iterator[Event]:
        """Return this iterator."""
        return self

    def __next__(self) -> Event:
        """Produce the next item from the merged set."""
        heap: list[tuple[datetime.datetime, PeekingIterator]] = []
        for iterator in self._iters:
            peekd = iterator.peek()
            if peekd:
                heapq.heappush(heap, (peekd.start_datetime, iterator))
        if not heap:
            raise StopIteration()
        (_, iterator) = heapq.heappop(heap)
        return next(iterator)


class MergedIterable(Iterable[Event]):
    """An iterator that merges results from underlying sorted iterables."""

    def __init__(self, iters: list[Iterable[Event]]) -> None:
        """Initialize MergedIterable."""
        self._iters = iters

    def __iter__(self) -> Iterator[Event]:
        return MergedIterator([iter(it) for it in self._iters])


def calendar_timeline(events: list[Event]) -> Timeline:
    """Create a timeline for events on a calendar, including recurrence."""
    iters: list[Iterable[Event]] = [EventIterable(events)]
    for event in events:
        if not event.rrule and not event.rdate:
            continue
        ruleset = rrule.rruleset()
        if event.rrule:
            ruleset.rrule(_create_rrule(event.start, event.rrule))
        for rdate in event.rdate:
            ruleset.rdate(rdate)  # type: ignore[no-untyped-call]
        for exdate in event.exdate:
            ruleset.exdate(exdate)  # type: ignore[no-untyped-call]
        iters.append(RecurIterable(event, ruleset))
    return Timeline(MergedIterable(iters))
