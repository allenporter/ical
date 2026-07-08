"""Constants and enums representing rfc5545 values."""

import enum
from typing import Self

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


class ExtensibleEnum(str, enum.Enum):
    """Base class for extensible enums that allow non-standard fallback values."""

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        """Allow non-standard values (don't restrict to known constants)."""
        if value is None:
            return None
        value = str(value)

        # Check case-insensitive matching for known values to be user friendly
        upper_val = value.upper()
        for member in cls:
            if member.value == upper_val:
                return member

        obj = str.__new__(cls, value)
        obj._name_ = value
        obj._value_ = value
        return obj


@DATA_TYPE.register("CLASS")
class Classification(ExtensibleEnum):
    """Defines the access classification for a calendar component."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> Self | None:
        """Parse value into enum (accepts any string)."""
        return cls(prop.value)
