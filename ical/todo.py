"""A grouping of component properties that describe a to-do."""

from __future__ import annotations

import datetime
from typing import Any, Optional, Union

from pydantic import Field, root_validator, validator

from .alarm import Alarm
from .parsing.property import ParsedProperty
from .types import (
    CalAddress,
    ComponentModel,
    Geo,
    Priority,
    Recur,
    RequestStatus,
    TodoStatus,
    Uri,
    parse_text,
)
from .util import dtstamp_factory, normalize_datetime, uid_factory


class Todo(ComponentModel):
    """A calendar todo component."""

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=dtstamp_factory
    )
    uid: str = Field(default_factory=uid_factory)

    attendees: list[CalAddress] = Field(alias="attendee", default_factory=list)
    categories: list[str] = Field(default_factory=list)
    classification: Optional[str] = Field(alias="class", default=None)
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
    recurrence_id: Optional[Union[datetime.datetime, datetime.date]] = Field(
        alias="recurrence-id"
    )
    request_status: Optional[RequestStatus] = Field(
        alias="request-status", default_value=None
    )
    rrule: Optional[Recur] = None
    sequence: Optional[int] = None
    status: Optional[TodoStatus] = None
    summary: Optional[str] = None
    url: Optional[Uri] = None

    alarms: list[Alarm] = Field(alias="valarm", default_factory=list)

    extras: list[ParsedProperty] = Field(default_factory=list)

    def __init__(self, **data: dict[str, Any]) -> None:
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

    @validator("status", pre=True, allow_reuse=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse a TodoStatus from a ParsedPropertyValue."""
        value = parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected text value as a string: {value}")
        return value

    @validator("categories", pre=True, allow_reuse=True)
    def parse_categories(cls, value: list[str]) -> list[str]:
        """Parse Categories from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            values.extend(prop.split(","))
        return values

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
