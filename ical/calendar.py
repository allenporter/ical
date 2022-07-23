"""The Calendar component."""

from __future__ import annotations

from importlib import metadata
from typing import Optional

from pydantic import BaseModel, Field, root_validator

from .event import Event
from .property_values import Text
from .timeline import Timeline
from .todo import Todo
from .validators import parse_property_fields

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

    # Flatten list[ParsedProperty] to ParsedProperty where appropriate
    _parse_property_fields = root_validator(pre=True, allow_reuse=True)(
        parse_property_fields
    )
