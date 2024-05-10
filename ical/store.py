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
from .event import Event
from .exceptions import StoreError, TodoStoreError, EventStoreError
from .iter import RulesetIterable
from .list import todo_list_view
from .timezone import Timezone
from .todo import Todo
from .types import Range, Recur, RecurrenceId, RelationshipType
from .tzif.timezoneinfo import TimezoneInfoError
from .util import dtstamp_factory, local_timezone


_LOGGER = logging.getLogger(__name__)


__all__ = [
    "EventStore",
    "EventStoreError",
    "TodoStore",
    "TodoStoreError",
    "StoreError",
]

_T = TypeVar("_T", bound="Event | Todo")


def _ensure_timezone(
    dtstart: datetime.datetime | datetime.date | None, timezones: list[Timezone]
) -> Timezone | None:
    """Create a timezone object for the specified date if it does not already exist."""
    if (
        not isinstance(dtstart, datetime.datetime)
        or not dtstart.utcoffset()
        or not dtstart.tzinfo
    ):
        return None

    # Verify this timezone does not already exist. The number of timezones
    # in a calendar is typically very small so iterate over the whole thing
    # to avoid any synchronization/cache issues.
    key = str(dtstart.tzinfo)
    for timezone in timezones:
        if timezone.tz_id == key:
            return None

    try:
        return Timezone.from_tzif(key)
    except TimezoneInfoError as err:
        raise EventStoreError(
            f"No timezone information available for event: {key}"
        ) from err


def _match_item(item: _T, uid: str, recurrence_id: str | None) -> bool:
    """Return True if the item is an instance of a recurring event."""
    if item.uid != uid:
        return False
    if recurrence_id is None:
        # Match all items with the specified uids
        return True
    # Match a single item with the specified recurrence_id. If the item is an
    # edited instance match return it
    if item.recurrence_id == recurrence_id:
        _LOGGER.debug("Matched exact recurrence_id: %s", item)
        return True
    # Otherwise, determine if this instance is in the series
    _LOGGER.debug(
        "Expanding item %s %s to look for match of %s", uid, item.dtstart, recurrence_id
    )
    dtstart = RecurrenceId.to_value(recurrence_id)
    for dt in item.as_rrule() or ():
        if dt == dtstart:
            _LOGGER.debug("Found expanded recurrence_id: %s", dt)
            return True
    return False


def _match_items(
    items: list[_T], uid: str, recurrence_id: str | None
) -> Generator[tuple[int, _T], None, None]:
    """Return items from the list that match the uid and recurrence_id."""
    for index, item in enumerate(items):
        if _match_item(item, uid, recurrence_id):
            yield index, item


def _prepare_update(
    store_item: Event | Todo,
    item: Event | Todo,
    recurrence_id: str | None = None,
    recurrence_range: Range = Range.NONE,
) -> dict[str, Any]:
    """Prepare an update to an existing event."""
    partial_update = item.dict(
        exclude_unset=True,
        exclude={"dtstamp", "uid", "sequence", "created", "last_modified"},
    )
    _LOGGER.debug("Preparing update update=%s", item)
    update = {
        "created": store_item.dtstamp,
        "sequence": (store_item.sequence + 1) if store_item.sequence else 1,
        "last_modified": item.dtstamp,
        **partial_update,
        "dtstamp": item.dtstamp,
    }
    if rrule := update.get("rrule"):
        update["rrule"] = Recur.parse_obj(rrule)
    if recurrence_id and store_item.rrule:
        # Forking a new event off the old event preserves the original uid and
        # recurrence_id.
        update.update(
            {
                "uid": store_item.uid,
                "recurrence_id": recurrence_id,
            }
        )
        if recurrence_range == Range.NONE:
            # The new event copied from the original is a single instance,
            # which is not recurring.
            update["rrule"] = None
        else:
            # Overwriting with a new recurring event
            update["created"] = item.dtstamp

            # Adjust start and end time of the event
            dtstart: datetime.datetime | datetime.date = RecurrenceId.to_value(
                recurrence_id
            )
            if item.dtstart:
                dtstart = item.dtstart
            update["dtstart"] = dtstart
            # Event either has a duration (which should already be set) or has
            # an explicit end which needs to be realigned to new start time.
            if isinstance(store_item, Event) and store_item.dtend:
                update["dtend"] = dtstart + store_item.computed_duration
    return update


