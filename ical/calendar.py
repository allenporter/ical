"""Calendar implementation."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .contentlines import parse_content
from .event import Event, IcsEvent
from .timeline import Timeline


class Calendar(BaseModel):
    """A calendar with events."""

    events: list[Event] = Field(default=[])

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(self.events)


class IcsCalendar(BaseModel):
    """A sequence of calendar properities and calendar components."""

    prodid: str
    version: str
    calscale: Optional[str] = None
    method: Optional[str] = None
    x_prop: Optional[str] = None
    iana_prop: Optional[str] = None
    events: list[IcsEvent] = Field(alias="vevent")


class IcsStream(BaseModel):
    """A container that is a collection of calendaring information."""

    calendars: list[IcsCalendar] = Field(alias="vcalendar")

    @staticmethod
    def from_content(content: str) -> "IcsStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        return IcsStream.parse_obj(parse_content(content))
