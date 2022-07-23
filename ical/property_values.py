"""Implementation of the strong types for rfc5545 properties.

These types are pydantic custom field types. The content line parser
produces a `list[ParsedProperty]`, supporting repeated values for the
same property. (This likely needs to be decoupled and moved to a higer
level).
"""

from __future__ import annotations

import datetime
import re
import zoneinfo
from collections.abc import Callable
from typing import Generator

from .contentlines import ParsedProperty

DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
DATE_REGEX = re.compile(r"^([0-9]{8})$")
DATE_PARAM = "DATE"
DATETIME_PARAM = "DATE-TIME"

PROPERTY_VALUE = re.compile(r"^VALUE=([^:]+):(.*)$")

ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}


# This is a property parameter, currently used by the DATE-TIME type. It
# should probably be composed in the property or in a separate file of
# property parameters.
TZID = "TZID"


class Date(datetime.date):
    """Parser for rfc5545 date."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_date

    @classmethod
    def parse_date(cls, prop: ParsedProperty) -> datetime.date | None:
        """Parse a rfc5545 into a datetime.date."""
        value = prop.value
        if not (match := DATE_REGEX.fullmatch(value)):
            raise ValueError(f"Expected value to match {DATE_PARAM} pattern: {value}")
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        return datetime.date(year, month, day)


class DateTime(datetime.datetime):
    """Parser for rfc5545 date times."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_date_time

    @classmethod
    def parse_date_time(cls, prop: ParsedProperty) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        value = prop.value
        if value_match := PROPERTY_VALUE.fullmatch(value):
            if value_match.group(1) != DATETIME_PARAM:
                raise TypeError(f"Expected VALUE={DATETIME_PARAM} value: {value}")
            value = value_match.group(2)
        if not (match := DATETIME_REGEX.fullmatch(value)):
            raise ValueError(
                f"Expected value to match {DATETIME_PARAM} pattern: {value}"
            )

        # Example: TZID=America/New_York:19980119T020000
        timezone: datetime.tzinfo | None = None
        if tzid := prop.get_parameter_value(TZID):
            timezone = zoneinfo.ZoneInfo(tzid)
        elif match.group(3):  # Example: 19980119T070000Z
            timezone = datetime.timezone.utc

        # Example: 19980118T230000
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        time_value = match.group(2)
        hour = int(time_value[0:2])
        minute = int(time_value[2:4])
        second = int(time_value[4:6])

        return datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=timezone
        )


class Text(str):
    """A type that contains human readable text."""

    ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_text
        yield cls.unescape_text

    @classmethod
    def parse_text(cls, prop: ParsedProperty) -> str:
        """Parse a rfc5545 into a text value."""
        return prop.value

    @classmethod
    def unescape_text(cls, value: str) -> str:
        """Escape human readable text items."""
        for key, vin in Text.ESCAPE_CHAR.items():
            value = value.replace(key, vin)
        return value


class Integer(int):
    """A type that contains a signed integer value."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_int

    @classmethod
    def parse_int(cls, prop: ParsedProperty) -> int:
        """Parse a rfc5545 into a text value."""
        return int(prop.value)
