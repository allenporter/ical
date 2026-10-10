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
from .types.period import Period
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
        # A RECURRENCE-ID may be written as a date, a floating time, a time
        # with a TZID or a UTC time, independently of how DTSTART is written.
        # Timed values with a zone name an instant, so they are compared as
        # instants. A floating value is read in the zone of the series, and a
        # floating series is matched by the wall time the value was written in.
        self._dates: set[datetime.date] = set()
        self._wall_times: set[datetime.datetime] = set()
        self._floating: set[datetime.datetime] = set()
        self._instants: set[datetime.datetime] = set()
        for recurrence_id in exclude_ids:
            try:
                value = RecurrenceId.to_value(recurrence_id)
            except ValueError:
                continue
            if not isinstance(value, datetime.datetime):
                self._dates.add(value)
                continue
            self._wall_times.add(value.replace(tzinfo=None))
            if value.tzinfo is None and (
                tzinfo := getattr(recurrence_id, "tzinfo", None)
            ):
                value = value.replace(tzinfo=tzinfo)
            if value.tzinfo is None:
                self._floating.add(value)
            else:
                self._instants.add(value.astimezone(datetime.timezone.utc))

    def _is_excluded(self, dt: _DateOrDatetime) -> bool:
        """Return True if an edited instance replaces this recurrence date."""
        if not isinstance(dt, datetime.datetime):
            return dt in self._dates
        if dt.tzinfo is None:
            return dt in self._wall_times
        return (
            dt.replace(tzinfo=None) in self._floating
            or dt.astimezone(datetime.timezone.utc) in self._instants
        )

    def __iter__(self) -> Iterator[_DateOrDatetime]:
        """Iterate over recurrence dates, excluding overridden ones."""
        for dt in self._recur:
            if not self._is_excluded(dt):
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
        self._duration = item.computed_duration  # ty: ignore[invalid-attribute-access]
        self._tzinfo = tzinfo
        self._period_starts: dict[_DateOrDatetime, Period] = {}
        for p in self._item.rdate:
            if isinstance(p, Period):
                start = p.start
                if isinstance(start, datetime.datetime) and start.tzinfo:
                    start = start.replace(tzinfo=None)
                self._period_starts[start] = p

    def get(
        self, dtstart: datetime.datetime | datetime.date
    ) -> SortableItem[Timespan, ItemType]:
        """Return a lazy sortable item."""
        if self._period_starts:
            dt_key = (
                dtstart.replace(tzinfo=None)
                if isinstance(dtstart, datetime.datetime) and dtstart.tzinfo
                else dtstart
            )
            period = self._period_starts.get(dt_key)
        else:
            period = None

        if period:
            dtend = period.end_value
        else:
            dtend = dtstart + self._duration if self._duration else dtstart

        def build() -> ItemType:
            recurrence_id = _recurrence_id_for(dtstart)
            updates = {
                "dtstart": dtstart,
                "recurrence_id": recurrence_id,
            }
            if isinstance(self._item, Event) and (self._item.dtend or period):
                updates["dtend"] = dtend
            elif isinstance(self._item, Todo) and (self._item.due or period):
                updates["due"] = dtend
            return self._item.model_copy(update=updates)

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
            if not (recur := item.as_rrule()):  # ty: ignore[invalid-argument-type]
                # Non-recurring item (includes edited instances)
                iters.append(
                    [
                        SortableItemValue(
                            item.timespan_of(tzinfo),  # ty: ignore[invalid-argument-type]
                            item,
                        )
                    ]
                )
            else:
                # Recurring item - filter out overridden instances if any
                dates = (
                    FilteredRecurrenceIterable(recur, exclude_ids)
                    if exclude_ids
                    else recur
                )
                iters.append(
                    RecurIterable(RecurAdapter(item, tzinfo=tzinfo).get, dates)
                )

    return MergedIterable(iters)
