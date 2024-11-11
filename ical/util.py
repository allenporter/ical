"""Utility methods used by multiple components."""

from __future__ import annotations

import datetime
from importlib import metadata
import uuid

__all__ = [
    "dtstamp_factory",
    "uid_factory",
    "prodid_factory",
]


MIDNIGHT = datetime.time()
PRODID = "github.com/allenporter/ical"
VERSION = metadata.version("ical")


def dtstamp_factory() -> datetime.datetime:
    """Factory method for new event timestamps to facilitate mocking."""
    return datetime.datetime.now(tz=datetime.UTC)


def uid_factory() -> str:
    """Factory method for new uids to facilitate mocking."""
    return str(uuid.uuid1())


def prodid_factory() -> str:
    """Return the ical version to facilitate mocking."""
    return f"-//{PRODID}//{VERSION}//EN"


def local_timezone() -> datetime.tzinfo:
    """Get the local timezone to use when converting date to datetime."""
    if local_tz := datetime.datetime.now().astimezone().tzinfo:
        return local_tz
    return datetime.timezone.utc


def normalize_datetime(
    value: datetime.date | datetime.datetime, tzinfo: datetime.tzinfo | None = None
) -> datetime.datetime:
    """Convert date or datetime to a value that can be used for comparison."""
    if not isinstance(value, datetime.datetime):
        value = datetime.datetime.combine(value, MIDNIGHT)
    if value.tzinfo is None:
        if tzinfo is None:
            tzinfo = local_timezone()
        value = value.replace(tzinfo=tzinfo)
    return value
