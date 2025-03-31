"""The core, a collection of Calendar and Scheduling objects.

This is an example of parsing an ics file as a stream of calendar objects:
```python
from pathlib import Path
from ical.calendar_stream import IcsCalendarStream

filename = Path("example/calendar.ics")
with filename.open() as ics_file:
    stream = IcsCalendarStream.from_ics(ics_file.read())
    print("File contains %s calendar(s)", len(stream.calendars))
```

You can encode a calendar stream as ics content calling the `ics()` method on
the `IcsCalendarStream`:

```python
from pathlib import Path

filename = Path("/tmp/output.ics")
with filename.open(mode="w") as ics_file:
    ics_file.write(stream.ics())
```

"""

# mypy: allow-any-generics

from __future__ import annotations

import logging
import pyparsing

try:
    from pydantic.v1 import Field
except ImportError:
    from pydantic import Field  # type: ignore[assignment]

from .calendar import Calendar
from .component import ComponentModel
from .parsing.component import encode_content, parse_content
from .types.data_types import DATA_TYPE
from .exceptions import CalendarParseError

_LOGGER = logging.getLogger(__name__)


class CalendarStream(ComponentModel):
    """A container that is a collection of calendaring information.

    This object supports parsing an rfc5545 calendar file, but does not
    support encoding. See `IcsCalendarStream` instead for encoding ics files.
    """

    calendars: list[Calendar] = Field(alias="vcalendar", default_factory=list)

    @classmethod
    def from_ics(cls, content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        try:
            components = parse_content(content)
        except pyparsing.ParseException as err:
            raise CalendarParseError(
                f"Failed to parse calendar contents", detailed_error=str(err)
            ) from err
        result: dict[str, list] = {"vcalendar": []}
        for component in components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        _LOGGER.debug("Parsing object %s", result)
        return cls(**result)

    def ics(self) -> str:
        """Encode the calendar stream as an rfc5545 iCalendar Stream content."""
        return encode_content(self.__encode_component_root__().components)


class IcsCalendarStream(CalendarStream):
    """A calendar stream that supports parsing and encoding ICS."""

    @classmethod
    def calendar_from_ics(cls, content: str) -> Calendar:
        """Load a single calendar from an ics string."""
        stream = cls.from_ics(content)
        if len(stream.calendars) == 1:
            return stream.calendars[0]
        if len(stream.calendars) == 0:
            return Calendar()
        raise CalendarParseError("Calendar Stream had more than one calendar")

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
