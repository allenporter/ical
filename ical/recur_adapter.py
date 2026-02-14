"""Component specific iterable functions.

This module contains functions that are helpful for iterating over components
in a calendar. This includes expanding recurring components or other functions
for managing components from a list (e.g. grouping by uid).
"""

import datetime
from collections.abc import Iterable, Iterator
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
from .timespan import Timespan


ItemType = TypeVar("ItemType", bound="Event | Todo | Journal")
_DateOrDatetime = datetime.datetime | datetime.date


def _recurrence_id_for(dt: _DateOrDatetime) -> RecurrenceId:
    """Compute the RecurrenceId for a recurrence date.

    This converts a date/datetime from a recurrence expansion into the
    floating-time RecurrenceId string used to identify that instance.
    """
    # Make recurrence_id floating time to avoid dealing with serializing
    # TZID. This value will still be unique within the series and is in
    # the context of dtstart which may have a timezone.
    if isinstance(dt, datetime.datetime) and dt.tzinfo:
        dt = dt.replace(tzinfo=None)
    return RecurrenceId.__parse_property_value__(dt)


class FilteredRecurrenceIterable(Iterable[_DateOrDatetime]):
    """An iterable that filters out dates from a recurrence expansion.

    This wraps a recurrence iterable and excludes dates that have been
    overridden by edited instances (identified by RECURRENCE-ID).
    """

    def __init__(
        self,
        recur: Iterable[_DateOrDatetime],
        exclude_ids: frozenset[RecurrenceId],
    ) -> None:
        """Initialize the filtered iterable."""
        self._recur = recur
        self._exclude_ids = exclude_ids

    def __iter__(self) -> Iterator[_DateOrDatetime]:
        """Iterate over recurrence dates, excluding overridden ones."""
        for dt in self._recur:
            if _recurrence_id_for(dt) not in self._exclude_ids:
                yield dt


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

        dtend = dtstart + self._duration if self._duration else dtstart
        recurrence_id = _recurrence_id_for(dtstart)

        def build() -> ItemType:
            updates = {
                "dtstart": dtstart,
                "recurrence_id": recurrence_id,
            }
            if isinstance(self._item, Event) and self._item.dtend and dtend:
                updates["dtend"] = dtend
            if isinstance(self._item, Todo) and self._item.due and dtend:
                updates["due"] = dtend
            return cast(ItemType, self._item.model_copy(update=updates))

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
    """Merge and expand items that are recurring.

    This function handles the case where a recurring event has been modified
    by creating a separate event with a RECURRENCE-ID. The modified instance
    should replace the original instance from the recurrence expansion, not
    appear as a duplicate.
    """
    # Group by UID to find edited instances that override recurrence dates
    grouped = items_by_uid(items)

    iters: list[Iterable[SpanOrderedItem[ItemType]]] = []
    for uid_items in grouped.values():
        # Collect recurrence_ids from edited instances for O(1) lookup.
        # An edited instance has a recurrence_id (identifying which
        # instance it replaces) but no rrule (it's a single instance).
        exclude_ids = frozenset(
            item.recurrence_id
            for item in uid_items
            if item.recurrence_id and not item.rrule
        )

        for item in uid_items:
            if not (recur := item.as_rrule()):
                # Non-recurring item (includes edited instances)
                iters.append(
                    [
                        SortableItemValue(
                            item.timespan_of(tzinfo),
                            item,
                        )
                    ]
                )
            else:
                # Recurring item - filter out overridden instances if any
                dates = FilteredRecurrenceIterable(recur, exclude_ids) if exclude_ids else recur
                iters.append(
                    RecurIterable(RecurAdapter(item, tzinfo=tzinfo).get, dates)
                )

    return MergedIterable(iters)
