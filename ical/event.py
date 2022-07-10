"""Event implementation."""

from __future__ import annotations

import datetime
from typing import Any, Tuple, Union

from pydantic import BaseModel


class Event(BaseModel):
    """A single event on a calendar.

    Can either be for a specific day, or with a start time and duration/end time.
    """

    summary: str
    start: Union[datetime.datetime, datetime.date]
    end: Union[datetime.datetime, datetime.date]

    @property
    def duration(self) -> datetime.timedelta:
        """Return the event duration."""
        return self.end - self.start

    def starts_within(self, other: "Event") -> bool:
        """Return True if this event starts while the other event is active."""
        return other.start <= self.start < other.end

    def ends_within(self, other: "Event") -> bool:
        """Return True if this event ends while the other event is active."""
        return other.start <= self.end < other.end

    def intersects(self, other: "Event") -> bool:
        """Return True if this event overlaps with the other event."""
        return (
            other.start <= self.start < other.end
            or other.start <= self.end < other.end
            or self.start <= other.start < self.end
            or self.start <= other.end < self.end
        )

    def includes(self, other: "Event") -> bool:
        """Return True if the other event starts and ends within this event."""
        return (
            self.start <= other.start < self.end and self.start <= other.end < self.end
        )

    def is_included_in(self, other: "Event") -> bool:
        """Return True if this event starts and ends within the other event."""
        return other.start <= self.start and self.end < other.end

    def _tuple(
        self,
    ) -> Tuple[datetime.date | datetime.datetime, datetime.date | datetime.datetime]:
        return (self.start, self.end)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() < other._tuple()

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() > other._tuple()

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() <= other._tuple()

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self._tuple() >= other._tuple()
