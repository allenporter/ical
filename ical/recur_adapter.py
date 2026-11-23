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

    Preserves timezone metadata on the returned RecurrenceId. For ambiguous
    DST fall-back ``fold=1`` occurrences, normalizes to UTC so the identifier
    uniquely distinguishes ``fold=1`` from ``fold=0``.
    """
    if isinstance(dt, datetime.datetime) and dt.tzinfo is not None and dt.fold == 1:
        dt = dt.astimezone(datetime.timezone.utc)
    return RecurrenceId.__parse_property_value__(dt)


class FilteredRecurrenceIterable(SeekableIterable[_DateOrDatetime]):
    """An iterable that filters out dates from a recurrence expansion.

    This wraps a recurrence iterable and excludes dates that have been
    overridden by edited instances (identified by RECURRENCE-ID).
    """

    def __init__(
        self,
        recur: Iterable[_DateOrDatetime],
        exclude_ids: Iterable[RecurrenceId],
        tzinfo: datetime.tzinfo | None = None,
    ) -> None:
        """Initialize the filtered iterable."""
        self._recur = recur
        self._exclude_ids = tuple(exclude_ids)
        self._floating = tzinfo is None
        exclude_keys: set[_DateOrDatetime] = set()
        for rid in self._exclude_ids:
            try:
                exclude_keys.add(
                    RecurrenceId.comparable_key(
                        rid, tzinfo=tzinfo, floating=self._floating
                    )
                )
            except ValueError:
                continue
        self._exclude_keys = frozenset(exclude_keys)

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
        exclude_keys = self._exclude_keys
        if not exclude_keys:
            yield from source
            return
        floating = self._floating
        for dt in source:
            if RecurrenceId.comparable_key(dt, floating=floating) not in exclude_keys:
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
                item_tzinfo = (
                    item.dtstart.tzinfo
                    if isinstance(item.dtstart, datetime.datetime)
                    else None
                )
                dates = (
                    FilteredRecurrenceIterable(
                        recur, override_rids, tzinfo=item_tzinfo
                    )
                    if override_rids
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
