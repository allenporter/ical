"""Library for managing the lifecycle of components in a calendar.

A store is like a manager for events within a Calendar, updating the necessary
properties such as modification times, sequence numbers, and ids. This higher
level API is a more convenient API than working with the lower level objects
directly.
"""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import logging
from collections.abc import Callable, Iterable, Generator
from typing import Any, TypeVar, Generic, cast

from .calendar import Calendar
from .component import validate_recurrence_dates
from .event import Event
from .exceptions import StoreError, TodoStoreError, EventStoreError
from .iter import RulesetIterable, as_rrule
from .list import todo_list_view
from .recur_adapter import _recurrence_id_for
from .timezone import Timezone
from .todo import Todo, TodoStatus
from .types import Range, Recur, RecurrenceId, RelationshipType, Period
from .tzif.timezoneinfo import TimezoneInfoError
from .util import dtstamp_factory, local_timezone, normalize_datetime


_LOGGER = logging.getLogger(__name__)


__all__ = [
    "EventStore",
    "EventStoreError",
    "TodoStore",
    "TodoStoreError",
    "StoreError",
]

_T = TypeVar("_T", bound="Event | Todo")
# We won't be able to edit dates more than 100 years in the future, but this
# should be sufficient for most use cases.
_MAX_SCAN_DATE = datetime.date.today() + datetime.timedelta(days=365 * 100)


def _ensure_timezone(
    dtvalue: datetime.datetime | datetime.date | None,
    timezones: list[Timezone],
    exc: type[StoreError] = EventStoreError,
) -> Timezone | None:
    """Create a timezone object for the specified date if it does not already exist."""
    if (
        not isinstance(dtvalue, datetime.datetime)
        or not dtvalue.tzinfo
        or dtvalue.tzinfo == datetime.timezone.utc
    ):
        return None

    # Verify this timezone does not already exist. The number of timezones
    # in a calendar is typically very small so iterate over the whole thing
    # to avoid any synchronization/cache issues.
    key = str(dtvalue.tzinfo)
    for timezone in timezones:
        if timezone.tz_id == key:
            return None

    try:
        return Timezone.from_tzif(key)
    except TimezoneInfoError as err:
        raise exc(f"No timezone information available for event: {key}") from err


def _resolve_recurrence_id(
    recurrence_id: str,
    item_dtstart: datetime.datetime | datetime.date | None,
) -> datetime.datetime | datetime.date:
    """Resolve a recurrence_id string to a date/datetime aligned with item_dtstart."""
    dtstart = RecurrenceId.to_value(recurrence_id)
    if isinstance(dtstart, datetime.datetime) and isinstance(
        item_dtstart, datetime.datetime
    ):
        if item_dtstart.tzinfo is None:
            if dtstart.tzinfo is not None:
                dtstart = dtstart.replace(tzinfo=None)
        elif dtstart.tzinfo is None:
            # No explicit TZID was supplied; fall back to the item's own timezone
            # so the wall-clock time comparison is correct.
            dtstart = dtstart.replace(tzinfo=item_dtstart.tzinfo)
        elif dtstart.tzinfo != item_dtstart.tzinfo:
            dtstart = dtstart.astimezone(item_dtstart.tzinfo)
    return dtstart


def _targets_segment_start(
    store_item: Event | Todo,
    recurrence_id: str,
) -> bool:
    """Return True if recurrence_id identifies the start of store_item."""
    if store_item.dtstart is None:
        return False
    if _resolve_recurrence_id(recurrence_id, store_item.dtstart) == store_item.dtstart:
        return True
    if store_item.recurrence_id is not None and _recurrence_id_matches(
        store_item.recurrence_id, recurrence_id, store_item.dtstart
    ):
        return True
    return False


def _same_temporal_kind(
    dt1: datetime.date | datetime.datetime | None,
    dt2: datetime.date | datetime.datetime | None,
) -> bool:
    """Return True if both values are date-only or both are datetime."""
    if dt1 is None or dt2 is None:
        return dt1 is dt2
    return isinstance(dt1, datetime.datetime) == isinstance(dt2, datetime.datetime)


def _recurrence_id_matches(
    item_recurrence_id: str | None,
    target_recurrence_id: str | None,
    ref_dtstart: datetime.datetime | datetime.date | None,
) -> bool:
    """Return True if two recurrence_id values resolve to the same instant/date."""
    if item_recurrence_id is None or target_recurrence_id is None:
        return item_recurrence_id is target_recurrence_id
    if item_recurrence_id == target_recurrence_id:
        return True
    try:
        dt1 = _resolve_recurrence_id(item_recurrence_id, ref_dtstart)
        dt2 = _resolve_recurrence_id(target_recurrence_id, ref_dtstart)
    except Exception:  # pylint: disable=broad-except
        return False
    return _same_temporal_kind(dt1, dt2) and dt1 == dt2


