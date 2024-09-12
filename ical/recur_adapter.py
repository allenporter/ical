"""Component specific iterable functions.

This module contains functions that are helpful for iterating over components
in a calendar. This includes expanding recurring components or other functions
for managing components from a list (e.g. grouping by uid).
"""

import datetime
from collections.abc import Iterable
from typing import Generic, TypeVar, cast

from .iter import (
    MergedIterable,
    RecurIterable,
    SortableItemValue,
    SpanOrderedItem,
    LazySortableItem,
    SortableItem,
)
from .types.recur import RecurrenceId
from .event import Event
from .todo import Todo
from .journal import Journal
from .freebusy import FreeBusy
from .timespan import Timespan


ItemType = TypeVar("ItemType", bound="Event | Todo | Journal")
_DateOrDatetime = datetime.datetime | datetime.date


class RecurAdapter(Generic[ItemType]):
    """An adapter that expands an Event instance for a recurrence rule.

    This adapter is given an event, then invoked with a specific date/time instance
    that the event occurs on due to a recurrence rule. The event is copied with
    necessary updated fields to act as a flattened instance of the event.
    """

    def __init__(
        self,
        item: ItemType,
        tzinfo: datetime.tzinfo | None = None,
    ) -> None:
        """Initialize the RecurAdapter."""
        self._item = item
        self._duration = item.computed_duration
        self._tzinfo = tzinfo

    def get(
        self, dtstart: datetime.datetime | datetime.date
    ) -> SortableItem[Timespan, ItemType]:
        """Return a lazy sortable item."""

        recur_id_dt = dtstart
        dtend = dtstart + self._duration if self._duration else dtstart
        # Make recurrence_id floating time to avoid dealing with serializing
        # TZID. This value will still be unique within the series and is in
        # the context of dtstart which may have a timezone.
        if isinstance(recur_id_dt, datetime.datetime) and recur_id_dt.tzinfo:
            recur_id_dt = recur_id_dt.replace(tzinfo=None)
        recurrence_id = RecurrenceId.__parse_property_value__(recur_id_dt)

        def build() -> ItemType:
            updates = {
                "dtstart": dtstart,
                "recurrence_id": recurrence_id,
            }
            if isinstance(self._item, Event) and self._item.dtend and dtend:
                updates["dtend"] = dtend
            if isinstance(self._item, Todo) and self._item.due and dtend:
                updates["due"] = dtend
            return cast(ItemType, self._item.copy(update=updates))

        ts = Timespan.of(dtstart, dtend, self._tzinfo)
        return LazySortableItem(ts, build)


def items_by_uid(items: list[ItemType]) -> dict[str, list[ItemType]]:
    items_by_uid: dict[str, list[ItemType]] = {}
    for item in items:
        if item.uid is None:
            raise ValueError("Todo must have a UID")
        if (values := items_by_uid.get(item.uid)) is None:
            values = []
            items_by_uid[item.uid] = values
        values.append(item)
    return items_by_uid


def merge_and_expand_items(
    items: list[ItemType], tzinfo: datetime.tzinfo
) -> Iterable[SpanOrderedItem[ItemType]]:
    """Merge and expand items that are recurring."""
    iters: list[Iterable[SpanOrderedItem[ItemType]]] = []
    for item in items:
        if not (recur := item.as_rrule()):
            iters.append(
                [
                    SortableItemValue(
                        item.timespan_of(tzinfo),
                        item,
                    )
                ]
            )
            continue
        iters.append(RecurIterable(RecurAdapter(item, tzinfo=tzinfo).get, recur))
    return MergedIterable(iters)
