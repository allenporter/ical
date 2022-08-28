"""Parser for the the PRIORITY type."""

from collections.abc import Callable
from typing import Generator

from ical.parsing.property import ParsedProperty

from .integer import IntEncoder


class Priority(int):
    """Defines relative priority for a calendar component."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_priority

    @classmethod
    def parse_priority(cls, value: ParsedProperty) -> int:
        """Parse a rfc5545 into a text value."""
        priority = IntEncoder.__parse_property_value__(value)
        if priority < 0 or priority > 9:
            raise ValueError("Expected priority between 0-9")
        return priority
