"""Library for parsing and encoding UTC-OFFSET values."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE

UTC_OFFSET_REGEX = re.compile(r"^([-+]?)([0-9]{2})([0-9]{2})([0-9]{2})?$")


@DATA_TYPE.register("UTC-OFFSET")
@dataclass
class UtcOffset:
    """Contains an offset from UTC to local time."""

    offset: datetime.timedelta

    @classmethod
    def __parse_property_value__(cls, prop: Any) -> UtcOffset:
        """Parse a UTC Offset."""
        if isinstance(prop, UtcOffset):
            return prop
        value = prop
        if isinstance(prop, ParsedProperty):
            value = prop.value
        if not (match := UTC_OFFSET_REGEX.fullmatch(value)):
            raise ValueError(f"Expected value to match UTC-OFFSET pattern: {value}")
        sign, hours, minutes, seconds = match.groups()
        result = datetime.timedelta(
            hours=int(hours or 0),
            minutes=int(minutes or 0),
            seconds=int(seconds or 0),
        )
        if sign == "-":
            result = -result
        return UtcOffset(result)

    @classmethod
    def __encode_property_json__(cls, value: UtcOffset) -> str:
        """Serialize a time delta as a UTC-OFFSET ICS value."""
        duration = value.offset
        parts = []
        if duration < datetime.timedelta(days=0):
            parts.append("-")
            duration = -duration
        else:
            parts.append("+")
        seconds = duration.seconds
        hours = int(seconds / 3600)
        seconds %= 3600
        parts.append(f"{hours:02}")
        minutes = int(seconds / 60)
        seconds %= 60
        parts.append(f"{minutes:02}")
        return "".join(parts)
