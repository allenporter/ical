"""The Calendar component."""

from __future__ import annotations

from importlib import metadata
from typing import Optional

from pydantic import Field

from .event import Event
from .timeline import Timeline
from .todo import Todo
from .types import ComponentModel

_VERSION = metadata.version("ical")
_PRODID = metadata.metadata("ical")["prodid"]


class Calendar(ComponentModel):
    """A sequence of calendar properities and calendar components."""

    version: str = Field(default=_VERSION)
    prodid: str = Field(default=_PRODID)
    calscale: Optional[str] = None
    method: Optional[str] = None
    x_prop: Optional[str] = None
    iana_prop: Optional[str] = None

    events: list[Event] = Field(alias="vevent", default_factory=list)
    todos: list[Todo] = Field(alias="vtodo", default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(self.events)
