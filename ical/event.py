"""Event implementation."""

from __future__ import annotations

import datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, root_validator, validator

from .contentlines import ParsedProperty
from .properties import EventStatus
from .property_values import Date, DateTime, Text

MIDNIGHT = datetime.time()


class Event(BaseModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.
    """

    summary: str
    start: Union[datetime.datetime, datetime.date]
    end: Union[datetime.datetime, datetime.date]

    @property
    def start_datetime(self) -> datetime.datetime:
        """Return the events start as a datetime."""
        if isinstance(self.start, datetime.datetime):
            return self.start
        if isinstance(self.start, datetime.date):
            return datetime.datetime.combine(self.start, MIDNIGHT)
        raise ValueError("Unable to convert date to datetime")

    @property
    def end_datetime(self) -> datetime.datetime:
        """Return the events end as a datetime."""
        if isinstance(self.end, datetime.datetime):
            return self.end
        if isinstance(self.end, datetime.date):
            return datetime.datetime.combine(self.end, MIDNIGHT)
        raise ValueError("Unable to convert date to datetime")

    @property
    def duration(self) -> datetime.timedelta:
        """Return the event duration."""
        return self.end - self.start

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


class IcsEvent(BaseModel):
    """A calendar event component."""

    dtstamp: Union[DateTime, Date]
    uid: Text
    dtstart: Union[DateTime, Date]
    dtend: Optional[Union[DateTime, Date]] = None
    summary: Text
    description: Optional[Text] = None
    transparency: Optional[Text] = Field(alias="transp", default=None)
    categories: Optional[list[str]] = None
    status: Optional[EventStatus] = None
    extras: Optional[list[tuple[str, ParsedProperty]]] = None

    @validator("status", pre=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse an EventStatus from a ParsedPropertyValue."""
        for func in Text.__get_validators__():
            value = func(value)
        if value and not isinstance(value, str):
            raise ValueError("Expected Text value as a string")
        return value

    @validator("categories", pre=True)
    def parse_categories(cls, value: Any) -> list[str] | None:
        """Parse Categories from a ParsedPropertyValue."""
        for func in Text.__get_validators__():
            value = func(value)
        if not value:
            return []
        if not isinstance(value, str):
            raise ValueError("Expected Text value as a string")
        return value.split(",")

    @root_validator(pre=True)
    def parse_extra_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse extra fields not in the model."""
        all_fields = {
            field.alias for field in cls.__fields__.values() if field.alias != "extras"
        }
        extras: list[tuple[str, ParsedProperty]] = []
        for field_name in list(values):
            if field_name in all_fields:
                continue
            for prop in values.pop(field_name):
                extras.append((field_name, prop))
        if extras:
            values["extras"] = extras
        return values
