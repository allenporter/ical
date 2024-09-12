"""A grouping of component properties that describe a calendar event.

An event can be an activity (e.g. a meeting from 8am to 9am tomorrow)
grouping of properties such as a summary or a description. An event will
take up time on a calendar as an opaque time interval, but can alternatively
have transparency set to transparent to prevent blocking of time as busy.

An event start and end time may either be a date and time or just a day
alone. Events may also span more than one day. Alternatively, an event
can have a start and a duration.
"""

# pylint: disable=unnecessary-lambda

from __future__ import annotations

import datetime
import enum
import logging
from collections.abc import Iterable
from typing import Any, Optional, Union

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator  # type: ignore[no-redef, assignment]

from .alarm import Alarm
from .component import ComponentModel, validate_until_dtstart, validate_recurrence_dates
from .iter import RulesetIterable, as_rrule
from .exceptions import CalendarParseError
from .parsing.property import ParsedProperty
from .timespan import Timespan
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

_LOGGER = logging.getLogger(__name__)


class EventStatus(str, enum.Enum):
    """Status or confirmation of the event set by the organizer."""

    CONFIRMED = "CONFIRMED"
    """Indicates event is definite."""

    TENTATIVE = "TENTATIVE"
    """Indicates event is tentative."""

    CANCELLED = "CANCELLED"
    """Indicates event was cancelled."""


