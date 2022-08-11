"""The Calendar component."""

from __future__ import annotations

from importlib import metadata
from typing import Optional

from pydantic import Field

from .event import Event
from .freebusy import FreeBusy
from .journal import Journal
from .parsing.property import ParsedProperty
from .timeline import Timeline, calendar_timeline
from .timezone import Timezone
from .todo import Todo
from .types import ComponentModel

_VERSION = metadata.version("ical")
_PRODID = metadata.metadata("ical")["prodid"]


class Calendar(ComponentModel):
    """A sequence of calendar properties and calendar components."""

    calscale: Optional[str] = None
    method: Optional[str] = None
    prodid: str = Field(default=_PRODID)
    version: str = Field(default=_VERSION)

    # Calendar components
    events: list[Event] = Field(alias="vevent", default_factory=list)
    todos: list[Todo] = Field(alias="vtodo", default_factory=list)
    journal: list[Journal] = Field(alias="vjournal", default_factory=list)
    freebusy: list[FreeBusy] = Field(alias="vfreebusy", default_factory=list)
    timezones: list[Timezone] = Field(alias="vtimezone", default_factory=list)

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return calendar_timeline(self.events)
