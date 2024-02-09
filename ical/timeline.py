"""A Timeline is a set of events on a calendar.

A timeline can be used to iterate over all events, including expanded
recurring events. A timeline also supports methods to scan ranges of events
like returning all events happening today or after a specific date.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Iterator

from .event import Event
from .iter import (
    SortableItemTimeline,
    SpanOrderedItem,
)
from .recur_adapter import merge_and_expand_items

__all__ = ["Timeline"]


class Timeline(SortableItemTimeline[Event]):
    """A set of events on a calendar.

    A timeline is typically created from a `ics.calendar.Calendar` and is
    typically not instantiated directly.
    """

    def __init__(self, iterable: Iterable[SpanOrderedItem[Event]]) -> None:
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

    def now(self, tz: datetime.tzinfo | None = None) -> Iterator[Event]:
        """Return an iterator containing all events active on the specified day."""
        return super().now(tz)


def calendar_timeline(events: list[Event], tzinfo: datetime.tzinfo) -> Timeline:
    """Create a timeline for events on a calendar, including recurrence."""
    return Timeline(merge_and_expand_items(events, tzinfo))