class Event(ComponentModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.

    The dtstamp and uid functions have factory methods invoked with a lambda to facilitate
    mocking in unit tests.


    Example:
    ```python
    import datetime
    from ical.event import Event

    event = Event(
        dtstart=datetime.datetime(2022, 8, 31, 7, 00, 00),
        dtend=datetime.datetime(2022, 8, 31, 7, 30, 00),
        summary="Morning exercise",
    )
    print("The event duration is: ", event.computed_duration)
    ```

    An Event is a pydantic model, so all properties of a pydantic model apply here to such as
    the constructor arguments, properties to return the model as a dictionary or json, as well
    as other parsing methods.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=lambda: dtstamp_factory()
    )
    """Specifies the date and time the event was created."""

    uid: str = Field(default_factory=lambda: uid_factory())
    """A globally unique identifier for the event."""

    # Has an alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date] = Field(
        default=None,
    )
    """The start time or start day of the event."""

    # Has an alias of 'end'
    dtend: Optional[Union[datetime.datetime, datetime.date]] = None
    """The end time or end day of the event.

    This may be specified as an explicit date. Alternatively, a duration
    can be used instead.
    """

    duration: Optional[datetime.timedelta] = None
    """The duration of the event as an alternative to an explicit end date/time."""

    summary: str = ""
    """Defines a short summary or subject for the event."""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    """Specifies participants in a group-scheduled calendar."""

    categories: list[str] = Field(default_factory=list)
    """Defines the categories for an event.

    Specifies a category or subtype. Can be useful for searching for a particular
    type of event.
    """

    classification: Optional[Classification] = Field(alias="class", default=None)
    """An access classification for a calendar event.

    This provides a method of capturing the scope of access of a calendar, in
    conjunction with an access control system.
    """

    comment: list[str] = Field(default_factory=list)
    """Specifies a comment to the calendar user."""

    contacts: list[str] = Field(alias="contact", default_factory=list)
    """Contact information associated with the event."""

    created: Optional[datetime.datetime] = None
    """The date and time the event information was created."""

    description: Optional[str] = None
    """A more complete description of the event than provided by the summary."""

    geo: Optional[Geo] = None
    """Specifies a latitude and longitude global position for the event activity."""

    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )

    location: Optional[str] = None
    """Defines the intended venue for the activity defined by this event."""

    organizer: Optional[CalAddress] = None
    """The organizer of a group-scheduled calendar entity."""

    priority: Optional[Priority] = None
    """Defines the relative priorirty of the calendar event."""

    recurrence_id: Optional[RecurrenceId] = Field(alias="recurrence-id", default=None)
    """Defines a specific instance of a recurring event.

    The full range of calendar events specified by a recurrence set is referenced
    by referring to just the uid. The `recurrence_id` allows reference of an individual
    instance within the recurrence set.
    """

    related_to: list[RelatedTo] = Field(alias="related-to", default_factory=list)
    """Used to represent a relationship or reference between events."""

    related: list[str] = Field(default_factory=list)
    """Unused and will be deleted in a future release"""

    resources: list[str] = Field(default_factory=list)
    """Defines the equipment or resources anticipated for the calendar event."""

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

    request_status: Optional[RequestStatus] = Field(
        alias="request-status", default_value=None
    )

    sequence: Optional[int] = None
    """The revision sequence number in the calendar component.

    When an event is created, its sequence number is 0. It is monotonically incremented
    by the organizers calendar user agent every time a significant revision is made to
    the calendar event.
    """

    status: Optional[EventStatus] = None
    """Defines the overall status or confirmation of the event.

    In a group-scheduled calendar, used by the organizer to provide a confirmation
    of the event to attendees.
    """

    transparency: Optional[str] = Field(alias="transp", default=None)
    """Defines whether or not an event is transparenty to busy time searches."""

    url: Optional[Uri] = None
    """Defines a url associated with the event.

    May convey a location where a more dynamic rendition of the calendar event
    information associated with the event can be found.
    """

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    alarm: list[Alarm] = Field(alias="valarm", default_factory=list)
    """A grouping of reminder alarms for the event."""

    def __init__(self, **data: Any) -> None:
        """Initialize a Calendar Event.

        This method accepts keyword args with field names on the Calendar such as `summary`,
        `start`, `end`, `description`, etc.
        """
        if "start" in data:
            data["dtstart"] = data.pop("start")
        if "end" in data:
            data["dtend"] = data.pop("end")
        super().__init__(**data)

    @property
    def start(self) -> datetime.datetime | datetime.date:
        """Return the start time for the event."""
        return self.dtstart

    @property
    def end(self) -> datetime.datetime | datetime.date:
        """Return the end time for the event."""
        if self.duration:
            return self.dtstart + self.duration
        if self.dtend:
            return self.dtend

        if isinstance(self.dtstart, datetime.datetime):
            return self.dtstart
        return self.dtstart + datetime.timedelta(days=1)

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime in UTC"""
        return normalize_datetime(self.start).astimezone(datetime.timezone.utc)

    @property
    def end_datetime(self) -> datetime.datetime:
        """Return the events end as a datetime in UTC."""
        return normalize_datetime(self.end).astimezone(datetime.timezone.utc)

    @property
    def computed_duration(self) -> datetime.timedelta:
        """Return the event duration."""
        if self.duration is not None:
            return self.duration
        return self.end - self.start

    @property
    def timespan(self) -> Timespan:
        """Return a timespan representing the event start and end."""
        return Timespan.of(self.start, self.end)

    def timespan_of(self, tzinfo: datetime.tzinfo) -> Timespan:
        """Return a timespan representing the event start and end."""
        return Timespan.of(
            normalize_datetime(self.start, tzinfo), normalize_datetime(self.end, tzinfo)
        )

    def starts_within(self, other: "Event") -> bool:
        """Return True if this event starts while the other event is active."""
        return self.timespan.starts_within(other.timespan)

    def ends_within(self, other: "Event") -> bool:
        """Return True if this event ends while the other event is active."""
        return self.timespan.ends_within(other.timespan)

    def intersects(self, other: "Event") -> bool:
        """Return True if this event overlaps with the other event."""
        return self.timespan.intersects(other.timespan)

    def includes(self, other: "Event") -> bool:
        """Return True if the other event starts and ends within this event."""
        return self.timespan.includes(other.timespan)

    def is_included_in(self, other: "Event") -> bool:
        """Return True if this event starts and ends within the other event."""
        return self.timespan.is_included_in(other.timespan)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.timespan < other.timespan

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.timespan > other.timespan

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.timespan <= other.timespan

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.timespan >= other.timespan

    @property
    def recurring(self) -> bool:
        """Return true if this event is recurring.

        A recurring event is typically evaluated specially on the timeline. The
        data model has a single event, but the timeline evaluates the recurrence
        to expand and copy the the event to multiple places on the timeline
        using `as_rrule`.
        """
        if self.rrule or self.rdate:
            return True
        return False

    def as_rrule(self) -> Iterable[datetime.datetime | datetime.date] | None:
        """Return an iterable containing the occurrences of a recurring event.

        A recurring event is typically evaluated specially on the timeline. The
        data model has a single event, but the timeline evaluates the recurrence
        to expand and copy the the event to multiple places on the timeline.

        This is only valid for events where `recurring` is True.
        """
        return as_rrule(self.rrule, self.rdate, self.exdate, self.dtstart)

    @root_validator(pre=True, allow_reuse=True)
    def _inspect_date_types(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Debug the date and date/time values of the event."""
        dtstart = values.get("dtstart")
        dtend = values.get("dtend")
        if not dtstart or not dtend:
            return values
        _LOGGER.debug("Found initial values dtstart=%s, dtend=%s", dtstart, dtend)
        return values

    @root_validator(allow_reuse=True)
    def _validate_date_types(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that start and end values are the same date or datetime type."""
        dtstart = values.get("dtstart")
        dtend = values.get("dtend")

        if not dtstart or not dtend:
            return values
        if isinstance(dtstart, datetime.datetime):
            if not isinstance(dtend, datetime.datetime):
                _LOGGER.debug("Unexpected data types for values: %s", values)
                raise ValueError(
                    f"Unexpected dtstart value '{dtstart}' was datetime but "
                    f"dtend value '{dtend}' was not datetime"
                )
        elif isinstance(dtstart, datetime.date):
            if isinstance(dtend, datetime.datetime):
                raise ValueError(
                    f"Unexpected dtstart value '{dtstart}' was date but "
                    f"dtend value '{dtend}' was datetime"
                )
        return values

    @root_validator(allow_reuse=True)
    def _validate_datetime_timezone(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that start and end values have the same timezone information."""
        if (
            not (dtstart := values.get("dtstart"))
            or not (dtend := values.get("dtend"))
            or not isinstance(dtstart, datetime.datetime)
            or not isinstance(dtend, datetime.datetime)
        ):
            return values
        if dtstart.tzinfo is None and dtend.tzinfo is not None:
            raise ValueError(
                f"Expected end datetime value in localtime but was {dtend}"
            )
        if dtstart.tzinfo is not None and dtend.tzinfo is None:
            raise ValueError(f"Expected end datetime with timezone but was {dtend}")
        return values

    @root_validator(allow_reuse=True)
    def _validate_one_end_or_duration(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that only one of duration or end date may be set."""
        if values.get("dtend") and values.get("duration"):
            raise ValueError("Only one of dtend or duration may be set." "")
        return values

    @root_validator(allow_reuse=True)
    def _validate_duration_unit(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate the duration is the appropriate units."""
        if not (duration := values.get("duration")):
            return values
        dtstart = values["dtstart"]
        if type(dtstart) is datetime.date:
            if duration.seconds != 0:
                raise ValueError("Event with start date expects duration in days only")
        if duration < datetime.timedelta(seconds=0):
            raise ValueError(f"Expected duration to be positive but was {duration}")
        return values

    _validate_until_dtstart = root_validator(allow_reuse=True)(validate_until_dtstart)
    _validate_recurrence_dates = root_validator(allow_reuse=True)(
        validate_recurrence_dates
    )
