"""Utility methods used by multiple components."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

__all__ = [
    "use_local_timezone",
    "dtstamp_factory",
    "uid_factory",
]


MIDNIGHT = datetime.time()
LOCAL_TZ = ContextVar[datetime.tzinfo]("_local_tz")


def dtstamp_factory() -> datetime.datetime:
    """Factory method for new event timestamps to facilitate mocking."""
    return datetime.datetime.utcnow()


def uid_factory() -> str:
    """Factory method for new uids to facilitate mocking."""
    return str(uuid.uuid1())


@contextmanager
def use_local_timezone(local_tz: datetime.tzinfo) -> Generator[None, None, None]:
    """Set the local timezone to use when converting a date to datetime.

    This is expected to be used as a context manager when the default timezone
    used by python is not the timezone to be used for calendar operations (the
    attendees local timezone).

    Example:
    ```
    import datetime
    import zoneinfo
    from ical.calendar import Calendar
    from ical.event import Event
    from ical.util import use_local_timezone

    cal = Calendar()
    cal.events.append(
        Event(
            summary="Example",
            start=datetime.date(2022, 2, 1),
            end=datetime.date(2022, 2, 2)
        )
    )
    # Use UTC-8 as local timezone
    with use_local_timezone(zoneinfo.ZoneInfo("America/Los_Angeles")):
        # Returns event above
        events = cal.timeline.start_after(
            datetime.datetime(2022, 2, 1, 7, 59, 59, tzinfo=datetime.timezone.utc))

        # Does not return event above
        events = cal.timeline.start_after(
            datetime.datetime(2022, 2, 1, 8, 00, 00, tzinfo=datetime.timezone.utc))
    ```
    """
    orig_tz = LOCAL_TZ.set(local_tz)
    try:
        yield
    finally:
        LOCAL_TZ.reset(orig_tz)


def local_timezone() -> datetime.tzinfo:
    """Get the local timezone to use when converting date to datetime."""
    if local_tz := LOCAL_TZ.get(None):
        return local_tz
    if local_tz := datetime.datetime.now().astimezone().tzinfo:
        return local_tz
    return datetime.timezone.utc


def normalize_datetime(value: datetime.date | datetime.datetime) -> datetime.datetime:
    """Convert date or datetime to a value that can be used for comparison."""
    if not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, MIDNIGHT)
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_timezone())
    return value
