"""A grouping of component properties that describe a to-do."""

from __future__ import annotations

import datetime
import enum
from typing import Any, Optional, Union

try:
    from pydantic.v1 import Field, root_validator
except ImportError:
    from pydantic import Field, root_validator

from .alarm import Alarm
from .component import ComponentModel, validate_until_dtstart, validate_recurrence_dates
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
    uid: str = Field(default_factory=lambda: uid_factory())

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    categories: list[str] = Field(default_factory=list)
    classification: Optional[Classification] = Field(alias="class", default=None)
    comment: list[str] = Field(default_factory=list)
    completed: Optional[datetime.datetime] = None
    contacts: list[str] = Field(alias="contact", default_factory=list)
    created: Optional[datetime.datetime] = None
    description: Optional[str] = None

    # Has alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date, None] = None

    due: Union[datetime.datetime, datetime.date, None] = None
    duration: Optional[datetime.timedelta] = None
    exdate: list[Union[datetime.datetime, datetime.date]] = Field(default_factory=list)
    geo: Optional[Geo] = None
    last_modified: Optional[datetime.datetime] = Field(
        alias="last-modified", default=None
    )
    location: str = ""
    organizer: Optional[CalAddress] = None
    percent: Optional[int] = None
    priority: Optional[Priority] = None
    recurrence_id: Optional[RecurrenceId] = Field(alias="recurrence-id")

    related_to: list[RelatedTo] = Field(alias="related-to", default_factory=list)
    """Used to represent a relationship or reference between events."""

    request_status: Optional[RequestStatus] = Field(
        alias="request-status",
        default_value=None,
    )
    rrule: Optional[Recur] = None
    sequence: Optional[int] = None
    status: Optional[TodoStatus] = None
    summary: Optional[str] = None
    url: Optional[Uri] = None

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

    @root_validator
    def validate_one_due_or_duration(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that only one of duration or end date may be set."""
        if values.get("due") and values.get("duration"):
            raise ValueError("Only one of dtend or duration may be set." "")
        return values

    @root_validator
    def validate_duration_requires_start(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate that only one of duration or end date may be set."""
        if values.get("duration") and not values.get("dtstart"):
            raise ValueError("Duration requires that dtstart is specified")
        return values

    _validate_until_dtstart = root_validator(allow_reuse=True)(validate_until_dtstart)
    _validate_recurrence_dates = root_validator(allow_reuse=True)(
        validate_recurrence_dates
    )
