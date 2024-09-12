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
from .iter import (
    SortableItemTimeline,
    SpanOrderedItem,
)
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
