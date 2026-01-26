"""Component specific iterable functions.

This module contains functions that are helpful for iterating over components
in a calendar. This includes expanding recurring components or other functions
for managing components from a list (e.g. grouping by uid).
"""

import datetime
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from .iter import (
    MergedIterable,
    RecurIterable,
    SortableItemValue,
    SpanOrderedItem,
    LazySortableItem,
    SortableItem,
)
from .types.recur import RecurrenceId, Range
from .event import Event
from .todo import Todo
from .journal import Journal
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
            return cast(ItemType, self._item.model_copy(update=updates))

        ts = Timespan.of(dtstart, dtend, self._tzinfo)
        return LazySortableItem(ts, build)


def items_by_uid(items: list[ItemType]) -> dict[str, list[ItemType]]:
    items_by_uid: dict[str, list[ItemType]] = {}
    for item in items:
        if item.uid is None:
            raise ValueError("Item must have a UID")
        if (values := items_by_uid.get(item.uid)) is None:
            values = []
            items_by_uid[item.uid] = values
        values.append(item)
    return items_by_uid


def _normalize_date(dt: datetime.datetime | datetime.date) -> datetime.datetime | datetime.date:
    """Normalize a datetime to floating time for comparison.

    This matches how recurrence_id values are stored (without timezone info)
    so we can compare them against dates from recurrence expansion.
    """
    if isinstance(dt, datetime.datetime) and dt.tzinfo:
        return dt.replace(tzinfo=None)
    return dt


def _date_lte(a: _DateOrDatetime, b: _DateOrDatetime) -> bool:
    """Safely compare dates, handling mixed datetime/date types.

    Comparing datetime.datetime with datetime.date raises TypeError in Python 3.
    This function safely compares by coercing to the same type when needed.
    """
    # Same type - direct comparison is safe
    if type(a) is type(b):
        return a <= b
    # Mixed types - compare as dates only (spec says types should match,
    # but we handle gracefully if they don't)
    a_date = a.date() if isinstance(a, datetime.datetime) else a
    b_date = b.date() if isinstance(b, datetime.datetime) else b
    return a_date <= b_date


@dataclass
class ThisAndFutureEdit(Generic[ItemType]):
    """Holds a THISANDFUTURE edit with computed time shift information.

    When RECURRENCE-ID;RANGE=THISANDFUTURE is set, the modification applies to
    this instance and all subsequent instances in the recurrence set.
    """

    item: ItemType
    """The edited item with THISANDFUTURE range."""

    effective_date: datetime.datetime | datetime.date
    """The date from which this edit applies (from RECURRENCE-ID)."""

    time_shift: datetime.timedelta
    """The time shift to apply to subsequent instances."""

    @classmethod
    def from_item(cls, item: ItemType) -> "ThisAndFutureEdit[ItemType]":
        """Create a ThisAndFutureEdit from an item with THISANDFUTURE recurrence_id."""
        if not item.recurrence_id:
            raise ValueError("Item must have a recurrence_id")

        effective_date = RecurrenceId.to_value(item.recurrence_id)

        # Calculate time shift: difference between new dtstart and original recurrence date
        # This is the shift that should be applied to all subsequent instances
        time_shift = datetime.timedelta()
        if item.dtstart and effective_date:
            dtstart = item.dtstart
            eff_date = effective_date

            if isinstance(dtstart, datetime.datetime) and isinstance(
                eff_date, datetime.datetime
            ):
                # Handle timezone mismatch: RecurrenceId stores floating time (naive)
                # but dtstart may be timezone-aware
                if dtstart.tzinfo and not eff_date.tzinfo:
                    # Make effective_date timezone-aware using dtstart's timezone
                    eff_date = eff_date.replace(tzinfo=dtstart.tzinfo)
                elif eff_date.tzinfo and not dtstart.tzinfo:
                    # Make dtstart timezone-aware (unlikely but handle it)
                    dtstart = dtstart.replace(tzinfo=eff_date.tzinfo)
                time_shift = dtstart - eff_date
            elif isinstance(dtstart, datetime.date) and isinstance(
                eff_date, datetime.date
            ):
                time_shift = datetime.timedelta(days=(dtstart - eff_date).days)

        return cls(
            item=item,
            effective_date=_normalize_date(effective_date),
            time_shift=time_shift,
        )


