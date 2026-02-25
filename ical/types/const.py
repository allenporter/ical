"""Constants and enums representing rfc5545 values."""

import enum
from typing import Self

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


@DATA_TYPE.register("CLASS")
class Classification(str, enum.Enum):
    """Defines the access classification for a calendar component."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"

    @classmethod
    def _missing_(cls, value: object) -> Self | None:
        """Allow non-standard CLASS values (don't restrict to known constants)."""
        if value is None:
            return None
        value = str(value)

        obj = str.__new__(cls, value)
        obj._name_ = value
        obj._value_ = value
        return obj

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> Self | None:
        """Parse value into enum (accepts any string)."""
        return cls(prop.value)