def _match_item(
    item: _T,
    uid: str,
    recurrence_id: str | None,
    recurrence_range: Range = Range.NONE,
) -> bool:
    """Return True if the item is an instance of a recurring event."""
    if item.uid != uid:
        return False
    if recurrence_id is None:
        # Match all items with the specified uids
        return True
    # Match a single item with the specified recurrence_id. If the item is an
    # edited instance match return it
    if item.recurrence_id is not None and _recurrence_id_matches(
        item.recurrence_id, recurrence_id, item.dtstart
    ):
        _LOGGER.debug("Matched exact recurrence_id: %s", item)
        return True
    # Otherwise, determine if this instance is in the series
    _LOGGER.debug(
        "Expanding item %s %s to look for match of %s", uid, item.dtstart, recurrence_id
    )
    dtstart = _resolve_recurrence_id(recurrence_id, item.dtstart)
    if item.dtstart is not None and not _same_temporal_kind(dtstart, item.dtstart):
        return False
    if (
        recurrence_range == Range.THIS_AND_FUTURE
        and (item.rrule or item.rdate)
        and item.dtstart
    ):
        occurrences = as_rrule(item.rrule, item.rdate, [], item.dtstart)
    else:
        occurrences = cast(Any, item).as_rrule()
    for dt in occurrences or ():
        if isinstance(dt, datetime.datetime):
            if dt.date() > _MAX_SCAN_DATE:
                _LOGGER.debug("Aborting scan, date %s is beyond max scan date", dt)
                break
        elif dt > _MAX_SCAN_DATE:
            _LOGGER.debug("Aborting scan, date %s is beyond max scan date", dt)
            break
        if dt == dtstart:
            _LOGGER.debug("Found expanded recurrence_id: %s", dt)
            return True
    return False


def _match_items(
    items: list[_T],
    uid: str,
    recurrence_id: str | None,
    recurrence_range: Range = Range.NONE,
) -> Generator[tuple[int, _T], None, None]:
    """Return items from the list that match the uid and recurrence_id."""
    for index, item in enumerate(items):
        if _match_item(item, uid, recurrence_id, recurrence_range):
            yield index, item


def _align_rrule_until_for_dtstart(
    rrule: Recur,
    old_dtstart: datetime.date | datetime.datetime | None,
    new_dtstart: datetime.date | datetime.datetime,
) -> Recur:
    """Align rrule.until value type and timezone when dtstart changes."""
    old_until = rrule.until
    if old_until is None:
        return rrule
    if isinstance(new_dtstart, datetime.datetime) and not isinstance(
        old_until, datetime.datetime
    ):
        new_until = datetime.datetime.combine(old_until, new_dtstart.time())
        if new_dtstart.tzinfo is not None:
            new_until = new_until.replace(tzinfo=new_dtstart.tzinfo).astimezone(
                datetime.timezone.utc
            )
        return rrule.model_copy(update={"until": new_until})
    if isinstance(new_dtstart, datetime.datetime) and isinstance(
        old_until, datetime.datetime
    ):
        if new_dtstart.tzinfo is not None and old_until.tzinfo is None:
            new_until = old_until.replace(tzinfo=new_dtstart.tzinfo).astimezone(
                datetime.timezone.utc
            )
            return rrule.model_copy(update={"until": new_until})
        if new_dtstart.tzinfo is None and old_until.tzinfo is not None:
            ref_tz = (
                old_dtstart.tzinfo
                if isinstance(old_dtstart, datetime.datetime)
                else None
            )
            new_until = (
                old_until.astimezone(ref_tz).replace(tzinfo=None)
                if ref_tz is not None
                else old_until.replace(tzinfo=None)
            )
            return rrule.model_copy(update={"until": new_until})
    return rrule


def _find_matching_rdate_period(
    store_item: Event | Todo,
    orig_dtstart: datetime.date | datetime.datetime,
) -> Period | None:
    """Return a Period from store_item.rdate matching orig_dtstart, if any."""
    for rdate_val in store_item.rdate or ():
        if isinstance(rdate_val, Period) and rdate_val.start == orig_dtstart:
            return rdate_val
    return None


def _shift_end_or_due(
    store_item: Event | Todo,
    new_dtstart: datetime.date | datetime.datetime,
    partial_update: dict[str, Any],
    update: dict[str, Any],
    matched_period: Period | None = None,
    same_kind: bool = True,
) -> None:
    """Shift Event.dtend or Todo.due to preserve duration when dtstart changes."""
    if "duration" in partial_update:
        return
    if isinstance(store_item, Event):
        end_field = "dtend"
        has_end = bool(store_item.dtend or matched_period is not None)
        min_days = 1
    else:
        end_field = "due"
        has_end = bool(store_item.due or matched_period is not None)
        min_days = 0
    if not has_end or end_field in partial_update:
        return

    occ_duration = (
        (matched_period.end_value - matched_period.start)
        if matched_period is not None
        else store_item.computed_duration
    )
    if same_kind:
        if occ_duration is not None:
            update[end_field] = new_dtstart + occ_duration
            if matched_period is not None and store_item.duration is not None:
                update["duration"] = None
    elif isinstance(new_dtstart, datetime.datetime):
        delta = (
            occ_duration if occ_duration is not None else datetime.timedelta(hours=1)
        )
        update[end_field] = new_dtstart + delta
    else:
        days = (
            max(min_days, occ_duration.days) if occ_duration is not None else min_days
        )
        update[end_field] = new_dtstart + datetime.timedelta(days=days)


