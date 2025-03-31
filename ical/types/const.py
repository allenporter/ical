"""Constants and enums representing rfc5545 values."""

import enum
from collections.abc import Generator, Callable
from typing import Any, Self

from .enum import create_enum_validator


class Classification(str, enum.Enum):
    """Defines the access classification for a calendar component."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"

    @classmethod
    def __get_validators__(cls) -> Generator[Callable[[Any], Any], None, None]:
        """Return a generator that validates the value against the enum."""
        yield create_enum_validator(Classification)
