"""The core, a collection of Calendar and Scheduling objects."""

# mypy: allow-any-generics

from __future__ import annotations

import logging

from pydantic import Field

from .calendar import Calendar
from .contentlines import parse_content
from .model import ComponentModel

_LOGGER = logging.getLogger(__name__)


class CalendarStream(ComponentModel):
    """A container that is a collection of calendaring information."""

    calendars: list[Calendar] = Field(alias="vcalendar")

    @staticmethod
    def from_ics(content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        components = parse_content(content)
        result: dict[str, list] = {}
        for component in components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        return CalendarStream.parse_obj(result)