def _segment_cutoff_norm(
    store_item: Event | Todo,
    recurrence_id: str | None,
    include_segment_bounds: bool = False,
) -> tuple[datetime.tzinfo | None, datetime.datetime]:
    """Compute (tzinfo, cutoff_norm) for THIS_AND_FUTURE range truncation/splitting."""
    tzinfo = (
        store_item.dtstart.tzinfo
        if isinstance(store_item.dtstart, datetime.datetime)
        else None
    )
    if recurrence_id is not None:
        split_dt = _resolve_recurrence_id(recurrence_id, store_item.dtstart)
        cutoff_norm = normalize_datetime(split_dt, tzinfo=tzinfo)
    else:
        assert store_item.dtstart is not None
        cutoff_norm = normalize_datetime(store_item.dtstart, tzinfo=tzinfo)
    if include_segment_bounds:
        if store_item.dtstart is not None:
            cutoff_norm = min(
                cutoff_norm, normalize_datetime(store_item.dtstart, tzinfo=tzinfo)
            )
        if store_item.recurrence_id is not None:
            seg_rid_dt = _resolve_recurrence_id(
                store_item.recurrence_id, store_item.dtstart
            )
            cutoff_norm = min(
                cutoff_norm, normalize_datetime(seg_rid_dt, tzinfo=tzinfo)
            )
    return tzinfo, cutoff_norm


