"""Calendar implementation."""

from __future__ import annotations

import datetime
import re
import zoneinfo
from collections.abc import Callable
from typing import Any, Generator

DATETIME_REGEX = re.compile(r"^(TZID=[^:]+:)?([0-9]{8})T([0-9]{6})(Z)?$")
TZ_REGEX = re.compile(r"TZID=([^:]+):")
DATE_REGEX = re.compile(r"^([0-9]{8})$")
DATE_PARAM = "DATE"
DATETIME_PARAM = "DATE-TIME"

PROPERTY_VALUE = re.compile(r"^VALUE=([^:]+):(.*)$")

ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}


class Date(datetime.date):
    """Parser for rfc5545 date."""

    @classmethod
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], datetime.date], None, None]:
        yield cls.parse_date

    @classmethod
    def parse_date(cls, value: Any) -> datetime.date:
        """Parse a rfc5545 into a datetime.date."""
        if not isinstance(value, str):
            raise TypeError(f"Expected string for {DATE_PARAM} value: {value}")
        if value_match := PROPERTY_VALUE.fullmatch(value):
            if value_match.group(1) != DATE_PARAM:
                raise TypeError(f"Expected VALUE={DATE_PARAM} value: {value}")
            value = value_match.group(2)
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
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], datetime.datetime], None, None]:
        yield cls.parse_date_time

    @classmethod
    def parse_date_time(cls, value: Any) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        if not isinstance(value, str):
            raise TypeError(f"Expected string for {DATETIME_PARAM} value: {value}")
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
        if match.group(1) and (tzmatch := TZ_REGEX.fullmatch(match.group(1))):
            timezone = zoneinfo.ZoneInfo(tzmatch.group(1))
        elif match.group(4):  # Example: 19980119T070000Z
            timezone = datetime.timezone.utc

        # Example: 19980118T230000
        date_value = match.group(2)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        time_value = match.group(3)
        hour = int(time_value[0:2])
        minute = int(time_value[2:4])
        second = int(time_value[4:6])

        return datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=timezone
        )
