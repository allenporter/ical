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
from .timezone import Timezone
from .todo import Todo, TodoStatus
from .types import Frequency, Range, Recur, RecurrenceId, RelationshipType, Period
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
        or dtvalue.utcoffset() is None
        or not dtvalue.tzinfo
        or dtvalue.tzinfo == datetime.timezone.utc
        or str(dtvalue.tzinfo) in ("UTC", "Etc/UTC")
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


def _normalize_recurrence_id(recurrence_id: str) -> str:
    """Return the plain date/datetime recurrence_id string without inline parameters."""
    if "=" in recurrence_id.split(":")[0]:
        return recurrence_id.split(":", 1)[1]
    return str(recurrence_id)


def _parse_recurrence_id(
    recurrence_id: str,
    dtstart: datetime.date | datetime.datetime | None,
) -> datetime.date | datetime.datetime:
    """Parse recurrence_id and align its timezone with dtstart if needed."""
    dt_val = RecurrenceId.to_value(recurrence_id)
    if isinstance(dt_val, datetime.datetime):
        if (
            dt_val.tzinfo is None
            and isinstance(recurrence_id, RecurrenceId)
            and recurrence_id.tzinfo is not None
        ):
            dt_val = dt_val.replace(tzinfo=recurrence_id.tzinfo)
        if isinstance(dtstart, datetime.datetime):
            if dtstart.tzinfo is not None:
                if dt_val.tzinfo is None:
                    dt_val = dt_val.replace(tzinfo=dtstart.tzinfo)
                else:
                    dt_val = dt_val.astimezone(dtstart.tzinfo)
            elif dt_val.tzinfo is not None:
                dt_val = dt_val.replace(tzinfo=None)
    return dt_val


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
    norm_recurrence_id = _normalize_recurrence_id(recurrence_id)
    # Match a single item with the specified recurrence_id. If the item is an
    # edited instance match return it
    if item.recurrence_id == recurrence_id or item.recurrence_id == norm_recurrence_id:
        _LOGGER.debug("Matched exact recurrence_id: %s", item)
        return True
    # Otherwise, determine if this instance is in the series
    _LOGGER.debug(
        "Expanding item %s %s to look for match of %s", uid, item.dtstart, recurrence_id
    )
    dtstart = _parse_recurrence_id(recurrence_id, item.dtstart)
    if recurrence_range == Range.THIS_AND_FUTURE and item.exdate:
        if dtstart in item.exdate:
            _LOGGER.debug(
                "Found recurrence_id in exdate for THIS_AND_FUTURE: %s", dtstart
            )
            return True
    for dt in cast(Any, item).as_rrule() or ():
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


