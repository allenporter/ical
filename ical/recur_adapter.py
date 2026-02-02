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
from .journal import Journal
from .todo import Todo
from .timespan import Timespan


ItemType = TypeVar("ItemType", bound="Event | Todo | Journal")
_DateOrDatetime = datetime.datetime | datetime.date


def _normalize_for_comparison(
    dt: _DateOrDatetime, target_tzinfo: datetime.tzinfo | None
) -> _DateOrDatetime:
    """Normalize a date/datetime for comparison with recurrence dates.

    RECURRENCE-ID values are stored as floating time (no timezone), but the
    recurrence expansion produces timezone-aware datetimes. To compare them,
    we need to normalize both to the same form.
    """
    if not isinstance(dt, datetime.datetime):
        return dt
    # If we have a target tz and the datetime is naive, assume it's in that tz
    if target_tzinfo and dt.tzinfo is None:
        return dt.replace(tzinfo=target_tzinfo)
    # If we have a target tz and datetime is aware, convert to target
    if target_tzinfo and dt.tzinfo:
        return dt.astimezone(target_tzinfo)
    return dt


class FilteredRecurrenceIterable(Iterable[_DateOrDatetime]):
    """An iterable that filters out dates from a recurrence expansion.

    This wraps a recurrence iterable and excludes dates that have been
    overridden by edited instances (identified by RECURRENCE-ID).
    """

    def __init__(
        self,
        recur: Iterable[_DateOrDatetime],
        exclude_dates: frozenset[_DateOrDatetime],
        parent_tzinfo: datetime.tzinfo | None,
    ) -> None:
        """Initialize the filtered iterable."""
        self._recur = recur
        self._exclude_dates = exclude_dates
        self._parent_tzinfo = parent_tzinfo

    def __iter__(self) -> Iterator[_DateOrDatetime]:
        """Iterate over recurrence dates, excluding overridden ones."""
        for dt in self._recur:
            # Normalize recurrence date to match how we stored exclude dates
            normalized = _normalize_for_comparison(dt, self._parent_tzinfo)
            if normalized not in self._exclude_dates:
                yield dt


class RecurAdapter(Generic[ItemType]):
    """An adapter that expands an Event instance for a recurrence rule.

    This adapter is given an event, then invoked with a specific date/time
    instance that the event occurs on due to a recurrence rule. The event is
    copied with necessary updated fields to act as a flattened instance.
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
            return cast(ItemType, self._item.model_copy(update=updates))

        ts = Timespan.of(dtstart, dtend, self._tzinfo)
        return LazySortableItem(ts, build)


def items_by_uid(items: list[ItemType]) -> dict[str, list[ItemType]]:
    result: dict[str, list[ItemType]] = {}
    for item in items:
        if item.uid is None:
            raise ValueError("Todo must have a UID")
        if (values := result.get(item.uid)) is None:
            values = []
            result[item.uid] = values
        values.append(item)
    return result


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
        # Find the parent recurring event to get its timezone
        parent = next(
            (i for i in uid_items if i.rrule and not i.recurrence_id), None
        )
        parent_tzinfo = (
            parent.dtstart.tzinfo
            if parent and isinstance(parent.dtstart, datetime.datetime)
            else None
        )

        # Collect override dates from edited instances as a frozenset for O(1)
        # lookup. An edited instance has a recurrence_id (identifying which
        # instance it replaces) but no rrule (it's a single instance).
        override_dates: set[_DateOrDatetime] = set()
        for item in uid_items:
            if item.recurrence_id and not item.rrule:
                override_date = RecurrenceId.to_value(item.recurrence_id)
                # Normalize to parent's tz for consistent comparison
                normalized = _normalize_for_comparison(
                    override_date, parent_tzinfo
                )
                override_dates.add(normalized)
        exclude_dates = frozenset(override_dates)

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
            elif exclude_dates:
                # Recurring item with overrides - wrap in filter
                filtered = FilteredRecurrenceIterable(
                    recur, exclude_dates, parent_tzinfo
                )
                adapter = RecurAdapter(item, tzinfo=tzinfo)
                iters.append(RecurIterable(adapter.get, filtered))
            else:
                # Recurring item without overrides - use directly
                iters.append(
                    RecurIterable(RecurAdapter(item, tzinfo=tzinfo).get, recur)
                )

    return MergedIterable(iters)
