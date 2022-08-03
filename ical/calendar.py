"""The Calendar component."""

from __future__ import annotations

from importlib import metadata
from typing import Optional

from pydantic import Field

from .contentlines import ParsedProperty
from .event import Event
from .timeline import SortedIterable, Timeline
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

    # Unknown or unsupported properties
    extras: list[ParsedProperty] = Field(default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(SortedIterable(self.events))
