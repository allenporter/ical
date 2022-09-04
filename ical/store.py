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
from .types import Range, RecurrenceId
from .util import dtstamp_factory

_LOGGER = logging.getLogger(__name__)


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
    # Cancel a single instance of the recurring event
    store.cancel(uid=event.uid, recurrence_id="20220710")
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

    def add(self, event: Event) -> None:
        """Add the specified event to the calendar.

        This will handle assigning modification dates, sequence numbers, etc
        if those fields are unset.
        """
        update: dict[str, Any] = {}
        if not event.created:
            update["created"] = event.dtstamp
        if event.sequence is None:
            update["sequence"] = 0
        new_event = event.copy(update=update)
        _LOGGER.debug("Adding event: %s", new_event)
        self._calendar.events.append(new_event)

    def cancel(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: Range = Range.NONE,
    ) -> None:
        """Delete the event from the calendar.

        This method is used to cancel an existing event. For a recurring event
        either the whole event or instances of an event may be cancelled. To
        cancel the complete range of a recurring event, the `uid` property
        for the event must be specified and the `recurrence_id` should not
        be specified. To cancel an individual instances of the event the
        `recurrence_id` must be specified.

        When deleting individual instances, the range property may specify
        if cancellation of just a specific instance, or a range of instances.
        """
        if not (store_event := self._lookup_event(uid)):
            raise ValueError(f"No existing event with uid: {uid}")

        # Deleting all instances in the series
        if not recurrence_id:
            self._calendar.events.remove(store_event)
            return

        # Deleting one or more instances in the recurrence
        if not store_event.rrule:
            raise ValueError("Specified recurrence_id but event is not recurring")

        exdate = RecurrenceId.to_value(recurrence_id)
        if recurrence_range == Range.NONE:
            # A single recurrence instance is removed. Add an exclusion to
            # to the event.
            store_event.exdate.append(exdate)
            return

        # Assumes any recurrence cancellation is valid, and that overwriting
        # the "until" value will not produce more instances.
        store_event.rrule.count = None
        store_event.rrule.until = exdate - datetime.timedelta(seconds=1)
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

        For a recurring event, either the whol eevent or individual instances
        of the event may be edited. To edit the complete range of a recurring
        event the `uid` property must be specified and the `recurrence_id` should
        not be specified. To edit an individual instances of the event the
        `recurrence_id` must be specified. The `recurrence_range` determines if
        just that individual instance is updated or all events following as well.
        """
        if not (store_event := self._lookup_event(uid)):
            raise ValueError(f"No existing event with uid: {uid}")
        partial_update = event.dict(exclude_unset=True)
        _LOGGER.debug("EV pdate=%s", event)
        update = {
            "created": store_event.dtstamp,
            "sequence": (store_event.sequence + 1) if store_event.sequence else 1,
            "last_modified": event.dtstamp,
            **partial_update,
            "dtstamp": event.dtstamp,
        }
        if recurrence_id:
            if not store_event.rrule:
                raise ValueError("Specified recurrence_id but event is not recurring")
            # Forking a new event off the old event
            update["uid"] = event.uid
            if recurrence_range == Range.NONE:
                # The new event copied from the original is a single instance,
                # not recurrin
                update["rrule"] = None
                update["rdate"] = []
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

        # Make a deep copy since cancellation may update this objects recurrence rules
        new_event = store_event.copy(update=update, deep=True)
        if recurrence_id and new_event.rrule and new_event.rrule.count:
            # The recurring event count needs to skip any events that
            # come before the start of the new event.
            for dtvalue in iter(new_event.rrule.as_rrule(store_event.dtstart)):
                if dtvalue >= dtstart:
                    break
                new_event.rrule.count = new_event.rrule.count - 1

        # Editing a single instance of a recurring event is like canceling that instance
        # then adding a new instance on the specified date. If recurrence id is not
        # specified then the entire event is replaced.
        self.cancel(uid, recurrence_id=recurrence_id, recurrence_range=recurrence_range)
        if recurrence_id:
            self.add(new_event)
        else:
            self._calendar.events.append(new_event)