def _prepare_update(
    store_item: Event | Todo,
    item: Event | Todo,
    recurrence_id: str | None = None,
    recurrence_range: Range = Range.NONE,
    preserve_override_schedule: bool = False,
) -> dict[str, Any]:
    """Prepare an update to an existing event or todo."""
    exclude_fields = {"dtstamp", "uid", "sequence", "created", "last_modified"}
    if preserve_override_schedule:
        exclude_fields = exclude_fields | {
            "dtstart",
            "dtend",
            "due",
            "duration",
            "rrule",
            "rdate",
            "exdate",
        }
    partial_update = item.model_dump(
        exclude_unset=True,
        exclude=exclude_fields,
    )
    _LOGGER.debug("Preparing update update=%s", item)
    update = {
        "created": store_item.created or store_item.dtstamp,
        "sequence": (store_item.sequence + 1) if store_item.sequence else 1,
        "last_modified": item.dtstamp,
        **partial_update,
        "dtstamp": item.dtstamp,
    }
    if "duration" in partial_update and partial_update["duration"] is not None:
        if isinstance(store_item, Event) and "dtend" not in partial_update:
            update["dtend"] = None
        elif isinstance(store_item, Todo) and "due" not in partial_update:
            update["due"] = None
    elif (
        isinstance(store_item, Event)
        and "dtend" in partial_update
        and partial_update["dtend"] is not None
        and "duration" not in partial_update
    ):
        update["duration"] = None
    elif (
        isinstance(store_item, Todo)
        and "due" in partial_update
        and partial_update["due"] is not None
        and "duration" not in partial_update
    ):
        update["duration"] = None

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
    if rrule := update.get("rrule"):
        update["rrule"] = Recur.model_validate(rrule)
    if recurrence_id and store_item.rrule:
        # Forking a new event off the old event preserves the original uid and
        # recurrence_id.
        update.update(
            {
                "uid": store_item.uid,
                "recurrence_id": _normalize_recurrence_id(recurrence_id),
            }
        )
        # Adjust start and end/due time of the instance or split series
        dtstart: datetime.datetime | datetime.date = _parse_recurrence_id(
            recurrence_id, store_item.dtstart
        )
        if item.dtstart:
            dtstart = item.dtstart
        update["dtstart"] = dtstart
        if (
            isinstance(store_item, Event)
            and store_item.dtend
            and "dtend" not in partial_update
            and "duration" not in partial_update
        ):
            update["dtend"] = dtstart + store_item.computed_duration
        elif (
            isinstance(store_item, Todo)
            and store_item.due
            and "due" not in partial_update
            and "duration" not in partial_update
        ):
            update["due"] = dtstart + store_item.computed_duration

        if recurrence_range == Range.NONE:
            # The new event copied from the original is a single instance,
            # which is not recurring.
            update["rrule"] = None
            if "exdate" not in partial_update:
                update["exdate"] = []
            if "rdate" not in partial_update:
                update["rdate"] = []
        else:
            # Overwriting with a new recurring event
            update["created"] = item.dtstamp
            if "exdate" not in partial_update:
                update["exdate"] = []
    elif "dtstart" in partial_update and item.dtstart is not None:
        if (
            isinstance(store_item, Event)
            and store_item.dtend
            and "dtend" not in partial_update
            and "duration" not in partial_update
            and (
                store_item.rrule
                or store_item.recurrence_id
                or type(item.dtstart) is not type(store_item.dtend)
                or (
                    isinstance(item.dtstart, datetime.datetime)
                    and isinstance(store_item.dtend, datetime.datetime)
                    and (item.dtstart.tzinfo is None)
                    != (store_item.dtend.tzinfo is None)
                )
                or item.dtstart > store_item.dtend
            )
        ):
            update["dtend"] = item.dtstart + store_item.computed_duration
        elif (
            isinstance(store_item, Todo)
            and store_item.due
            and "due" not in partial_update
            and "duration" not in partial_update
            and (
                store_item.rrule
                or store_item.recurrence_id
                or type(item.dtstart) is not type(store_item.due)
                or (
                    isinstance(item.dtstart, datetime.datetime)
                    and isinstance(store_item.due, datetime.datetime)
                    and (item.dtstart.tzinfo is None) != (store_item.due.tzinfo is None)
                )
                or item.dtstart >= store_item.due
            )
        ):
            update["due"] = item.dtstart + store_item.computed_duration
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

        # The store can only manage cascading deletes for some relationship types
        for relation in new_item.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise self._exc(f"Unsupported relationship type {relation.reltype}")

        _LOGGER.debug("Adding item: %s", new_item)
        self._ensure_timezone(new_item.dtstart)
        if isinstance(new_item, Event) and new_item.dtend:
            self._ensure_timezone(new_item.dtend)
        elif isinstance(new_item, Todo) and new_item.due:
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
        if recurrence_id is not None and recurrence_range == Range.THIS_AND_FUTURE:
            for item in self._items:
                if (
                    item.uid == uid
                    and item.recurrence_id
                    and not item.rrule
                    and item not in items_to_delete
                ):
                    target_dt = _parse_recurrence_id(recurrence_id, item.dtstart)
                    item_rid_dt = _parse_recurrence_id(item.recurrence_id, item.dtstart)
                    if normalize_datetime(
                        item_rid_dt, self._tzinfo
                    ) >= normalize_datetime(target_dt, self._tzinfo):
                        items_to_delete.append(item)

        if not items_to_delete:
            raise self._exc(
                f"No existing item with uid/recurrence_id: {uid}/{recurrence_id}"
            )

        for store_item in items_to_delete:
            self._apply_delete(store_item, recurrence_id, recurrence_range)

    def _apply_delete(
        self,
        store_item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
        cascade_children: bool = True,
    ) -> None:
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and _parse_recurrence_id(recurrence_id, store_item.dtstart)
            == store_item.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new event
            recurrence_id = None

        # Deleting all instances in the series
        if not recurrence_id or not store_item.rrule:
            self._items.remove(store_item)
            if cascade_children and not any(
                item.uid == store_item.uid for item in self._items
            ):
                children = [
                    event
                    for event in self._items
                    if any(
                        relation.reltype == RelationshipType.PARENT
                        and relation.uid == store_item.uid
                        for relation in (event.related_to or ())
                    )
                ]
                for child in children:
                    self._items.remove(child)
            return

        exdate = _parse_recurrence_id(recurrence_id, store_item.dtstart)
        if recurrence_range == Range.NONE:
            # A single recurrence instance is removed. Add an exclusion to
            # to the event.
            if exdate not in store_item.exdate:
                store_item.exdate.append(exdate)
            return

        # Assumes any recurrence deletion is valid, and that overwriting
        # the "until" value will not produce more instances. UNTIL is
        # inclusive so it can't include the specified exdate.
        store_item.rrule.count = None
        if (
            isinstance(exdate, datetime.datetime)
            and isinstance(store_item.dtstart, datetime.datetime)
            and store_item.dtstart.tzinfo
        ):
            exdate = exdate.astimezone(datetime.timezone.utc)
        if isinstance(exdate, datetime.datetime) and (
            store_item.rrule.freq
            in (Frequency.HOURLY, Frequency.MINUTELY, Frequency.SECONDLY)
            or store_item.rrule.by_hour
            or store_item.rrule.by_minute
            or store_item.rrule.by_second
        ):
            store_item.rrule.until = exdate - datetime.timedelta(seconds=1)
        else:
            store_item.rrule.until = exdate - datetime.timedelta(days=1)
        if store_item.exdate:
            store_item.exdate = _prune_invalid_exdates(
                store_item.exdate,
                store_item.rrule,
                store_item.rdate,
                store_item.dtstart,
            )
        now = self._dtstamp_fn()
        store_item.dtstamp = now
        store_item.last_modified = now

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

        has_recurring = any(
            store_itm.rrule or store_itm.rdate for _, store_itm in items_to_edit
        )
        if (
            recurrence_id is not None
            and recurrence_range == Range.THIS_AND_FUTURE
            and has_recurring
        ):
            # Remove single-instance overrides at or after the split point
            overrides_to_remove = []
            for existing in self._items:
                if (
                    existing.uid == uid
                    and existing.recurrence_id
                    and not existing.rrule
                ):
                    target_dt = _parse_recurrence_id(recurrence_id, existing.dtstart)
                    existing_rid_dt = _parse_recurrence_id(
                        existing.recurrence_id, existing.dtstart
                    )
                    if normalize_datetime(
                        existing_rid_dt, self._tzinfo
                    ) >= normalize_datetime(target_dt, self._tzinfo):
                        overrides_to_remove.append(existing)
            for override in overrides_to_remove:
                self._items.remove(override)
            items_to_edit = [
                (idx, itm) for idx, itm in items_to_edit if itm.rrule or itm.rdate
            ]

        for store_index, store_item in items_to_edit:
            preserve_override_schedule = bool(
                recurrence_id is None
                and has_recurring
                and store_item.recurrence_id
                and not store_item.rrule
            )
            self._apply_edit(
                store_index,
                store_item,
                item,
                recurrence_id,
                recurrence_range,
                preserve_override_schedule=preserve_override_schedule,
            )

        if recurrence_id is None and has_recurring:
            recurring_items = [
                itm
                for itm in self._items
                if itm.uid == uid and (itm.rrule or itm.rdate)
            ]
            overrides = [
                itm
                for itm in self._items
                if itm.uid == uid and itm.recurrence_id and not itm.rrule
            ]
            for override in overrides:
                assert override.recurrence_id is not None
                still_valid = False
                for rec_item in recurring_items:
                    rid_dt = _parse_recurrence_id(
                        override.recurrence_id, rec_item.dtstart
                    )
                    if rid_dt in rec_item.exdate:
                        still_valid = True
                        break
                if not still_valid:
                    self._items.remove(override)

    def _apply_edit(
        self,
        store_index: int,
        store_item: _T,
        item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
        preserve_override_schedule: bool = False,
    ) -> None:
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and _parse_recurrence_id(recurrence_id, store_item.dtstart)
            == store_item.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new item
            recurrence_id = None

        update = _prepare_update(
            store_item,
            item,
            recurrence_id,
            recurrence_range,
            preserve_override_schedule=preserve_override_schedule,
        )
        if recurrence_range == Range.NONE:
            # Changing the recurrence rule of a single item in the middle of the series
            # is not allowed. It is allowed to convert a single instance item to recurring.
            if item.rrule and store_item.rrule:
                if item.rrule.as_rrule_str() != store_item.rrule.as_rrule_str():
                    raise self._exc(
                        f"Can't update single instance with rrule (rrule={item.rrule})"
                    )
                item.rrule = None

        # Make a deep copy since deletion may update this objects recurrence rules
        new_item = cast(_T, store_item.copy_and_validate(update=update))
        if (
            recurrence_id
            and new_item.rrule
            and new_item.rrule.count
            and store_item.dtstart
        ):
            # The recurring item count needs to skip any items that
            # come before the start of the new item. Use a RulesetIterable
            # to handle workarounds for dateutil.rrule limitations.
            orig_dtstart = _parse_recurrence_id(recurrence_id, store_item.dtstart)
            base_rrule = store_item.rrule or new_item.rrule
            ruleset = RulesetIterable(
                store_item.dtstart,
                [base_rrule.as_rrule(store_item.dtstart)],
                [],
                [],
            )
            for dtvalue in ruleset:
                if dtvalue >= orig_dtstart:
                    break
                new_item.rrule.count = new_item.rrule.count - 1

        # The store can only manage cascading deletes for some relationship types
        for relation in new_item.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise self._exc(f"Unsupported relationship type {relation.reltype}")

        self._ensure_timezone(new_item.dtstart)
        if isinstance(new_item, Event) and new_item.dtend:
            self._ensure_timezone(new_item.dtend)
        elif isinstance(new_item, Todo) and new_item.due:
            self._ensure_timezone(new_item.due)

        # Clean up EXDATE entries that are no longer valid occurrences of the recurrence rule
        if new_item.exdate and (new_item.rrule or new_item.rdate):
            new_item.exdate = _prune_invalid_exdates(
                new_item.exdate, new_item.rrule, new_item.rdate, new_item.dtstart
            )

        # Editing a single instance of a recurring item is like deleting that instance
        # then adding a new instance on the specified date. If recurrence id is not
        # specified then the entire item is replaced.
        if not recurrence_id or not store_item.rrule:
            idx = self._items.index(store_item)
            self._items[idx] = new_item
        else:
            self._apply_delete(
                store_item,
                recurrence_id=recurrence_id,
                recurrence_range=recurrence_range,
                cascade_children=False,
            )
            idx = self._items.index(store_item)
            self._items.insert(idx, new_item)

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
        return todo_list_view(self._calendar.todos, dtstart, tzinfo=self._tzinfo)
