"""A Timeline is a set of events on a calendar.

A timeline can be used to iterate over all events, including expanded
recurring events. A timeline also supports methods to scan ranges of events
like returning all events happening today or after a specific date.
"""

from __future__ import annotations

import datetime
import heapq
import logging
from collections.abc import Iterable, Iterator

from dateutil import rrule

from .event import Event
from .iter import MergedIterable, RecurIterable
from .timespan import Timespan
from .types.recur import RecurrenceId
from .util import normalize_datetime

_LOGGER = logging.getLogger(__name__)

__all__ = ["Timeline"]


class Timeline(Iterable[Event]):
    """A set of events on a calendar.

    A timeline is typically created from a `ics.calendar.Calendar` and is
    typically not instantiated directly.
    """

    def __init__(self, iterable: Iterable[Event]) -> None:
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
        timespan = Timespan.of(start, end)
        for event in self:
            timesp = event.timespan_of(timespan.tzinfo)
            if timesp.is_included_in(timespan):
                yield event
            elif timesp > timespan:
                break

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator containing events active during the timespan.

        The end date is exclusive.
        """
        timespan = Timespan.of(start, end)
        for event in self:
            timesp = event.timespan_of(timespan.tzinfo)
            if timesp.intersects(timespan):
                yield event
            elif timesp > timespan:
                break

    def start_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events starting after the specified time."""
        instant_value = normalize_datetime(instant)
        if not instant_value.tzinfo:
            raise ValueError("Expected tzinfo to be set on normalized datetime")
        for event in self:
            if event.timespan_of(instant_value.tzinfo).start > instant_value:
                yield event

    def active_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events active after the specified time."""
        instant_value = normalize_datetime(instant)
        if not instant_value.tzinfo:
            raise ValueError("Expected tzinfo to be set on normalized datetime")
        for event in self:
            timesp = event.timespan_of(instant_value.tzinfo)
            if timesp.start > instant_value or timesp.end > instant_value:
                yield event

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing events starting after the specified time."""
        timespan = Timespan.of(instant, instant)
        for event in self:
            timesp = event.timespan_of(timespan.tzinfo)
            if timesp.includes(timespan):
                yield event
            elif timesp > timespan:
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
    """Iterable that returns events in sorted order.

    This iterable will ignore recurring events entirely.
    """

    def __init__(self, iterable: Iterable[Event], tzinfo: datetime.tzinfo) -> None:
        """Initialize timeline."""
        self._iterable = iterable
        self._tzinfo = tzinfo

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""
        # Using a heap is faster than sorting if the number of events (n) is
        # much bigger than the number of events we extract from the iterator (k).
        # Complexity: O(n + k log n).
        heap: list[tuple[datetime.date | datetime.datetime, Event]] = []
        for event in iter(self._iterable):
            if event.rrule or event.rdate:
                continue
            heapq.heappush(heap, (event.timespan_of(self._tzinfo).start, event))
        while heap:
            (_, event) = heapq.heappop(heap)
            yield event


class RecurAdapter:
    """An adapter that expands an Event instance for a recurrence rule.

    This adapter is given an event, then invoked with a specific date/time instance
    that the event occurs on due to a recurrence rule. The event is copied with
    necessary updated fields to act as a flattened instance of the event.
    """

    def __init__(self, event: Event):
        """Initialize the RecurAdapter."""
        self._event = event
        self._event_duration = event.computed_duration
        self._is_all_day = not isinstance(self._event.dtstart, datetime.datetime)

    def get(self, dtstart: datetime.datetime | datetime.date) -> Event:
        """Return the next event in the recurrence."""
        if self._is_all_day and isinstance(dtstart, datetime.datetime):
            # Convert back to datetime.date if needed for the original event
            dtstart = datetime.date.fromordinal(dtstart.toordinal())
        return self._event.copy(
            deep=True,
            update={
                "dtstart": dtstart,
                "dtend": dtstart + self._event_duration,
                "recurrence_id": RecurrenceId.__parse_property_value__(dtstart),
            },
        )


def calendar_timeline(events: list[Event], tzinfo: datetime.tzinfo) -> Timeline:
    """Create a timeline for events on a calendar, including recurrence."""
    iters: list[Iterable[Event]] = [EventIterable(events, tzinfo=tzinfo)]
    for event in events:
        if not event.rrule and not event.rdate:
            continue
        ruleset = rrule.rruleset()
        if event.rrule:
            ruleset.rrule(event.rrule.as_rrule(event.start))
        for rdate in event.rdate:
            ruleset.rdate(rdate)  # type: ignore[no-untyped-call]
        for exdate in event.exdate:
            if not isinstance(exdate, datetime.datetime):
                # Convert to datetime matching dateutil's logic
                exdate = datetime.datetime.fromordinal(exdate.toordinal())
            ruleset.exdate(exdate)  # type: ignore[no-untyped-call]
        iters.append(RecurIterable(RecurAdapter(event).get, ruleset))
    return Timeline(MergedIterable(iters))