class GenericStore(Generic[_T]):
    """A a store manages the lifecycle of items on a Calendar."""

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
        new_item = cast(_T, item.copy_and_validate(update=update))

        # The store can only manage cascading deletes for some relationship types
        for relation in new_item.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise self._exc(f"Unsupported relationship type {relation.reltype}")

        _LOGGER.debug("Adding item: %s", new_item)
        self._ensure_timezone(item.dtstart)
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
        be specified. To delete an individual instances of the item the
        `recurrence_id` must be specified.

        When deleting individual instances, the range property may specify
        if deletion of just a specific instance, or a range of instances.
        """
        items_to_delete: list[_T] = [
            item for _, item in _match_items(self._items, uid, recurrence_id)
        ]
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
    ) -> None:
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and RecurrenceId.to_value(recurrence_id) == store_item.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new event
            recurrence_id = None

        children = []
        for event in self._items:
            for relation in event.related_to or ():
                if (
                    relation.reltype == RelationshipType.PARENT
                    and relation.uid == store_item.uid
                ):
                    children.append(event)
        for child in children:
            self._items.remove(child)

        # Deleting all instances in the series
        if not recurrence_id or not store_item.rrule:
            self._items.remove(store_item)
            return

        exdate = RecurrenceId.to_value(recurrence_id)
        if recurrence_range == Range.NONE:
            # A single recurrence instance is removed. Add an exclusion to
            # to the event.
            store_item.exdate.append(exdate)
            return

        # Assumes any recurrence deletion is valid, and that overwriting
        # the "until" value will not produce more instances. UNTIL is
        # inclusive so it can't include the specified exdate. FREQ=DAILY
        # is the lowest frequency supported so subtracting one day is
        # safe and works for both dates and datetimes.
        store_item.rrule.count = None
        store_item.rrule.until = exdate - datetime.timedelta(days=1)
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
            (index, item)
            for index, item in _match_items(self._items, uid, recurrence_id)
        ]
        if not items_to_edit:
            raise self._exc(
                f"No existing item with uid/recurrence_id: {uid}/{recurrence_id}"
            )

        for store_index, store_item in items_to_edit:
            self._apply_edit(
                store_index, store_item, item, recurrence_id, recurrence_range
            )

    def _apply_edit(
        self,
        store_index: int,
        store_item: _T,
        item: _T,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and RecurrenceId.to_value(recurrence_id) == store_item.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new item
            recurrence_id = None

        update = _prepare_update(store_item, item, recurrence_id, recurrence_range)
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
            dtstart: datetime.date | datetime.datetime = update["dtstart"]
            ruleset = RulesetIterable(
                store_item.dtstart,
                [new_item.rrule.as_rrule(store_item.dtstart)],
                [],
                [],
            )
            for dtvalue in ruleset:
                if dtvalue >= dtstart:
                    break
                new_item.rrule.count = new_item.rrule.count - 1

        # The store can only manage cascading deletes for some relationship types
        for relation in new_item.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise self._exc(f"Unsupported relationship type {relation.reltype}")

        self._ensure_timezone(new_item.dtstart)

        # Editing a single instance of a recurring item is like deleting that instance
        # then adding a new instance on the specified date. If recurrence id is not
        # specified then the entire item is replaced.
        self.delete(
            store_item.uid,
            recurrence_id=recurrence_id,
            recurrence_range=recurrence_range,
        )
        self._items.insert(store_index, new_item)

    def _ensure_timezone(
        self, dtstart: datetime.datetime | datetime.date | None
    ) -> None:
        if (new_timezone := _ensure_timezone(dtstart, self._timezones)) is not None:
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
