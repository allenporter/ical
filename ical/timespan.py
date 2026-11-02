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

from .util import normalize_datetime, to_utc

__all__ = ["Timespan"]


class Timespan:
    """An unambiguous definition of a start and end time.

    A timespan is not ambiguous in that it can never be a "floating" time range
    and instead is always aligned to some kind of timezone or UTC. When created
    via :meth:`of`, ``date`` (all-day) and naive ``datetime`` inputs are first
    anchored to the viewer's ``tzinfo`` (such as local midnight), and
    :attr:`start`, :attr:`end`, and :attr:`tzinfo` preserve those original
    timezone-aware values.

    Internally, ``Timespan`` converts both endpoints to ``datetime.UTC``
    (:attr:`start_utc` and :attr:`end_utc`) and performs all ordering
    comparisons, interval predicates (such as :meth:`intersects` and
    :meth:`includes`), and :attr:`duration` arithmetic in UTC. Under Python's
    PEP 495 rules, comparing or subtracting two ``datetime`` objects that share
    the same ``tzinfo`` ignores ``fold`` and operates on wall-clock time, while
    ``==`` / ``!=`` across different ``tzinfo`` instances returns ``False`` /
    ``True`` for ambiguous fold or gap times. Evaluating in UTC provides a
    consistent chronological total order and true elapsed duration across DST
    transitions.
    """

    __slots__ = ("_start", "_end", "_tzinfo", "_start_utc", "_end_utc")

    def __init__(self, start: datetime.datetime, end: datetime.datetime) -> None:
        """Initialize a Timespan from timezone-aware start and end datetimes."""
        self._start = start
        self._end = end
        if self._start.tzinfo is None:
            raise ValueError(f"Start time did not have a timezone: {self._start}")
        if self._end.tzinfo is None:
            raise ValueError(f"End time did not have a timezone: {self._end}")
        self._tzinfo = self._start.tzinfo
        try:
            self._start_utc = to_utc(start)
        except ValueError as err:
            raise ValueError(
                f"Start time did not have a timezone: {self._start}"
            ) from err
        try:
            self._end_utc = to_utc(end)
        except ValueError as err:
            raise ValueError(f"End time did not have a timezone: {self._end}") from err

    @classmethod
    def of(  # pylint: disable=invalid-name]
        cls,
        start: datetime.date | datetime.datetime,
        end: datetime.date | datetime.datetime,
        tzinfo: datetime.tzinfo | None = None,
    ) -> "Timespan":
        """Create a Timespan for the specified date range."""
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
    def start_utc(self) -> datetime.datetime:
        """Return the timespan start as a UTC datetime."""
        return self._start_utc

    @property
    def end_utc(self) -> datetime.datetime:
        """Return the timespan end as a UTC datetime."""
        return self._end_utc

    @property
    def tzinfo(self) -> datetime.tzinfo:
        """Return the timespan timezone."""
        return self._tzinfo

    @property
    def duration(self) -> datetime.timedelta:
        """Return the timespan duration."""
        return self._end_utc - self._start_utc

    def starts_within(self, other: "Timespan") -> bool:
        """Return True if this timespan starts while the other timespan is active."""
        return other._start_utc <= self._start_utc < other._end_utc

    def ends_within(self, other: "Timespan") -> bool:
        """Return True if this timespan ends while the other event is active."""
        return other._start_utc < self._end_utc <= other._end_utc

    def intersects(self, other: "Timespan") -> bool:
        """Return True if this timespan overlaps with the other event."""
        return (
            other._start_utc <= self._start_utc < other._end_utc
            or other._start_utc < self._end_utc <= other._end_utc
            or self._start_utc <= other._start_utc < self._end_utc
            or self._start_utc < other._end_utc <= self._end_utc
        )

    def includes(self, other: "Timespan") -> bool:
        """Return True if the other timespan starts and ends within this event."""
        if self._start_utc == self._end_utc:
            return self._start_utc == other._start_utc == other._end_utc
        return (
            self._start_utc <= other._start_utc < self._end_utc
            and self._start_utc <= other._end_utc <= self._end_utc
        )

    def is_included_in(self, other: "Timespan") -> bool:
        """Return True if this timespan starts and ends within the other event."""
        return other._start_utc <= self._start_utc and self._end_utc <= other._end_utc

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        return self._start_utc == other._start_utc and self._end_utc == other._end_utc

    def __hash__(self) -> int:
        return hash((self._start_utc, self._end_utc))

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        if self._start_utc != other._start_utc:
            return self._start_utc < other._start_utc
        return self._end_utc < other._end_utc

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        if self._start_utc != other._start_utc:
            return self._start_utc > other._start_utc
        return self._end_utc > other._end_utc

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        if self._start_utc != other._start_utc:
            return self._start_utc < other._start_utc
        return self._end_utc <= other._end_utc

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, Timespan):
            return NotImplemented
        if self._start_utc != other._start_utc:
            return self._start_utc > other._start_utc
        return self._end_utc >= other._end_utc
