"""Event implementation."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional, Union

from pydantic import Field, root_validator, validator

from .contentlines import ParsedProperty
from .types import (
    CalAddress,
    Classification,
    ComponentModel,
    EventStatus,
    Geo,
    Priority,
    Uri,
    parse_text,
)

MIDNIGHT = datetime.time()


class Event(ComponentModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=datetime.datetime.utcnow
    )
    uid: str = Field(default_factory=uuid.uuid1)
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
    classification: Optional[Classification] = Field(alias="class", default=None)
    comment: list[str] = Field(default_factory=list)
    contacts: list[str] = Field(alias="contact", default_factory=list)
    created: Optional[datetime.datetime] = None
    description: str = ""
    geo: Optional[Geo] = None
    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    location: str = ""
    organization: str = ""
    organizer: Optional[CalAddress] = None
    priority: Optional[Priority] = None
    related: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    status: Optional[EventStatus] = None
    transparency: Optional[str] = Field(alias="transp", default=None)
    url: Optional[Uri] = None

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    # Other properties needed:
    # - seq
    # - recurid
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
    def start(self) -> Union[datetime.datetime, datetime.date]:
        """Return the start time for the event."""
        return self.dtstart

    @property
    def end(self) -> Union[datetime.datetime, datetime.date, None]:
        """Return the end time for the event."""
        if self.duration:
            return self.dtstart + self.duration
        return self.dtend

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime."""
        if isinstance(self.start, datetime.datetime):
            return self.start
        # is datetime.date
        return datetime.datetime.combine(self.start, MIDNIGHT)

    @property
    def end_datetime(self) -> datetime.datetime:
        """Return the events end as a datetime."""
        if isinstance(self.end, datetime.datetime):
            return self.end
        if isinstance(self.end, datetime.date):
            return datetime.datetime.combine(self.end, MIDNIGHT)
        raise ValueError("Unable to convert date to datetime")

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
            or other.start_datetime <= self.end_datetime < other.end_datetime
            or self.start_datetime <= other.start_datetime < self.end_datetime
            or self.start_datetime <= other.end_datetime < self.end_datetime
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

    @validator("status", pre=True, allow_reuse=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse an EventStatus from a ParsedPropertyValue."""
        value = parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected text value as a string: {value}")
        return value

    @validator("categories", pre=True, allow_reuse=True)
    def parse_categories(cls, value: Any) -> list[str]:
        """Parse Categories from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            if not isinstance(prop, str):
                raise ValueError(f"Expected text value as a string: {value}")
            values.extend(prop.split(","))
        return values

    @validator("resources", pre=True, allow_reuse=True)
    def parse_resources(cls, value: Any) -> list[str]:
        """Parse resources from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            if not isinstance(prop, str):
                raise ValueError(f"Expected text value as a string: {value}")
            values.extend(prop.split(","))
        return values

    @validator("classification", pre=True, allow_reuse=True)
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
