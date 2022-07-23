"""The core, a collection of Calendar and Scheduling objects."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .calendar import Calendar
from .contentlines import parse_content


class CalendarStream(BaseModel):
    """A container that is a collection of calendaring information."""

    calendars: list[Calendar] = Field(alias="vcalendar")

    @staticmethod
    def from_ics(content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        return CalendarStream.parse_obj(parse_content(content))
