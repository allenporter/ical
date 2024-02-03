"""A grouping of component properties that describe a to-do."""

from __future__ import annotations

from collections.abc import Iterable
import datetime
import enum
from typing import Any, Optional, Union

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator  # type: ignore[no-redef, assignment]

from .alarm import Alarm
from .component import ComponentModel, validate_until_dtstart, validate_recurrence_dates
from .exceptions import CalendarParseError
from .iter import RulesetIterable
from .parsing.property import ParsedProperty
from .types import (
    CalAddress,
    Classification,
    Geo,
    Priority,
    Recur,
    RecurrenceId,
    RequestStatus,
    Uri,
    RelatedTo,
)
from .util import dtstamp_factory, normalize_datetime, uid_factory


class TodoStatus(str, enum.Enum):
    """Status or confirmation of the to-do."""

    NEEDS_ACTION = "NEEDS-ACTION"
    COMPLETED = "COMPLETED"
    IN_PROCESS = "IN-PROCESS"
    CANCELLED = "CANCELLED"


class Todo(ComponentModel):
    """A calendar todo component."""

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=dtstamp_factory
    )
    """Specifies the date and time the item was created."""

    uid: str = Field(default_factory=lambda: uid_factory())
    """A globally unique identifier for the item."""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    """Specifies participants in a group-scheduled calendar."""

    categories: list[str] = Field(default_factory=list)
    """Defines the categories for an item.

    Specifies a category or subtype. Can be useful for searching for a particular
    type of item.
    """

    classification: Optional[Classification] = Field(alias="class", default=None)
    """An access classification for a calendar to-do item.

    This provides a method of capturing the scope of access of a calendar, in
    conjunction with an access control system.
    """

    comment: list[str] = Field(default_factory=list)
    """Specifies a comment to the calendar user."""

    completed: Optional[datetime.datetime] = None

    contacts: list[str] = Field(alias="contact", default_factory=list)
    """Contact information associated with the item."""

    created: Optional[datetime.datetime] = None

    description: Optional[str] = None
    """A more complete description of the item than provided by the summary."""

    # Has alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date, None] = None
    """The start time or start day of the item."""

    due: Union[datetime.datetime, datetime.date, None] = None

    duration: Optional[datetime.timedelta] = None
    """The duration of the item as an alternative to an explicit end date/time."""

    geo: Optional[Geo] = None
    """Specifies a latitude and longitude global position for the activity."""

    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )

    location: str = ""
    """Defines the intended venue for the activity defined by this item."""

    organizer: Optional[CalAddress] = None
    """The organizer of a group-scheduled calendar entity."""

    percent: Optional[int] = None

    priority: Optional[Priority] = None
    """Defines the relative priorirty of the todo item."""

    recurrence_id: Optional[RecurrenceId] = Field(alias="recurrence-id")
    """Defines a specific instance of a recurring item.

    The full range of items specified by a recurrence set is referenced
    by referring to just the uid. The `recurrence_id` allows reference of an individual
    instance within the recurrence set.
    """

    related_to: list[RelatedTo] = Field(alias="related-to", default_factory=list)
    """Used to represent a relationship or reference between events."""

    request_status: Optional[RequestStatus] = Field(
        alias="request-status",
        default_value=None,
    )

    rrule: Optional[Recur] = None
    """A recurrence rule specification.

    Defines a rule for specifying a repeated event. The recurrence set is the complete
    set of recurrence instances for a calendar component (based on rrule, rdate, exdate).
    The recurrence set is generated by gathering the rrule and rdate properties then
    excluding any times specified by exdate. The recurrence is generated with the dtstart
    property defining the first instance of the recurrence set.

    Typically a dtstart should be specified with a date local time and timezone to make
    sure all instances have the same start time regardless of time zone changing.
    """

    rdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    """Defines the list of date/time values for recurring events.

    Can appear along with the rrule property to define a set of repeating occurrences of the
    event. The recurrence set is the complete set of recurrence instances for a calendar component
    (based on rrule, rdate, exdate). The recurrence set is generated by gathering the rrule
    and rdate properties then excluding any times specified by exdate.
    """

    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    """Defines the list of exceptions for recurring events.

    The exception dates are used in computing the recurrence set. The recurrence set is
    the complete set of recurrence instances for a calendar component (based on rrule, rdate,
    exdate). The recurrence set is generated by gathering the rrule and rdate properties
    then excluding any times specified by exdate.
    """

    sequence: Optional[int] = None
    """The revision sequence number in the calendar component.

    When an event is created, its sequence number is 0. It is monotonically incremented
    by the organizers calendar user agent every time a significant revision is made to
    the calendar event.
    """

    status: Optional[TodoStatus] = None
    """Defines the overall status or confirmation of the event.

    In a group-scheduled calendar, used by the organizer to provide a confirmation
    of the event to attendees.
    """

    summary: Optional[str] = None
    """Defines a short summary or subject for the event."""

    url: Optional[Uri] = None
    """Defines a url associated with the item.

    May convey a location where a more dynamic rendition of the item can be found.
    """

    alarms: list[Alarm] = Field(alias="valarm", default_factory=list)

    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        """Initialize Todo."""
        if "start" in data:
            data["dtstart"] = data.pop("start")
        super().__init__(**data)

    @property
    def start(self) -> datetime.datetime | datetime.date | None:
        """Return the start time for the todo."""
        return self.dtstart

    @property
    def start_datetime(self) -> datetime.datetime | None:
        """Return the todos start as a datetime."""
        if not self.dtstart:
            return None
        return normalize_datetime(self.dtstart).astimezone(tz=datetime.timezone.utc)

    @property
    def computed_duration(self) -> datetime.timedelta | None:
        """Return the event duration."""
        if self.due is None or self.dtstart is None:
            return None
        return self.due - self.dtstart

    @property
    def recurring(self) -> bool:
        """Return true if this Todo is recurring.

        A recurring event is typically evaluated specially on the list. The
        data model has a single todo, but the timeline evaluates the recurrence
        to expand and copy the the event to multiple places on the timeline
        using `as_rrule`.
        """
        if self.rrule or self.rdate:
            return True
        return False

    def as_rrule(self) -> Iterable[datetime.datetime | datetime.date] | None:
        """Return an iterable containing the occurrences of a recurring todo.

        A recurring todo is typically evaluated specially on the todo list. The
        data model has a single todo item, but the timeline evaluates the recurrence
        to expand and copy the the item to multiple places on the timeline.

        This is only valid for events where `recurring` is True.
        """
        if not self.rrule and not self.rdate:
            return None
        if not self.start:
            raise CalendarParseError("Event must have a start date to be recurring")
        if not self.due:
            raise CalendarParseError("Event must have a due date to be recurring")
        return RulesetIterable(
            self.start,
            [self.rrule.as_rrule(self.start)] if self.rrule else [],
            self.rdate,
            self.exdate,
        )

    @root_validator
    def validate_one_due_or_duration(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that only one of duration or end date may be set."""
        if values.get("due") and values.get("duration"):
            raise ValueError("Only one of dtend or duration may be set." "")
        return values

    @root_validator
    def validate_duration_requires_start(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that a duration requires the dtstart."""
        if values.get("duration") and not values.get("dtstart"):
            raise ValueError("Duration requires that dtstart is specified")
        return values

    _validate_until_dtstart = root_validator(allow_reuse=True)(validate_until_dtstart)
    _validate_recurrence_dates = root_validator(allow_reuse=True)(
        validate_recurrence_dates
    )
