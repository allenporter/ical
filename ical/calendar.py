"""The Calendar component."""

from __future__ import annotations

from importlib import metadata
from typing import Optional

from pydantic import BaseModel, Field

from .event import Event
from .property_values import Text
from .timeline import Timeline
from .todo import Todo

_VERSION = metadata.version("ical")
_PRODID = metadata.metadata("ical")["prodid"]


class Calendar(BaseModel):
    """A sequence of calendar properities and calendar components."""

    prodid: Text = Field(default=_PRODID)
    version: Text = Field(default=_VERSION)
    calscale: Optional[Text] = None
    method: Optional[Text] = None
    x_prop: Optional[Text] = None
    iana_prop: Optional[Text] = None

    events: list[Event] = Field(alias="vevent", default_factory=list)
    todos: list[Todo] = Field(alias="vtodo", default_factory=list)

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(self.events)
