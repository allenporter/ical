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
    def __parse_property_value__(cls, prop: ParsedProperty) -> Self | None:
        """Parse value into enum."""
        try:
            return cls(prop.value)
        except ValueError:
            return None
