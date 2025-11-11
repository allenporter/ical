"""Utility methods used by multiple components."""

from __future__ import annotations

from collections.abc import Sequence
import datetime
from importlib import metadata
from types import NoneType
from typing import TYPE_CHECKING, Any, Union, cast, get_args, get_origin, overload
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


def get_field_type(annotation: Any) -> Any:
    """Filter Optional type, e.g. for 'Optional[int]' return 'int'."""
    if get_origin(annotation) is Union:
        args: Sequence[Any] = get_args(annotation)
        if len(args) == 2:
            args = [arg for arg in args if arg is not NoneType]
            if len(args) == 1:
                return args[0]
    return annotation


@overload
def parse_date_and_datetime(value: None) -> None: ...


@overload
def parse_date_and_datetime(value: str | datetime.date) -> datetime.date: ...


def parse_date_and_datetime(value: str | datetime.date | None) -> datetime.date | None:
    """Coerce str into date and datetime value."""
    if not isinstance(value, str):
        return value
    if "T" in value or " " in value:
        return datetime.datetime.fromisoformat(value)
    return datetime.date.fromisoformat(value)


def parse_date_and_datetime_list(
    values: Sequence[str] | Sequence[datetime.date],
) -> list[datetime.date | datetime.datetime]:
    """Coerce list[str] into list[date | datetime] values."""
    if not values:
        return []
    if not isinstance(values[0], str):
        if TYPE_CHECKING:
            values = cast(list[datetime.date | datetime.datetime], values)
        return values
    if TYPE_CHECKING:
        values = cast(Sequence[str], values)
    return [
        datetime.datetime.fromisoformat(val)
        if "T" in val or " " in val
        else datetime.date.fromisoformat(val)
        for val in values
    ]
