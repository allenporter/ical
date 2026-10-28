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
    SeekableIterable,
    SortableItemValue,
    SortedItemIterable,
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
    if (
        isinstance(dt, datetime.datetime)
        and dt.tzinfo
        and dt.tzinfo != datetime.timezone.utc
    ):
        dt = dt.replace(tzinfo=None)
    return RecurrenceId.__parse_property_value__(dt)


def _canonical_exclude_id(
    rid: RecurrenceId,
    ref_dtstart: _DateOrDatetime | None = None,
) -> RecurrenceId:
    """Normalize a RecurrenceId string to a canonical key for override filtering."""
    try:
        val = RecurrenceId.to_value(rid)
        if isinstance(val, datetime.datetime) and val.tzinfo:
            if (
                isinstance(ref_dtstart, datetime.datetime)
                and ref_dtstart.tzinfo is not None
                and val.tzinfo != ref_dtstart.tzinfo
            ):
                val = val.astimezone(ref_dtstart.tzinfo)
            val = val.replace(tzinfo=None)
        return RecurrenceId.__parse_property_value__(val)
    except ValueError:
        return RecurrenceId(rid.rstrip("Z"))


class FilteredRecurrenceIterable(SeekableIterable[_DateOrDatetime]):
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
        exclude_dts: set[_DateOrDatetime] = set()
        for rid in exclude_ids:
            try:
                val = RecurrenceId.to_value(rid)
            except ValueError:
                continue
            if isinstance(val, datetime.datetime) and val.tzinfo is not None:
                val = val.replace(tzinfo=None)
            exclude_dts.add(val)
        self._exclude_dts = frozenset(exclude_dts)

    def __iter__(self) -> Iterator[_DateOrDatetime]:
        """Iterate over recurrence dates, excluding overridden ones."""
        return self._filter(self._recur)

    def iter_after(self, cutoff: datetime.datetime) -> Iterator[_DateOrDatetime]:
        """Iterate over recurrence dates fast-forwarded toward ``cutoff``, excluding overridden ones."""
        source = (
            self._recur.iter_after(cutoff)
            if isinstance(self._recur, SeekableIterable)
            else self._recur
        )
        return self._filter(source)

    def _filter(self, source: Iterable[_DateOrDatetime]) -> Iterator[_DateOrDatetime]:
        exclude_dts = self._exclude_dts
        if not exclude_dts:
            yield from source
            return
        for dt in source:
            dt_cmp = (
                dt.replace(tzinfo=None)
                if isinstance(dt, datetime.datetime) and dt.tzinfo is not None
                else dt
            )
            if dt_cmp not in exclude_dts:
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
            updates: dict[str, object] = {
                "dtstart": dtstart,
                "recurrence_id": recurrence_id,
            }
            if isinstance(self._item, Event) and (self._item.dtend or period):
                updates["dtend"] = dtend
                if period:
                    updates["duration"] = None
            elif isinstance(self._item, Todo) and (self._item.due or period):
                updates["due"] = dtend
                if period:
                    updates["duration"] = None
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
    non_recurring: list[SpanOrderedItem[ItemType]] = []
    for uid_items in grouped.values():
        override_rids = [
            item.recurrence_id
            for item in uid_items
            if item.recurrence_id and not item.rrule and not item.rdate
        ]

        for item in uid_items:
            if not (recur := item.as_rrule()):
                # Non-recurring item (includes edited instances)
                non_recurring.append(
                    SortableItemValue(
                        item.timespan_of(tzinfo),
                        item,
                    )
                )
            else:
                # Recurring item - filter out overridden instances if any
                exclude_ids = (
                    frozenset(
                        _canonical_exclude_id(rid, item.dtstart)
                        for rid in override_rids
                    )
                    if override_rids
                    else frozenset()
                )
                dates = (
                    FilteredRecurrenceIterable(recur, exclude_ids)
                    if exclude_ids
                    else recur
                )
                iters.append(
                    RecurIterable(
                        RecurAdapter(item, tzinfo=tzinfo).get,
                        dates,
                        item.computed_duration,
                    )
                )

    if non_recurring:
        non_recurring_iter = SortedItemIterable(lambda: non_recurring, tzinfo)
        if not iters:
            return non_recurring_iter
        iters.append(non_recurring_iter)

    return MergedIterable(iters)
