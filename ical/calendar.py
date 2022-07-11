"""Calendar implementation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .event import Event
from .timeline import Timeline


class Calendar(BaseModel):
    """A calendar with events."""

    events: list[Event] = Field(default=[])

    @property
    def timeline(self) -> Timeline:
        """Return a timeline view of events on the calendar."""
        return Timeline(self.events)