def _prepare_forked_occurrence_update(
    store_item: Event | Todo,
    item: Event | Todo,
    recurrence_id: str,
    recurrence_range: Range,
    partial_update: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """Populate update fields when forking an occurrence or split segment."""
    orig_dtstart: datetime.datetime | datetime.date = _resolve_recurrence_id(
        recurrence_id, store_item.dtstart
    )
    update.update(
        {
            "uid": store_item.uid,
            "recurrence_id": str(_recurrence_id_for(orig_dtstart)),
        }
    )
    matched_period = (
        _find_matching_rdate_period(store_item, orig_dtstart)
        if recurrence_range == Range.NONE
        else None
    )
    dtstart: datetime.datetime | datetime.date = item.dtstart or orig_dtstart
    update["dtstart"] = dtstart
    _shift_end_or_due(
        store_item,
        dtstart,
        partial_update,
        update,
        matched_period=matched_period,
        same_kind=True,
    )
    if recurrence_range == Range.NONE:
        update["rrule"] = None
        update["rdate"] = []
        update["exdate"] = []
    else:
        update["created"] = item.dtstamp


def _normalize_base_update_fields(
    store_item: Event | Todo,
    item: Event | Todo,
    partial_update: dict[str, Any],
    update: dict[str, Any],
) -> None:
    """Normalize Todo.completed, duration vs dtend/due, and rrule/dtstart changes."""
    if (
        isinstance(item, Todo)
        and isinstance(store_item, Todo)
        and item.status
        and not item.completed
    ):
        if (
            store_item.status != TodoStatus.COMPLETED
            and item.status == TodoStatus.COMPLETED
        ):
            update["completed"] = item.dtstamp
        if store_item.completed and item.status != TodoStatus.COMPLETED:
            update["completed"] = None
    if (
        "dtend" in partial_update or "due" in partial_update
    ) and "duration" not in partial_update:
        update["duration"] = None
    if "duration" in partial_update:
        if isinstance(store_item, Event) and "dtend" not in partial_update:
            update["dtend"] = None
        if isinstance(store_item, Todo) and "due" not in partial_update:
            update["due"] = None
    if rrule := update.get("rrule"):
        update["rrule"] = Recur.model_validate(rrule)
    if "dtstart" in partial_update and partial_update["dtstart"] is not None:
        new_dtstart = partial_update["dtstart"]
        if store_item.dtstart is not None and not _same_temporal_kind(
            new_dtstart, store_item.dtstart
        ):
            if "exdate" not in partial_update:
                update["exdate"] = []
            if "rdate" not in partial_update:
                update["rdate"] = []
        if (
            "rrule" not in partial_update
            and store_item.rrule is not None
            and store_item.rrule.until is not None
        ):
            update["rrule"] = _align_rrule_until_for_dtstart(
                store_item.rrule, store_item.dtstart, new_dtstart
            )


def _prepare_update(
    store_item: Event | Todo,
    item: Event | Todo,
    recurrence_id: str | None = None,
    recurrence_range: Range = Range.NONE,
) -> dict[str, Any]:
    """Prepare an update to an existing event or todo."""
    partial_update = item.model_dump(
        exclude_unset=True,
        exclude={"dtstamp", "uid", "sequence", "created", "last_modified"},
    )
    _LOGGER.debug("Preparing update update=%s", item)
    update = {
        "created": store_item.created or store_item.dtstamp,
        "sequence": (store_item.sequence + 1) if store_item.sequence else 1,
        "last_modified": item.dtstamp,
        **partial_update,
        "dtstamp": item.dtstamp,
    }
    _normalize_base_update_fields(store_item, item, partial_update, update)
    in_place_segment_start = bool(
        recurrence_id
        and recurrence_range == Range.THIS_AND_FUTURE
        and store_item.recurrence_id is not None
        and _targets_segment_start(store_item, recurrence_id)
    )
    if (
        recurrence_id
        and (store_item.rrule or store_item.rdate)
        and not in_place_segment_start
    ):
        _prepare_forked_occurrence_update(
            store_item,
            item,
            recurrence_id,
            recurrence_range,
            partial_update,
            update,
        )
    elif "dtstart" in partial_update and store_item.dtstart is not None:
        new_dtstart = partial_update["dtstart"]
        same_kind = _same_temporal_kind(new_dtstart, store_item.dtstart)
        if (
            same_kind
            and (
                store_item.rrule
                or store_item.rdate
                or store_item.recurrence_id is not None
            )
        ) or (not same_kind and new_dtstart is not None):
            _shift_end_or_due(
                store_item,
                new_dtstart,
                partial_update,
                update,
                same_kind=same_kind,
            )
    return update


def _prune_invalid_exdates(
    exdate: list[datetime.date | datetime.datetime],
    rrule: Recur | None,
    rdate: list[datetime.date | datetime.datetime | Period],
    dtstart: datetime.date | datetime.datetime | None,
) -> list[datetime.date | datetime.datetime]:
    """Remove EXDATE values that are no longer valid occurrences of the recurrence rule."""
    if not dtstart or not (occurrences_iter := as_rrule(rrule, rdate, [], dtstart)):
        return exdate

    tzinfo = dtstart.tzinfo if isinstance(dtstart, datetime.datetime) else None
    exdate_normalized = {ex: normalize_datetime(ex, tzinfo=tzinfo) for ex in exdate}
    max_exdate_normalized = max(exdate_normalized.values())
    allowed_occurrences = set()
    for occ in occurrences_iter:
        occ_normalized = normalize_datetime(occ, tzinfo=tzinfo)
        if occ_normalized > max_exdate_normalized:
            break
        allowed_occurrences.add(occ_normalized)

    return [ex for ex in exdate if exdate_normalized[ex] in allowed_occurrences]


class GenericStore(Generic[_T]):
    """A store manages the lifecycle of items on a Calendar."""

    def __init__(
        self,
        items: list[_T],
        timezones: list[Timezone],
        exc: type[StoreError],
        dtstamp_fn: Callable[[], datetime.datetime] = lambda: dtstamp_factory(),
        tzinfo: datetime.tzinfo | None = None,
    ):
        """Initialize the EventStore."""
        self._items = items
        self._timezones = timezones
        self._exc = exc
        self._dtstamp_fn = dtstamp_fn
        self._tzinfo = tzinfo or local_timezone()

    def add(self, item: _T) -> _T:
        """Add the specified item to the calendar.

        This will handle assigning modification dates, sequence numbers, etc
        if those fields are unset.

        The store will ensure the `ical.calendar.Calendar` has the necessary
        `ical.timezone.Timezone` needed to fully specify the time information
        when encoded.
        """
        update: dict[str, Any] = {}
        if not item.created:
            update["created"] = item.dtstamp
        if item.sequence is None:
            update["sequence"] = 0
        if isinstance(item, Todo) and not item.dtstart:
            if item.due:
                update["dtstart"] = item.due - datetime.timedelta(days=1)
            else:
                update["dtstart"] = datetime.datetime.now(tz=self._tzinfo)
        if (
            isinstance(item, Todo)
            and not item.completed
            and item.status == TodoStatus.COMPLETED
        ):
            update["completed"] = item.dtstamp
        new_item = cast(_T, item.copy_and_validate(update=update))

        _LOGGER.debug("Adding item: %s", new_item)
        self._ensure_timezone(new_item.dtstart)
        if isinstance(new_item, Event) and new_item.dtend:
            self._ensure_timezone(new_item.dtend)
        if isinstance(new_item, Todo) and new_item.due:
            self._ensure_timezone(new_item.due)
        self._items.append(new_item)
        return new_item

    def delete(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        """Delete the item from the calendar.

        This method is used to delete an existing item. For a recurring item
        either the whole item or instances of an item may be deleted. To
        delete the complete range of a recurring item, the `uid` property
        for the item must be specified and the `recurrence_id` should not
        be specified. To delete an individual instance of the item the
        `recurrence_id` must be specified.

        When deleting individual instances, the range property may specify
        if deletion of just a specific instance, or a range of instances.
        """
        items_to_delete: list[_T] = [
            item
            for _, item in _match_items(
                self._items, uid, recurrence_id, recurrence_range
            )
        ]
        if not items_to_delete:
            raise self._exc(
                f"No existing item with uid/recurrence_id: {uid}/{recurrence_id}"
            )

        for store_item in items_to_delete:
            if store_item in self._items:
                self._apply_delete(store_item, recurrence_id, recurrence_range)

    def _remove_overrides_from(
        self,
        store_item: _T,
        tzinfo: datetime.tzinfo | None,
        cutoff_norm: datetime.datetime,
        exclude_item: _T | None = None,
        remove_store_item: bool = False,
    ) -> set[datetime.datetime]:
        """Remove sibling overrides/segments with recurrence_id >= cutoff_norm."""
        removed_norms: set[datetime.datetime] = set()
        for other in list(self._items):
            if other is store_item:
                if remove_store_item:
                    self._items.remove(other)
                continue
            if (
                other is not exclude_item
                and other.uid == store_item.uid
                and other.recurrence_id is not None
            ):
                other_dt = _resolve_recurrence_id(
                    other.recurrence_id, store_item.dtstart
                )
                other_norm = normalize_datetime(other_dt, tzinfo=tzinfo)
                if other_norm >= cutoff_norm:
                    removed_norms.add(other_norm)
                    self._items.remove(other)
        return removed_norms

    def _delete_related_children(self, parent_uid: str) -> None:
        """Delete child items linked to parent_uid via a PARENT relationship."""
        children = [
            event
            for event in self._items
            if any(
                str(
                    relation.reltype.value
                    if isinstance(relation.reltype, RelationshipType)
                    else (relation.reltype or "PARENT")
                ).upper()
                not in ("CHILD", "SIBLING", "SIBBLING", "NEXT", "FIRST")
                and relation.uid == parent_uid
                for relation in (event.related_to or ())
            )
        ]
        for child in children:
            if child in self._items:
                self._items.remove(child)

    def _truncate_recurring_item(
        self,
        store_item: _T,
        exdate: datetime.date | datetime.datetime,
        tzinfo: datetime.tzinfo | None,
        exdate_norm: datetime.datetime,
        *,
        from_edit: bool = False,
    ) -> None:
        """Truncate store_item's rrule, rdate, and exdate before exdate."""
        if store_item.rrule:
            store_item.rrule.count = None
            if isinstance(exdate, datetime.datetime):
                if (
                    isinstance(store_item.dtstart, datetime.datetime)
                    and store_item.dtstart.tzinfo
                ):
                    exdate = exdate.astimezone(datetime.timezone.utc)
                store_item.rrule.until = exdate - datetime.timedelta(seconds=1)
            else:
                store_item.rrule.until = exdate - datetime.timedelta(days=1)
        if store_item.rdate:
            store_item.rdate = [
                rd
                for rd in store_item.rdate
                if normalize_datetime(
                    rd.start if isinstance(rd, Period) else rd, tzinfo=tzinfo
                )
                < exdate_norm
            ]
        if store_item.exdate and (store_item.rrule or store_item.rdate):
            store_item.exdate = _prune_invalid_exdates(
                store_item.exdate,
                store_item.rrule,
                store_item.rdate,
                store_item.dtstart,
            )
        now = self._dtstamp_fn()
        store_item.dtstamp = now
        store_item.last_modified = now
        if not from_edit:
            store_item.sequence = (
                (store_item.sequence + 1) if store_item.sequence else 1
            )

    def _apply_delete(
        self,
        store_item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
        from_edit: bool = False,
    ) -> None:
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and _targets_segment_start(store_item, recurrence_id)
        ):
            if store_item.recurrence_id is None:
                # Editing the first instance and all forward is the same as editing the
                # entire series so don't bother forking a new event
                recurrence_id = None
            else:
                tzinfo, cutoff_norm = _segment_cutoff_norm(
                    store_item, recurrence_id, include_segment_bounds=True
                )
                self._remove_overrides_from(
                    store_item, tzinfo, cutoff_norm, remove_store_item=True
                )
                return

        # Deleting all instances in the series (or a single non-recurring item)
        if not recurrence_id or not (store_item.rrule or store_item.rdate):
            if not recurrence_id or store_item.recurrence_id is None:
                self._delete_related_children(store_item.uid)
            if not recurrence_id:
                for other in list(self._items):
                    if other.uid == store_item.uid:
                        self._items.remove(other)
            elif store_item in self._items:
                self._items.remove(store_item)
            return

        exdate = _resolve_recurrence_id(recurrence_id, store_item.dtstart)
        if recurrence_range == Range.NONE:
            if exdate not in store_item.exdate:
                store_item.exdate.append(exdate)
            if not from_edit:
                now = self._dtstamp_fn()
                store_item.dtstamp = now
                store_item.last_modified = now
                store_item.sequence = (
                    (store_item.sequence + 1) if store_item.sequence else 1
                )
            return

        tzinfo, exdate_norm = _segment_cutoff_norm(store_item, recurrence_id)
        self._remove_overrides_from(store_item, tzinfo, exdate_norm)
        self._truncate_recurring_item(
            store_item, exdate, tzinfo, exdate_norm, from_edit=from_edit
        )

    def edit(
        self,
        uid: str,
        item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        """Update the item with the specified uid.

        The specified item should be created with minimal fields, just
        including the fields that should be updated. The default fields such
        as `uid` and `dtstamp` may be used to set the uid for a new created item
        when updating a recurring item, or for any modification times.

        For a recurring item, either the whole item or individual instances
        of the item may be edited. To edit the complete range of a recurring
        item the `uid` property must be specified and the `recurrence_id` should
        not be specified. To edit an individual instances of the item the
        `recurrence_id` must be specified. The `recurrence_range` determines if
        just that individual instance is updated or all items following as well.

        The store will ensure the `ical.calendar.Calendar` has the necessary
        `ical.timezone.Timezone` needed to fully specify the item time information
        when encoded.
        """
        items_to_edit: list[tuple[int, _T]] = [
            (store_idx, store_itm)
            for store_idx, store_itm in _match_items(
                self._items, uid, recurrence_id, recurrence_range
            )
        ]
        if not items_to_edit:
            raise self._exc(
                f"No existing item with uid/recurrence_id: {uid}/{recurrence_id}"
            )

        if recurrence_id is None:
            master_matches = [
                (idx, itm) for idx, itm in items_to_edit if itm.recurrence_id is None
            ]
            if master_matches:
                items_to_edit = master_matches
        elif recurrence_range == Range.NONE:
            override_matches = [
                (idx, itm)
                for idx, itm in items_to_edit
                if _recurrence_id_matches(itm.recurrence_id, recurrence_id, itm.dtstart)
                and not itm.rrule
                and not itm.rdate
            ]
            if override_matches:
                items_to_edit = override_matches
        elif recurrence_range == Range.THIS_AND_FUTURE:
            recurring_matches = [
                (idx, itm) for idx, itm in items_to_edit if itm.rrule or itm.rdate
            ]
            if recurring_matches:
                items_to_edit = recurring_matches

        for _, store_item in items_to_edit:
            if store_item not in self._items:
                continue
            store_index = self._items.index(store_item)
            self._apply_edit(
                store_index, store_item, item, recurrence_id, recurrence_range
            )

    @staticmethod
    def _apply_todo_status_transition(
        other: Event | Todo,
        item: Event | Todo,
        new_item: Event | Todo,
        base_update: dict[str, Any],
    ) -> dict[str, Any]:
        """Adjust Todo.completed when propagating a status change to an override or split segment."""
        if (
            isinstance(other, Todo)
            and isinstance(item, Todo)
            and item.status
            and "completed" not in base_update
        ):
            out = dict(base_update)
            if (
                other.status != TodoStatus.COMPLETED
                and item.status == TodoStatus.COMPLETED
            ):
                out["completed"] = new_item.dtstamp
            elif other.completed and item.status != TodoStatus.COMPLETED:
                out["completed"] = None
            return out
        return base_update

    @staticmethod
    def _adjust_split_rrule_count(
        store_item: _T, new_item: _T, recurrence_id: str
    ) -> None:
        """Subtract prior occurrences from new_item.rrule.count when splitting."""
        if not new_item.rrule or not new_item.rrule.count or not store_item.dtstart:
            return
        orig_dtstart: datetime.date | datetime.datetime = _resolve_recurrence_id(
            recurrence_id, store_item.dtstart
        )
        source_rrule = store_item.rrule or new_item.rrule
        ruleset = RulesetIterable(
            store_item.dtstart,
            [source_rrule.as_rrule(store_item.dtstart)],
            [],
            [],
        )
        prior_count = 0
        for dtvalue in ruleset:
            if dtvalue >= orig_dtstart:
                break
            prior_count += 1
        new_item.rrule.count = max(1, new_item.rrule.count - prior_count)

    def _partition_this_and_future_dates(
        self,
        store_item: _T,
        new_item: _T,
        item: _T,
        recurrence_id: str | None,
        in_place_segment_start: bool,
        normalized_from_first_instance: bool,
    ) -> None:
        """Partition rdate and prune purged-override exdates for THIS_AND_FUTURE edits."""
        if not store_item.dtstart:
            return
        split_tzinfo, split_norm = _segment_cutoff_norm(store_item, recurrence_id)
        if (
            recurrence_id is not None
            and not in_place_segment_start
            and "rdate" not in item.model_fields_set
            and new_item.rdate
        ):
            new_item.rdate = [
                rd
                for rd in new_item.rdate
                if normalize_datetime(
                    rd.start if isinstance(rd, Period) else rd,
                    tzinfo=split_tzinfo,
                )
                >= split_norm
            ]
        if "exdate" not in item.model_fields_set and new_item.exdate:
            _, cutoff_norm = _segment_cutoff_norm(
                store_item,
                recurrence_id,
                include_segment_bounds=(
                    in_place_segment_start or normalized_from_first_instance
                ),
            )
            purged_override_norms = {
                normalize_datetime(
                    _resolve_recurrence_id(other.recurrence_id, store_item.dtstart),
                    tzinfo=split_tzinfo,
                )
                for other in self._items
                if other is not store_item
                and other.uid == store_item.uid
                and other.recurrence_id is not None
            }
            purged_override_norms = {
                norm for norm in purged_override_norms if norm >= cutoff_norm
            }
            if purged_override_norms:
                new_item.exdate = [
                    ex
                    for ex in new_item.exdate
                    if normalize_datetime(ex, tzinfo=split_tzinfo)
                    not in purged_override_norms
                ]

    def _sync_overrides_after_series_edit(
        self,
        uid: str,
        item: _T,
        new_item: _T,
        non_schedule_update: dict[str, Any],
        normalized_from_first_instance: bool,
    ) -> None:
        """Prune orphaned overrides or propagate non-schedule updates to valid ones."""
        surviving_segments = [
            seg for seg in self._items if seg.uid == uid and (seg.rrule or seg.rdate)
        ]
        for other in list(self._items):
            if other is new_item or other.uid != uid or other.rrule or other.rdate:
                continue
            if (
                normalized_from_first_instance
                or not surviving_segments
                or not other.recurrence_id
            ):
                self._items.remove(other)
                continue
            is_valid_override = any(
                _same_temporal_kind(
                    other_dt := _resolve_recurrence_id(
                        other.recurrence_id, seg.dtstart
                    ),
                    seg.dtstart,
                )
                and _prune_invalid_exdates(
                    [other_dt], seg.rrule, seg.rdate, seg.dtstart
                )
                for seg in surviving_segments
            )
            if not is_valid_override:
                self._items.remove(other)
            elif non_schedule_update:
                ov_update = self._apply_todo_status_transition(
                    other, item, new_item, non_schedule_update
                )
                ov_idx = self._items.index(other)
                self._items[ov_idx] = cast(
                    _T, other.copy_and_validate(update=ov_update)
                )

    def _apply_whole_series_edit(
        self,
        store_index: int,
        store_item: _T,
        item: _T,
        new_item: _T,
        normalized_from_first_instance: bool,
    ) -> None:
        """Apply a whole-series edit, updating surviving split segments and overrides."""
        self._items[store_index] = new_item
        non_schedule_update = item.model_dump(
            exclude_unset=True,
            exclude={
                "dtstamp",
                "uid",
                "sequence",
                "created",
                "last_modified",
                "dtstart",
                "dtend",
                "due",
                "duration",
                "rrule",
                "rdate",
                "exdate",
                "recurrence_id",
            },
        )
        schedule_redefined = bool(
            normalized_from_first_instance
            or {"dtstart", "rrule", "rdate"} & item.model_fields_set
        )
        for other in list(self._items):
            if other is new_item or other.uid != store_item.uid:
                continue
            if other.rrule or other.rdate:
                if (
                    schedule_redefined
                    or not (new_item.rrule or new_item.rdate)
                    or not other.recurrence_id
                ):
                    self._items.remove(other)
                elif non_schedule_update:
                    seg_update = self._apply_todo_status_transition(
                        other, item, new_item, non_schedule_update
                    )
                    ov_idx = self._items.index(other)
                    self._items[ov_idx] = cast(
                        _T, other.copy_and_validate(update=seg_update)
                    )
        self._sync_overrides_after_series_edit(
            store_item.uid,
            item,
            new_item,
            non_schedule_update,
            normalized_from_first_instance,
        )

    def _validate_and_finalize_edited_item(self, new_item: _T) -> None:
        """Register timezones and prune invalid exdates on an edited item."""
        self._ensure_timezone(new_item.dtstart)
        if isinstance(new_item, Event) and new_item.dtend:
            self._ensure_timezone(new_item.dtend)
        if isinstance(new_item, Todo) and new_item.due:
            self._ensure_timezone(new_item.due)

        if not new_item.rrule and not new_item.rdate:
            new_item.exdate = []
        elif new_item.exdate:
            new_item.exdate = _prune_invalid_exdates(
                new_item.exdate, new_item.rrule, new_item.rdate, new_item.dtstart
            )

    @staticmethod
    def _normalize_edit_target(
        store_item: _T,
        recurrence_id: str | None,
        recurrence_range: Range,
    ) -> tuple[str | None, bool, bool]:
        """Resolve first-instance and split-segment-start flags for _apply_edit."""
        normalized_from_first_instance = False
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and store_item.recurrence_id is None
            and _resolve_recurrence_id(recurrence_id, store_item.dtstart)
            == store_item.dtstart
        ):
            recurrence_id = None
            normalized_from_first_instance = True

        in_place_segment_start = bool(
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and store_item.recurrence_id is not None
            and _targets_segment_start(store_item, recurrence_id)
        )
        return recurrence_id, normalized_from_first_instance, in_place_segment_start

    def _apply_edit(
        self,
        store_index: int,
        store_item: _T,
        item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        (
            recurrence_id,
            normalized_from_first_instance,
            in_place_segment_start,
        ) = self._normalize_edit_target(store_item, recurrence_id, recurrence_range)

        update = _prepare_update(store_item, item, recurrence_id, recurrence_range)
        if recurrence_id is not None and recurrence_range == Range.NONE and item.rrule:
            if (
                not store_item.rrule
                or item.rrule.as_rrule_str() != store_item.rrule.as_rrule_str()
            ):
                raise self._exc(
                    f"Can't update single instance with rrule (rrule={item.rrule})"
                )
            item.rrule = None
            update["rrule"] = None

        new_item = cast(_T, store_item.copy_and_validate(update=update))
        if recurrence_id and not in_place_segment_start:
            self._adjust_split_rrule_count(store_item, new_item, recurrence_id)

        if (
            recurrence_id or normalized_from_first_instance
        ) and recurrence_range == Range.THIS_AND_FUTURE:
            self._partition_this_and_future_dates(
                store_item,
                new_item,
                item,
                recurrence_id,
                in_place_segment_start,
                normalized_from_first_instance,
            )

        self._validate_and_finalize_edited_item(new_item)

        if recurrence_id is None:
            self._apply_whole_series_edit(
                store_index,
                store_item,
                item,
                new_item,
                normalized_from_first_instance,
            )
            return

        if not store_item.rrule and not store_item.rdate:
            self._items[store_index] = new_item
            return

        if in_place_segment_start and store_item.dtstart is not None:
            self._items[store_index] = new_item
            split_tzinfo, cutoff_norm = _segment_cutoff_norm(
                store_item, recurrence_id, include_segment_bounds=True
            )
            self._remove_overrides_from(
                store_item, split_tzinfo, cutoff_norm, exclude_item=new_item
            )
            return

        self._apply_delete(
            store_item,
            recurrence_id=recurrence_id,
            recurrence_range=recurrence_range,
            from_edit=True,
        )
        insert_idx = (
            self._items.index(store_item) if store_item in self._items else store_index
        )
        self._items.insert(insert_idx, new_item)

    def _ensure_timezone(
        self, dtvalue: datetime.datetime | datetime.date | None
    ) -> None:
        if (
            new_timezone := _ensure_timezone(dtvalue, self._timezones, self._exc)
        ) is not None:
            self._timezones.append(new_timezone)


class EventStore(GenericStore[Event]):
    """An event store manages the lifecycle of events on a Calendar.

    An `ical.calendar.Calendar` is a lower level object that can be directly
    manipulated to add/remove an `ical.event.Event`. That is, it does not
    handle updating timestamps, incrementing sequence numbers, or managing
    lifecycle of a recurring event during an update.


    Here is an example for setting up an `EventStore`:

    ```python
    import datetime
    from ical.calendar import Calendar
    from ical.event import Event
    from ical.store import EventStore
    from ical.types import Recur

    calendar = Calendar()
    store = EventStore(calendar)

    event = Event(
        summary="Event summary",
        start="2022-07-03",
        end="2022-07-04",
        rrule=Recur.from_rrule("FREQ=WEEKLY;COUNT=3"),
    )
    store.add(event)
    ```

    This will add events to the calendar:
    ```python3
    for event in calendar.timeline:
        print(event.summary, event.uid, event.recurrence_id, event.dtstart)
    ```
    With output like this:
    ```
    Event summary a521cf45-2c02-11ed-9e5c-066a07ffbaf5 20220703 2022-07-03
    Event summary a521cf45-2c02-11ed-9e5c-066a07ffbaf5 20220710 2022-07-10
    Event summary a521cf45-2c02-11ed-9e5c-066a07ffbaf5 20220717 2022-07-17
    ```

    You may also delete an event, or a specific instance of a recurring event:
    ```python
    # Delete a single instance of the recurring event
    store.delete(uid=event.uid, recurrence_id="20220710")
    ```

    Then viewing the store using the `print` example removes the individual
    instance in the event:
    ```
    Event summary a521cf45-2c02-11ed-9e5c-066a07ffbaf5 20220703 2022-07-03
    Event summary a521cf45-2c02-11ed-9e5c-066a07ffbaf5 20220717 2022-07-17
    ```

    Editing an event is also supported:
    ```python
    store.edit("event-uid-1", Event(summary="New Summary"))
    ```
    """

    def __init__(
        self,
        calendar: Calendar,
        dtstamp_fn: Callable[[], datetime.datetime] = lambda: dtstamp_factory(),
    ):
        """Initialize the EventStore."""
        super().__init__(
            calendar.events,
            calendar.timezones,
            EventStoreError,
            dtstamp_fn,
            tzinfo=None,
        )


class TodoStore(GenericStore[Todo]):
    """A To-do store manages the lifecycle of to-dos on a Calendar."""

    def __init__(
        self,
        calendar: Calendar,
        tzinfo: datetime.tzinfo | None = None,
        dtstamp_fn: Callable[[], datetime.datetime] = lambda: dtstamp_factory(),
    ):
        """Initialize the TodoStore."""
        super().__init__(
            calendar.todos,
            calendar.timezones,
            TodoStoreError,
            dtstamp_fn,
            tzinfo=tzinfo,
        )
        self._calendar = calendar

    def todo_list(self, dtstart: datetime.datetime | None = None) -> Iterable[Todo]:
        """Return a list of all todos on the calendar.

        This view accounts for recurring todos.
        """
        return todo_list_view(self._calendar.todos, dtstart)
