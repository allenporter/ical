"""The core, a collection of Calendar and Scheduling objects."""

# mypy: allow-any-generics

from __future__ import annotations

from pydantic import Field

from ._types import ComponentModel
from .calendar import Calendar
from .parsing.component import encode_content, parse_content
from .types.data_types import DATA_TYPE


class CalendarStream(ComponentModel):
    """A container that is a collection of calendaring information."""

    calendars: list[Calendar] = Field(alias="vcalendar", defaut_factory=[])

    @classmethod
    def from_ics(cls, content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        components = parse_content(content)
        result: dict[str, list] = {"vcalendar": []}
        for component in components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        return cls.parse_obj(result)

    def ics(self) -> str:
        """Encode the calendar stream as an rfc5545 iCalendar Stream content."""
        return encode_content(self.__encode_component_root__().components)


class IcsCalendarStream(CalendarStream):
    """A calendar stream that supports re-encoding ICS."""

    @classmethod
    def calendar_from_ics(cls, content: str) -> Calendar:
        """Load a single calendar from an ics string."""
        stream = cls.from_ics(content)
        if len(stream.calendars) == 1:
            return stream.calendars[0]
        if len(stream.calendars) == 0:
            return Calendar()
        raise ValueError("Calendar Stream had more than one calendar")

    @classmethod
    def calendar_to_ics(cls, calendar: Calendar) -> str:
        """Serialize a calendar as an ICS stream."""
        stream = cls(vcalendar=[calendar])
        return stream.ics()

    class Config:
        """Configuration for IcsCalendarStream pydantic model."""

        json_encoders = DATA_TYPE.encode_property_json
        validate_assignment = True
        allow_population_by_field_name = True
