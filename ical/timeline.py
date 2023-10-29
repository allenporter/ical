"""A Timeline is a set of events on a calendar.

A timeline can be used to iterate over all events, including expanded
recurring events. A timeline also supports methods to scan ranges of events
like returning all events happening today or after a specific date.
"""

from __future__ import annotations

import datetime
from collections.abc import Generator, Iterable, Iterator

from .event import Event
from .iter import (
    LazySortableItem,
    MergedIterable,
    RecurIterable,
    SortableItem,
    SortableItemTimeline,
    SortableItemValue,
    SortedItemIterable,
)
from .timespan import Timespan
from .types.recur import RecurrenceId

__all__ = ["Timeline"]


class Timeline(SortableItemTimeline[Event]):
    """A set of events on a calendar.

    A timeline is typically created from a `ics.calendar.Calendar` and is
    typically not instantiated directly.
    """

    def __init__(self, iterable: Iterable[SortableItem[Timespan, Event]]) -> None:
        super().__init__(iterable)

    def __iter__(self) -> Iterator[Event]:
        """Return an iterator as a traversal over events in chronological order."""
        return super().__iter__()

    def included(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator for all events active during the timespan.

        The end date is exclusive.
        """
        return super().included(start, end)

    def overlapping(
        self,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:
        """Return an iterator containing events active during the timespan.

        The end date is exclusive.
        """
        return super().overlapping(start, end)

    def start_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events starting after the specified time."""
        return super().start_after(instant)

    def active_after(
        self,
        instant: datetime.datetime | datetime.date,
    ) -> Iterator[Event]:
        """Return an iterator containing events active after the specified time."""
        return super().active_after(instant)

    def at_instant(
        self,
        instant: datetime.date | datetime.datetime,
    ) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing events starting after the specified time."""
        return super().at_instant(instant)

    def on_date(self, day: datetime.date) -> Iterator[Event]:  # pylint: disable
        """Return an iterator containing all events active on the specified day."""
        return super().on_date(day)

    def today(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return super().today()

    def now(self) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return super().now()


def _event_iterable(
    iterable: list[Event], tzinfo: datetime.tzinfo
) -> Iterable[SortableItem[Timespan, Event]]:
    """Create a sorted iterable from the list of events."""

    def sortable_items() -> Generator[SortableItem[Timespan, Event], None, None]:
        for event in iterable:
            if event.recurring:
                continue
            yield SortableItemValue(event.timespan_of(tzinfo), event)

    return SortedItemIterable(sortable_items, tzinfo)


class RecurAdapter:
    """An adapter that expands an Event instance for a recurrence rule.

    This adapter is given an event, then invoked with a specific date/time instance
    that the event occurs on due to a recurrence rule. The event is copied with
    necessary updated fields to act as a flattened instance of the event.
    """

    def __init__(self, event: Event, tzinfo: datetime.tzinfo | None = None):
        """Initialize the RecurAdapter."""
        self._event = event
        self._event_duration = event.computed_duration
        self._tzinfo = tzinfo

    def get(
        self, dtstart: datetime.datetime | datetime.date
    ) -> SortableItem[Timespan, Event]:
        """Return a lazy sortable item."""

        recur_id_dt = dtstart
        # Make recurrence_id floating time to avoid dealing with serializing
        # TZID. This value will still be unique within the series and is in
        # the context of dtstart which may have a timezone.
        if isinstance(recur_id_dt, datetime.datetime) and recur_id_dt.tzinfo:
            recur_id_dt = recur_id_dt.replace(tzinfo=None)
        recurrence_id = RecurrenceId.__parse_property_value__(recur_id_dt)

        def build() -> Event:
            return self._event.copy(
                update={
                    "dtstart": dtstart,
                    "dtend": dtstart + self._event_duration,
                    "recurrence_id": recurrence_id,
                },
            )

        return LazySortableItem(
            Timespan.of(dtstart, dtstart + self._event_duration, self._tzinfo), build
        )


def calendar_timeline(events: list[Event], tzinfo: datetime.tzinfo) -> Timeline:
    """Create a timeline for events on a calendar, including recurrence."""
    iters: list[Iterable[SortableItem[Timespan, Event]]] = [
        _event_iterable(events, tzinfo=tzinfo)
    ]
    for event in events:
        if not (recur := event.as_rrule()):
            continue
        iters.append(RecurIterable(RecurAdapter(event, tzinfo=tzinfo).get, recur))
    return Timeline(MergedIterable(iters))
