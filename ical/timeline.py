"""A Timeline is a set of events on a calendar."""

from __future__ import annotations

import datetime
import heapq
from collections.abc import Iterable, Iterator

from .event import Event


class Timeline(Iterable[Event]):
    """A set of events on a calendar."""

    def __init__(self, events: list[Event]) -> None:
        """Initialize timeline."""
        self._events = events

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""

        # Using a heap is faster than sorting if the number of events (n) is
        # much bigger than the number of events we extract from the iterator (k).
        # Complexity: O(n + k log n).
        heap: list[tuple[datetime.date | datetime.datetime, Event]] = []
        for event in self._events:
            heapq.heappush(heap, (event.start, event))
        while heap:
            (_, event) = heapq.heappop(heap)
            yield event

    def included(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator for all events active during the timespan."""
        timespan = Event(summary="", start=start, end=end)
        for event in self:
            if event.is_included_in(timespan):
                yield event

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an interator containing events active during the timespan."""
        timespan = Event(summary="", start=start, end=end)
        for event in self:
            if event.intersects(timespan):
                yield event

    def start_after(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an interator containing events starting after the specified time."""
        for event in self:
            if event.start > instant:
                yield event

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:  # pylint: disable
        """Return an interator containing events starting after the specified time."""
        timespan = Event(summary="", start=instant, end=instant)
        for event in self:
            if event.includes(timespan):
                yield event

    def on_date(self, day: datetime.date) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing all events active on the specified day."""
        return self.overlapping(day, day + datetime.timedelta(days=1))

    def today(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.on_date(datetime.date.today())

    def now(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.at_instant(datetime.datetime.now())
