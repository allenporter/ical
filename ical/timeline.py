"""A Timeline is a set of events on a calendar.

A timeline can be used to iterate over all events, including expanded
recurring events. A timeline also supports methods to scan ranges of events
like returning all events happening today or after a specific date.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Iterator
from typing import TypeVar, Generic, Protocol

from .event import Event
from .timespan import Timespan
from .iter import (
    SortableItemTimeline,
    SortableItemValue,
    SpanOrderedItem,
)
from .util import normalize_datetime
from .recur_adapter import merge_and_expand_items, ItemType

__all__ = ["Timeline", "generic_timeline"]

Timeline = SortableItemTimeline[Event]


def calendar_timeline(events: list[Event], tzinfo: datetime.tzinfo) -> Timeline:
    """Create a timeline for events on a calendar, including recurrence."""
    return Timeline(merge_and_expand_items(events, tzinfo))


def generic_timeline(
    items: list[ItemType], tzinfo: datetime.tzinfo
) -> SortableItemTimeline[ItemType]:
    """Return a timeline view of events on the calendar.

    All events are returned as if the attendee is viewing from the
    specified timezone. For example, this affects the order that All Day
    events are returned.
    """
    return SortableItemTimeline(
        merge_and_expand_items(
            items,
            tzinfo,
        )
    )


def materialize_timeline(
    timeline: SortableItemTimeline[ItemType],
    start: datetime.date | datetime.datetime,
    stop: datetime.date | datetime.datetime | None = None,
    max_number_of_events: int | None = None,
) -> SortableItemTimeline[ItemType]:
    """Materialize a timeline of events between start and optionally stop.

    This functions returns a new Timeline that contains all events
    between start and stop (if specified), but with all recurrence rules
    expanded and instances materialized. This is useful for performance when
    iterating over the same timeline multiple times or for caching
    the results of expensive recurrence calculations.

    Either stop or max_number_of_events must be specified to provide an
    upper bound on the materialized timeline.
    """
    start_dt = normalize_datetime(start)
    if stop:
        timespan = Timespan.of(start, stop)
    elif max_number_of_events is not None:
        timespan = None
    else:
        raise ValueError("Either stop or max_number_of_events must be specified")

    items: list[SortableItemValue[Timespan, ItemType]] = []
    for item in timeline._iterable:
        if max_number_of_events is not None and len(items) >= max_number_of_events:
            break
        if timespan:
            if item.key.intersects(timespan):
                items.append(SortableItemValue(item.key, item.item))
            elif item.key > timespan:
                break
        else:
            # No stop specified, so include all events active after start.
            if item.key.end > start_dt:
                items.append(SortableItemValue(item.key, item.item))

    return SortableItemTimeline[ItemType](items)
