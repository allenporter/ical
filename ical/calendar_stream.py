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

Fetching a remote ics file without blocking the event loop requires the
optional `ical[async]` extra (which installs `aiohttp`):

```python
from ical.calendar_stream import IcsCalendarStream

stream = await IcsCalendarStream.from_url("https://example.com/calendar.ics")
```

"""

# ty: allow-any-generics

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import Field, field_serializer

from .calendar import Calendar
from .component import ComponentModel
from .parsing.component import encode_content, parse_content
from .types.data_types import serialize_field
from .exceptions import CalendarFetchError, CalendarParseError
from pydantic import ConfigDict

if TYPE_CHECKING:
    import aiohttp

_LOGGER = logging.getLogger(__name__)

__all__ = ["CalendarStream", "IcsCalendarStream"]

_ASYNC_EXTRA_ERROR = (
    "The aiohttp library is required for async URL fetching. Install it "
    "with the optional extra: `pip install ical[async]`"
)


class CalendarStream(ComponentModel):
    """A container that is a collection of calendaring information.

    This object supports parsing an rfc5545 calendar file, but does not
    support encoding. See `IcsCalendarStream` instead for encoding ics files.
    """

    calendars: list[Calendar] = Field(alias="vcalendar", default_factory=list)

    @classmethod
    def from_ics(cls, content: str) -> "CalendarStream":
        """Factory method to create a new instance from an rfc5545 iCalendar content."""
        components = parse_content(content)
        result: dict[str, list] = {"vcalendar": []}
        for component in components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        _LOGGER.debug("Parsing object %s", result)
        return cls(**result)

    @classmethod
    async def from_url(
        cls, url: str, session: "aiohttp.ClientSession | None" = None
    ) -> "CalendarStream":
        """Async factory method to fetch and parse an rfc5545 iCalendar url.

        This avoids blocking the event loop while fetching a remote ics file
        (e.g. a calendar subscription url), which is useful for applications
        such as Home Assistant that are built on asyncio. Parsing the fetched
        content happens synchronously since it is fast and CPU-bound.

        This requires the optional `aiohttp` dependency, installable with the
        `ical[async]` extra. An existing `aiohttp.ClientSession` may be
        passed in to reuse connection pooling; otherwise a session is created
        and closed automatically for this single request.
        """
        try:
            import aiohttp  # noqa: PLC0415
        except ImportError as err:
            raise ImportError(_ASYNC_EXTRA_ERROR) from err

        async def _fetch(active_session: aiohttp.ClientSession) -> str:
            try:
                async with active_session.get(url) as response:
                    response.raise_for_status()
                    return await response.text()
            except aiohttp.ClientError as err:
                raise CalendarFetchError(
                    f"Failed to fetch calendar from url {url!r}: {err}"
                ) from err

        if session is not None:
            content = await _fetch(session)
        else:
            async with aiohttp.ClientSession() as owned_session:
                content = await _fetch(owned_session)
        return cls.from_ics(content)

    def ics(self) -> str:
        """Encode the calendar stream as an rfc5545 iCalendar Stream content."""
        return encode_content(self.__encode_component_root__().components)


class IcsCalendarStream(CalendarStream):
    """A calendar stream that supports parsing and encoding ICS."""

    @classmethod
    def calendar_from_ics(cls, content: str) -> Calendar:
        """Load a single calendar from an ics string."""
        stream = cls.from_ics(content)
        return cls._single_calendar(stream)

    @classmethod
    async def calendar_from_url(
        cls, url: str, session: "aiohttp.ClientSession | None" = None
    ) -> Calendar:
        """Async convenience method to fetch and load a single calendar from a url.

        See `from_url` for details on the optional `ical[async]` dependency
        and the `session` argument.
        """
        stream = await cls.from_url(url, session=session)
        return cls._single_calendar(stream)

    @staticmethod
    def _single_calendar(stream: "CalendarStream") -> Calendar:
        """Return the single calendar in the stream, or raise an error."""
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

    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
    )
    serialize_fields = field_serializer("*")(serialize_field)  # type: ignore[pydantic-field]
