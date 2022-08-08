"""Event implementation."""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any, Optional, Union

from pydantic import Field, root_validator, validator

from .alarm import Alarm
from .parsing.property import ParsedProperty
from .types import (
    CalAddress,
    ComponentModel,
    EventStatus,
    Geo,
    Priority,
    Recur,
    RequestStatus,
    Uri,
    parse_text,
)

_LOGGER = logging.getLogger(__name__)

MIDNIGHT = datetime.time()


def dtstamp_factory() -> datetime.datetime:
    """Factory method for new event timestamps to facilitate mocking."""
    return datetime.datetime.utcnow()


def uid_factory() -> uuid.UUID:
    """Factory method for new uids to facilitate mocking."""
    return uuid.uuid1()


def local_timezone() -> datetime.tzinfo:
    """Get the local timezone to use when converting date to datetime."""
    local_tz = datetime.datetime.now().astimezone().tzinfo
    if not local_tz:
        return datetime.timezone.utc
    return local_tz


def normalize_datetime(value: datetime.date | datetime.datetime) -> datetime.datetime:
    """Convert date or datetime to a value that can be used for comparison."""
    if not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, MIDNIGHT)
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_timezone())
    return value


class Event(ComponentModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=dtstamp_factory
    )
    uid: str = Field(default_factory=uid_factory)
    # Has an alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date] = Field(
        default=None,
    )
    # Has an alias of 'end'
    dtend: Optional[Union[datetime.datetime, datetime.date]] = None
    duration: Optional[datetime.timedelta] = None
    summary: str = ""

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    categories: list[str] = Field(default_factory=list)
    classification: Optional[str] = Field(alias="class", default=None)
    comment: list[str] = Field(default_factory=list)
    contacts: list[str] = Field(alias="contact", default_factory=list)
    created: Optional[datetime.datetime] = None
    description: str = ""
    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    geo: Optional[Geo] = None
    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    location: str = ""
    organization: str = ""
    organizer: Optional[CalAddress] = None
    priority: Optional[Priority] = None
    recurrence_id: Optional[Union[datetime.datetime, datetime.date]] = Field(
        alias="recurrence-id"
    )
    related: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    rrule: Optional[Recur] = None
    rdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    request_status: Optional[RequestStatus] = Field(
        alias="request-status", default_value=None
    )
    sequence: Optional[int] = None
    status: Optional[EventStatus] = None
    transparency: Optional[str] = Field(alias="transp", default=None)
    url: Optional[Uri] = None

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    alarm: list[Alarm] = Field(alias="valarm", default_factory=list)

    # Other properties needed:
    # -- multiple
    # - attach

    def __init__(self, **data: dict[str, Any]) -> None:
        """Initialize Event."""
        super().__init__(
            dtstart=data.pop("dtstart", None) or data.pop("start", None),
            dtend=data.pop("dtend", None) or data.pop("end", None),
            **data,
        )

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
        raise ValueError("Unexpected state with no duration or dtend")

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime."""
        return normalize_datetime(self.start).astimezone(tz=datetime.timezone.utc)

    @property
    def end_datetime(self) -> datetime.datetime:
        """Return the events end as a datetime."""
        return normalize_datetime(self.end).astimezone(tz=datetime.timezone.utc)

    @property
    def computed_duration(self) -> datetime.timedelta:
        """Return the event duration."""
        if self.end:
            return self.end - self.start
        if not self.duration:
            raise ValueError("Invalid state, expected end or duration")
        return self.duration

    def starts_within(self, other: "Event") -> bool:
        """Return True if this event starts while the other event is active."""
        return other.start_datetime <= self.start_datetime < other.end_datetime

    def ends_within(self, other: "Event") -> bool:
        """Return True if this event ends while the other event is active."""
        return other.start_datetime <= self.end_datetime < other.end_datetime

    def intersects(self, other: "Event") -> bool:
        """Return True if this event overlaps with the other event."""
        return (
            other.start_datetime <= self.start_datetime < other.end_datetime
            or other.start_datetime < self.end_datetime <= other.end_datetime
            or self.start_datetime <= other.start_datetime < self.end_datetime
            or self.start_datetime < other.end_datetime <= self.end_datetime
        )

    def includes(self, other: "Event") -> bool:
        """Return True if the other event starts and ends within this event."""
        return (
            self.start_datetime <= other.start_datetime < self.end_datetime
            and self.start_datetime <= other.end_datetime < self.end_datetime
        )

    def is_included_in(self, other: "Event") -> bool:
        """Return True if this event starts and ends within the other event."""
        return (
            other.start_datetime <= self.start_datetime
            and self.end_datetime < other.end_datetime
        )

    def _tuple(self) -> tuple[datetime.datetime, datetime.datetime]:
        return (self.start_datetime, self.end_datetime)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() < other._tuple()

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() > other._tuple()

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() <= other._tuple()

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() >= other._tuple()

    @validator("status", pre=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse an EventStatus from a ParsedPropertyValue."""
        value = parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected text value as a string: {value}")
        return value

    @validator("classification", pre=True)
    def parse_classification(cls, value: Any) -> str | None:
        """Parse a Classification from a ParsedPropertyValue."""
        value = parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected text value as a string: {value}")
        return value

    @root_validator
    def validate_date_types(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that start and end values are the same date or datetime type."""
        if (
            (dtstart := values.get("dtstart"))
            and (dtend := values.get("dtend"))
            and type(dtstart) != type(dtend)  # pylint: disable=unidiomatic-typecheck
        ):
            raise ValueError("Expected end value type to match start")
        return values

    @root_validator
    def validate_date_time_timezone(cls, values: dict[str, Any]) -> dict[str, Any]:
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

    @root_validator
    def validate_one_end_or_duration(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that only one of duration or end date may be set."""
        if values.get("dtend") and values.get("duration"):
            raise ValueError("Only one of dtend or duration may be set." "")
        return values

    @root_validator
    def validate_duration_unit(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate the duration is the appropriate units."""
        if not (duration := values.get("duration")):
            return values
        dtstart = values["dtstart"]
        if type(dtstart) == datetime.date:  # pylint: disable=unidiomatic-typecheck
            if duration.seconds != 0:
                raise ValueError("Event with start date expects duration in days only")
        if duration < datetime.timedelta(seconds=0):
            raise ValueError(f"Expected duration to be positive but was {duration}")
        return values