class ThisAndFutureRecurAdapter(Generic[ItemType]):
    """An adapter that expands a recurring item with THISANDFUTURE modifications.

    This adapter wraps RecurAdapter to apply time shifts and property changes
    from THISANDFUTURE edits to subsequent recurrence instances.
    """

    def __init__(
        self,
        item: ItemType,
        tzinfo: datetime.tzinfo | None,
        thisandfuture_edits: list[ThisAndFutureEdit[ItemType]],
    ) -> None:
        """Initialize the ThisAndFutureRecurAdapter."""
        self._item = item
        self._duration = item.computed_duration
        self._tzinfo = tzinfo
        # Sort edits by effective date so we can find the applicable one
        self._edits = sorted(thisandfuture_edits, key=lambda e: e.effective_date)

    def _find_applicable_edit(
        self, dt: datetime.datetime | datetime.date
    ) -> ThisAndFutureEdit[ItemType] | None:
        """Find the THISANDFUTURE edit that applies to the given date.

        Returns the most recent edit that has an effective_date <= dt.
        """
        normalized_dt = _normalize_date(dt)
        applicable = None
        for edit in self._edits:
            if _date_lte(edit.effective_date, normalized_dt):
                applicable = edit
            else:
                break
        return applicable

    def get(
        self, dtstart: datetime.datetime | datetime.date
    ) -> SortableItem[Timespan, ItemType]:
        """Return a lazy sortable item, applying THISANDFUTURE modifications if applicable."""
        edit = self._find_applicable_edit(dtstart)

        if edit is None:
            # No THISANDFUTURE edit applies - use the original item
            return RecurAdapter(self._item, self._tzinfo).get(dtstart)

        # Apply the THISANDFUTURE modifications
        shifted_dtstart = dtstart + edit.time_shift

        # Use duration from the edit if available, otherwise from original
        duration = edit.item.computed_duration or self._duration
        dtend = shifted_dtstart + duration if duration else shifted_dtstart

        # Make recurrence_id floating time
        recur_id_dt = dtstart
        if isinstance(recur_id_dt, datetime.datetime) and recur_id_dt.tzinfo:
            recur_id_dt = recur_id_dt.replace(tzinfo=None)
        recurrence_id = RecurrenceId.__parse_property_value__(recur_id_dt)

        def build() -> ItemType:
            # Start with the edit's properties and update with timing
            updates: dict[str, object] = {
                "dtstart": shifted_dtstart,
                "recurrence_id": recurrence_id,
            }

            # Copy relevant properties from the THISANDFUTURE edit
            edit_item = edit.item
            if edit_item.summary:
                updates["summary"] = edit_item.summary
            if edit_item.description:
                updates["description"] = edit_item.description

            # Event-specific properties (location, dtend)
            if isinstance(self._item, Event) and isinstance(edit_item, Event):
                if edit_item.location:
                    updates["location"] = edit_item.location
                if edit_item.dtend:
                    updates["dtend"] = shifted_dtstart + (edit_item.dtend - edit_item.dtstart) if edit_item.dtstart else dtend
                elif self._item.dtend and dtend:
                    updates["dtend"] = dtend

            # Todo-specific properties (location, due)
            if isinstance(self._item, Todo) and isinstance(edit_item, Todo):
                if edit_item.location:
                    updates["location"] = edit_item.location
                if edit_item.due:
                    updates["due"] = shifted_dtstart + (edit_item.due - edit_item.dtstart) if edit_item.dtstart else dtend
                elif self._item.due and dtend:
                    updates["due"] = dtend

            return cast(ItemType, self._item.model_copy(update=updates))

        ts = Timespan.of(shifted_dtstart, dtend, self._tzinfo)
        return LazySortableItem(ts, build)


def merge_and_expand_items(
    items: list[ItemType], tzinfo: datetime.tzinfo
) -> Iterable[SpanOrderedItem[ItemType]]:
    """Merge and expand items that are recurring.

    This function handles the case where a recurring event has been modified
    by creating a separate event with a RECURRENCE-ID. The modified instance
    should replace the original instance from the recurrence expansion, not
    appear as a duplicate.

    It also handles THISANDFUTURE edits where modifications apply to the
    specified instance and all subsequent instances in the recurrence set.
    """
    # Group by UID to find edited instances that override recurrence dates
    grouped = items_by_uid(items)

    iters: list[Iterable[SpanOrderedItem[ItemType]]] = []
    for uid_items in grouped.values():
        # Collect single-instance override dates from edited instances.
        # An edited instance has a recurrence_id (identifying which instance it replaces)
        # but no rrule (it's a single instance, not a recurring series).
        override_dates: set[datetime.datetime | datetime.date] = set()

        # Collect THISANDFUTURE edits (sorted by date)
        thisandfuture_edits: list[ThisAndFutureEdit[ItemType]] = []

        for item in uid_items:
            if item.recurrence_id and not item.rrule:
                recurrence_id = item.recurrence_id
                # Check if this is a THISANDFUTURE edit
                if recurrence_id.range == Range.THIS_AND_FUTURE:
                    thisandfuture_edits.append(ThisAndFutureEdit.from_item(item))
                else:
                    # Single-instance override
                    override_dates.add(
                        _normalize_date(RecurrenceId.to_value(recurrence_id))
                    )

        for item in uid_items:
            if not (recur := item.as_rrule()):
                # Non-recurring item (includes edited instances)
                # Skip THISANDFUTURE edits from direct iteration - they're applied via the adapter
                if item.recurrence_id and item.recurrence_id.range == Range.THIS_AND_FUTURE:
                    continue
                iters.append(
                    [
                        SortableItemValue(
                            item.timespan_of(tzinfo),
                            item,
                        )
                    ]
                )
            else:
                # Recurring item - filter out dates that have been overridden
                # by edited instances with RECURRENCE-ID (single-instance only)
                filtered_recur: Iterable[datetime.datetime | datetime.date] = recur
                if override_dates:
                    filtered_recur = (
                        dt for dt in recur if _normalize_date(dt) not in override_dates
                    )

                # Use THISANDFUTURE adapter if there are edits, otherwise standard adapter
                if thisandfuture_edits:
                    iters.append(
                        RecurIterable(
                            ThisAndFutureRecurAdapter(item, tzinfo, thisandfuture_edits).get,
                            filtered_recur,
                        )
                    )
                else:
                    iters.append(
                        RecurIterable(RecurAdapter(item, tzinfo=tzinfo).get, filtered_recur)
                    )

    return MergedIterable(iters)
