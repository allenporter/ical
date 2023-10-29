"""A timespan is defined by a start and end time and used for comparisons.

A common way to compare events is by comparing their start and end time. Often
there are corner cases such as an all day event which does not specify a
specific time, but instead needs to be interpreted in the timezone of the
attendee. A timespan is unambiguous in that it is created with that timezone.

A `Timespan` is not instantiated directly, but created by a calendar component
such as an `Event`.
"""

from __future__ import annotations

import datetime
from typing import Any

from .util import normalize_datetime

__all__ = ["Timespan"]


class Timespan:
    """An unambiguous definition of a start and end time.

    A timespan is not ambiguous in that it can never be a "floating" time range
    and instead is always aligned to some kind of timezone or utc.
    """

    def __init__(self, start: datetime.datetime, end: datetime.datetime) -> None:
        """..."""
        self._start = start
        self._end = end
        if not self._start.tzinfo:
            raise ValueError(f"Start time did not have a timezone: {self._start}")
        self._tzinfo = self._start.tzinfo

    @classmethod
    def of(  # pylint: disable=invalid-name]
        cls,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
        tzinfo: datetime.tzinfo | None = None,
    ) -> "Timespan":
        """Create a Timestapn for the specified date range."""
        return Timespan(
            normalize_datetime(start, tzinfo), normalize_datetime(end, tzinfo)
        )

    @property
    def start(self) -> datetime.datetime:
        """Return the timespan start as a datetime."""
        return self._start

    @property
    def end(self) -> datetime.datetime:
        """Return the timespan end as a datetime."""
        return self._end

    @property
    def tzinfo(self) -> datetime.tzinfo:
        """Return the timespan timezone."""
        return self._tzinfo

    @property
    def duration(self) -> datetime.timedelta:
        """Return the timespan duration."""
        return self.end - self.start

    def starts_within(self, other: "Timespan") -> bool:
        """Return True if this timespan starts while the other timespan is active."""
        return other.start <= self.start < other.end

    def ends_within(self, other: "Timespan") -> bool:
        """Return True if this timespan ends while the other event is active."""
        return other.start <= self.end < other.end

    def intersects(self, other: "Timespan") -> bool:
        """Return True if this timespan overlaps with the other event."""
        return (
            other.start <= self.start < other.end
            or other.start < self.end <= other.end
            or self.start <= other.start < self.end
            or self.start < other.end <= self.end
        )

    def includes(self, other: "Timespan") -> bool:
        """Return True if the other timespan starts and ends within this event."""
        return (
            self.start <= other.start < self.end and self.start <= other.end < self.end
        )

    def is_included_in(self, other: "Timespan") -> bool:
        """Return True if this timespan starts and ends within the other event."""
        return other.start <= self.start and self.end < other.end

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        return (self._start, self._end) < (other.start, other.end)

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        return (self._start, self._end) > (other.start, other.end)

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        return (self._start, self._end) <= (other.start, other.end)

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        return (self._start, self._end) >= (other.start, other.end)
