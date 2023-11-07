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
from collections.abc import Callable
from typing import Any

from .calendar import Calendar
from .event import Event
from .exceptions import StoreError, TodoStoreError, EventStoreError
from .todo import Todo
from .iter import RulesetIterable
from .timezone import Timezone
from .types import Range, Recur, RecurrenceId, RelationshipType
from .tzif.timezoneinfo import TimezoneInfoError
from .util import dtstamp_factory

_LOGGER = logging.getLogger(__name__)


__all__ = [
    "EventStore",
    "EventStoreError",
    "TodoStore",
    "TodoStoreError",
    "StoreError",
]


class EventStore:
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
    """

    def __init__(
        self,
        calendar: Calendar,
        dtstamp_fn: Callable[[], datetime.datetime] = lambda: dtstamp_factory(),
    ):
        """Initialize the EventStore."""
        self._calendar = calendar
        self._dtstamp_fn = dtstamp_fn

    def _lookup_event(self, uid: str) -> Event | None:
        """Find the specified event by id."""
        for event in self._calendar.events:
            if event.uid == uid:
                return event
        return None

    def add(self, event: Event) -> Event:
        """Add the specified event to the calendar.

        This will handle assigning modification dates, sequence numbers, etc
        if those fields are unset.

        The store will ensure the `ical.calendar.Calendar` has the necessary
        `ical.timezone.Timezone` needed to fully specify the event time information
        when encoded.
        """
        update: dict[str, Any] = {}
        if not event.created:
            update["created"] = event.dtstamp
        if event.sequence is None:
            update["sequence"] = 0
        new_event = event.copy(update=update)

        # The store can only manage cascading deletes for some relationship types
        for relation in new_event.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise EventStoreError(f"Unsupported relationship type {relation.reltype}")
            
        _LOGGER.debug("Adding event: %s", new_event)
        self._ensure_timezone(event)
        self._calendar.events.append(new_event)
        return new_event

    def delete(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        """Delete the event from the calendar.

        This method is used to delete an existing event. For a recurring event
        either the whole event or instances of an event may be deleted. To
        delete the complete range of a recurring event, the `uid` property
        for the event must be specified and the `recurrence_id` should not
        be specified. To delete an individual instances of the event the
        `recurrence_id` must be specified.

        When deleting individual instances, the range property may specify
        if deletion of just a specific instance, or a range of instances.
        """
        if not (store_event := self._lookup_event(uid)):
            raise EventStoreError(f"No existing event with uid: {uid}")

        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and RecurrenceId.to_value(recurrence_id) == store_event.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new event
            recurrence_id = None

        children = []
        for event in self._calendar.events:
            for relation in event.related_to or ():
                if relation.reltype == RelationshipType.PARENT and relation.uid == uid:
                    children.append(event)
        for child in children:
            self._calendar.events.remove(child)

        # Deleting all instances in the series
        if not recurrence_id:
            self._calendar.events.remove(store_event)
            return

        # Deleting one or more instances in the recurrence
        if not store_event.rrule:
            raise EventStoreError("Specified recurrence_id but event is not recurring")

        exdate = RecurrenceId.to_value(recurrence_id)
        if recurrence_range == Range.NONE:
            # A single recurrence instance is removed. Add an exclusion to
            # to the event.
            store_event.exdate.append(exdate)
            return

        # Assumes any recurrence deletion is valid, and that overwriting
        # the "until" value will not produce more instances. UNTIL is
        # inclusive so it can't include the specified exdate. FREQ=DAILY
        # is the lowest frequency supported so subtracting one day is
        # safe and works for both dates and datetimes.
        store_event.rrule.count = None
        store_event.rrule.until = exdate - datetime.timedelta(days=1)
        now = self._dtstamp_fn()
        store_event.dtstamp = now
        store_event.last_modified = now

    def edit(
        self,
        uid: str,
        event: Event,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        """Update the event with the specified uid.

        The specified event should be created with minimal fields, just
        including the fields that should be updated. The default fields such
        as `uid` and `dtstamp` may be used to set the uid for a new created event
        when updating a recurring event, or for any modification times.

        Example usage:
        ```python
        store.edit("event-uid-1", Event(summary="New Summary"))
        ```

        For a recurring event, either the whole event or individual instances
        of the event may be edited. To edit the complete range of a recurring
        event the `uid` property must be specified and the `recurrence_id` should
        not be specified. To edit an individual instances of the event the
        `recurrence_id` must be specified. The `recurrence_range` determines if
        just that individual instance is updated or all events following as well.

        The store will ensure the `ical.calendar.Calendar` has the necessary
        `ical.timezone.Timezone` needed to fully specify the event time information
        when encoded.
        """
        if not (store_event := self._lookup_event(uid)):
            raise EventStoreError(f"No existing event with uid: {uid}")

        if (
            recurrence_id
            and recurrence_range == Range.THIS_AND_FUTURE
            and RecurrenceId.to_value(recurrence_id) == store_event.dtstart
        ):
            # Editing the first instance and all forward is the same as editing the
            # entire series so don't bother forking a new event
            recurrence_id = None

        update = self._prepare_update(
            store_event, event, recurrence_id, recurrence_range
        )
        if recurrence_range == Range.NONE:
            # Changing the recurrence rule of a single event in the middle of the series
            # is not allowed. It is allowed to convert a single instance event to recurring.
            if event.rrule and store_event.rrule:
                if event.rrule.as_rrule_str() != store_event.rrule.as_rrule_str():
                    raise EventStoreError(
                        f"Can't update single instance with rrule (rrule={event.rrule})"
                    )
                event.rrule = None

        # Make a deep copy since deletion may update this objects recurrence rules
        new_event = store_event.copy(update=update, deep=True)
        if recurrence_id and new_event.rrule and new_event.rrule.count:
            # The recurring event count needs to skip any events that
            # come before the start of the new event. Use a RulesetIterable
            # to handle workarounds for dateutil.rrule limitations.
            dtstart: datetime.date | datetime.datetime = update["dtstart"]
            ruleset = RulesetIterable(
                store_event.dtstart,
                [new_event.rrule.as_rrule(store_event.dtstart)],
                [],
                [],
            )
            for dtvalue in ruleset:
                if dtvalue >= dtstart:
                    break
                new_event.rrule.count = new_event.rrule.count - 1

        # The store can only manage cascading deletes for some relationship types
        for relation in new_event.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise EventStoreError(f"Unsupported relationship type {relation.reltype}")

        self._ensure_timezone(event)

        # Editing a single instance of a recurring event is like deleting that instance
        # then adding a new instance on the specified date. If recurrence id is not
        # specified then the entire event is replaced.
        self.delete(uid, recurrence_id=recurrence_id, recurrence_range=recurrence_range)
        if recurrence_id:
            self.add(new_event)
        else:
            self._calendar.events.append(new_event)

    def _prepare_update(
        self,
        store_event: Event,
        event: Event,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> dict[str, Any]:
        """Prepare an update to an existing event."""
        partial_update = event.dict(exclude_unset=True)
        _LOGGER.debug("EV update=%s", event)
        update = {
            "created": store_event.dtstamp,
            "sequence": (store_event.sequence + 1) if store_event.sequence else 1,
            "last_modified": event.dtstamp,
            **partial_update,
            "dtstamp": event.dtstamp,
        }
        if "rrule" in update:
            update["rrule"] = Recur.parse_obj(update["rrule"])
        if recurrence_id:
            if not store_event.rrule:
                raise EventStoreError(
                    "Specified recurrence_id but event is not recurring"
                )
            # Forking a new event off the old event
            update["uid"] = event.uid
            if recurrence_range == Range.NONE:
                # The new event copied from the original is a single instance,
                # not recurrin
                update["rrule"] = None
            else:
                # Overwriting with a new recurring event
                update.update(
                    {
                        "sequence": 0,
                        "created": event.dtstamp,
                    }
                )

                # Adjust start and end time of the event
                dtstart: datetime.datetime | datetime.date = RecurrenceId.to_value(
                    recurrence_id
                )
                if event.dtstart:
                    dtstart = event.dtstart
                update["dtstart"] = dtstart
                # Event either has a duration (which should already be set) or has
                # an explicit end which needs to be realigned to new start time.
                if store_event.dtend:
                    update["dtend"] = dtstart + store_event.computed_duration
        return update

    def _ensure_timezone(self, event: Event) -> None:
        """Create a timezone object for the specified date if it does not already exist."""
        if (
            not isinstance(event.dtstart, datetime.datetime)
            or not event.dtstart.utcoffset()
            or not event.dtstart.tzinfo
        ):
            return

        # Verify this timezone does not already exist. The number of timezones
        # in a calendar is typically very small so iterate over the whole thing
        # to avoid any synchronization/cache issues.
        key = str(event.dtstart.tzinfo)
        for timezone in self._calendar.timezones:
            if timezone.tz_id == key:
                return

        new_timezone: Timezone
        try:
            new_timezone = Timezone.from_tzif(key)
        except TimezoneInfoError as err:
            raise EventStoreError(
                "No timezone information available for event: {key}"
            ) from err
        self._calendar.timezones.append(new_timezone)


class TodoStore:
    """A To-do store manages the lifecycle of to-dos on a Calendar."""

    def __init__(
        self,
        calendar: Calendar,
        dtstamp_fn: Callable[[], datetime.datetime] = lambda: dtstamp_factory(),
    ):
        """Initialize the TodoStore."""
        self._calendar = calendar
        self._dtstamp_fn = dtstamp_fn

    def _lookup_todo(self, uid: str) -> (int | None, Todo | None):
        """Find the specified todo by id returning the index."""
        for i, todo in enumerate(self._calendar.todos):
            if todo.uid == uid:
                return i, todo
        return None, None

    def add(self, todo: Todo) -> Todo:
        """Add the specified todo to the calendar."""
        update: dict[str, Any] = {}
        if not todo.created:
            update["created"] = todo.dtstamp
        if todo.sequence is None:
            update["sequence"] = 0
        new_todo = todo.copy(update=update)

        # The store can only manage cascading deletes for some relationship types
        for relation in new_todo.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise TodoStoreError(f"Unsupported relationship type {relation.reltype}")
            
        _LOGGER.debug("Adding todo: %s", new_todo)
        self._ensure_timezone(todo)
        self._calendar.todos.append(new_todo)
        return new_todo

    def delete(
        self,
        uid: str,
    ) -> None:
        """Delete the todo from the calendar."""
        store_index, store_todo = self._lookup_todo(uid)
        if not store_todo:
            raise TodoStoreError(f"No existing todo with uid: {uid}")
        removals = [store_todo]

        for todo in self._calendar.todos:
            for relation in todo.related_to or ():
                if relation.reltype == RelationshipType.PARENT and relation.uid == uid:
                    removals.append(todo)

        for todo in removals:
            self._calendar.todos.remove(todo)

    def edit(
        self,
        uid: str,
        todo: Todo,
    ) -> None:
        """Update the todo with the specified uid."""
        store_index, store_todo = self._lookup_todo(uid)
        if not store_todo:
            raise TodoStoreError(f"No existing todo with uid: {uid}")

        partial_update = todo.dict(exclude_unset=True)
        update = {
            "created": store_todo.dtstamp,
            "sequence": (store_todo.sequence + 1) if store_todo.sequence else 1,
            "last_modified": todo.dtstamp,
            **partial_update,
            "dtstamp": todo.dtstamp,
        }
        # Make a deep copy since deletion may update this objects recurrence rules
        new_todo = store_todo.copy(update=update, deep=True)

        # The store can only manage cascading deletes for some relationship types
        for relation in new_todo.related_to or ():
            if relation.reltype != RelationshipType.PARENT:
                raise TodoStoreError(f"Unsupported relationship type {relation.reltype}")

        self._ensure_timezone(todo)

        self._calendar.todos.pop(store_index)
        self._calendar.todos.insert(store_index, new_todo)

    def _ensure_timezone(self, todo: Todo) -> None:
        """Create a timezone object for the specified date if it does not already exist."""
        if (
            not isinstance(todo.due, datetime.datetime)
            or not todo.due.utcoffset()
            or not todo.due.tzinfo
        ):
            return

        # Verify this timezone does not already exist. The number of timezones
        # in a calendar is typically very small so iterate over the whole thing
        # to avoid any synchronization/cache issues.
        key = str(todo.due.tzinfo)
        for timezone in self._calendar.timezones:
            if timezone.tz_id == key:
                return

        new_timezone: Timezone
        try:
            new_timezone = Timezone.from_tzif(key)
        except TimezoneInfoError as err:
            raise TodoStoreError(
                "No timezone information available for todo: {key}"
            ) from err
        self._calendar.timezones.append(new_timezone)
