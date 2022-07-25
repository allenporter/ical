"""The core, a collection of Calendar and Scheduling objects."""

# mypy: allow-any-generics

from __future__ import annotations

import json

from pydantic import Field

from .calendar import Calendar
from .contentlines import encode_content, parse_content
from .types import ICS_ENCODERS, ComponentModel, encode_component


class CalendarStream(ComponentModel):
    """A container that is a collection of calendaring information."""

    calendars: list[Calendar] = Field(alias="vcalendar")

    @classmethod
    def from_ics(cls, content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        components = parse_content(content)
        result: dict[str, list] = {}
        for component in components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        return cls.parse_obj(result)

    def ics(self) -> str:
        """Encode the calendar stream as an rfc5545 iCalendar Stream content."""
        model = json.loads(
            self.json(exclude_unset=True, by_alias=True, exclude_none=True)
        )
        return encode_content(encode_component("stream", model).components)


class IcsCalendarStream(CalendarStream):
    """A calendar stream that supports re-encoding ICS."""

    class Config:
        """Configuration for IcsCalendarStream pydantic model."""

        json_encoders = ICS_ENCODERS
