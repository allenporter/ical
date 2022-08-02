"""A Timeline is a set of events on a calendar."""

from __future__ import annotations

import datetime
import heapq
import logging
from collections.abc import Iterable, Iterator

from dateutil import rrule

from .event import Event
from .types import Frequency, Weekday

_LOGGER = logging.getLogger(__name__)


class Timeline(Iterable[Event]):
    """A set of events on a calendar."""

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
        """Return an iterator containing events active during the timespan."""
        timespan = Event(summary="", start=start, end=end)
        for event in self:
            if event.intersects(timespan):
                yield event

    def start_after(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator containing events starting after the specified time."""
        for event in self:
            if event.start > instant:
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

    def on_date(self, day: datetime.date) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing all events active on the specified day."""
        return self.overlapping(day, day + datetime.timedelta(days=1))

    def today(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.on_date(datetime.date.today())

    def now(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return self.at_instant(datetime.datetime.now())


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

    def __init__(self, event: Event, recur: rrule.rrule) -> None:
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


def recur_timeline(event: Event) -> Timeline:
    """Create a timeline for a recurring event."""
    if not event.rrule:
        raise ValueError("Event did not have rrule")
    if not (freq := RRULE_FREQ.get(event.rrule.freq)):
        raise ValueError(f"Unsupported frequency in rrule: {event.rrule}")

    byweekday: list[rrule.weekday] | None = None
    if event.rrule.by_week_day:
        byweekday = [RRULE_WEEKDAY[week_day] for week_day in event.rrule.by_week_day]
    recur = rrule.rrule(
        freq=freq,
        dtstart=event.dtstart,
        interval=event.rrule.interval,
        count=event.rrule.count,
        until=event.rrule.until,
        byweekday=byweekday,
        bymonthday=event.rrule.by_month_day,
    )
    _LOGGER.debug("Creating timeline for rrule=%s", recur)
    return Timeline(RecurIterable(event, recur))
