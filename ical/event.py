"""Event implementation."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional, Union

from pydantic import Field, validator

from .contentlines import ParsedProperty
from .properties import EventStatus
from .types import ComponentModel, Text

MIDNIGHT = datetime.time()


class Event(ComponentModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.
    """

    dtstamp: Union[datetime.datetime, datetime.date] = Field(
        default_factory=datetime.datetime.utcnow
    )
    uid: str = Field(default_factory=uuid.uuid1)

    summary: str = ""

    # Has an alias of 'start'
    dtstart: Union[datetime.datetime, datetime.date] = Field(
        default=None,
    )
    # Has an alias of 'end'
    dtend: Optional[Union[datetime.datetime, datetime.date]] = Field(
        default=None,
    )
    description: Optional[str] = None
    transparency: Optional[str] = Field(alias="transp", default=None)
    categories: list[str] = Field(default_factory=list)
    status: Optional[EventStatus] = None
    extras: Optional[list[ParsedProperty]] = None

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
    def duration(self) -> datetime.timedelta:
        """Return the event duration."""
        if not self.end:
            raise ValueError("Cannot determine duration with no event end")
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

    @validator("status", pre=True, allow_reuse=True)
    def parse_status(cls, value: Any) -> str | None:
        """Parse an EventStatus from a ParsedPropertyValue."""
        value = Text.parse_text(value)
        if value and not isinstance(value, str):
            raise ValueError(f"Expected Text value as a string: {value}")
        return value

    @validator("categories", pre=True, allow_reuse=True)
    def parse_categories(cls, value: Any) -> list[str]:
        """Parse Categories from a list of ParsedProperty."""
        values: list[str] = []
        for prop in value:
            if not isinstance(prop, str):
                raise ValueError(f"Expected Text value as a string: {value}")
            values.extend(prop.split(","))
        return values
