"""Parser for the PRIORITY type."""

from typing import Any, Self

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from ical.parsing.property import ParsedProperty

from .integer import IntEncoder


class Priority(int):
    """Defines relative priority for a calendar component."""

    @classmethod
    def parse_priority(cls, value: ParsedProperty | int) -> Self:
        """Parse a rfc5545 into a text value."""
        priority = IntEncoder.__parse_property_value__(value)
        if priority < 0 or priority > 9:
            raise ValueError("Expected priority between 0-9")
        return cls(priority)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_before_validator_function(
            cls.parse_priority, handler(source_type)
        )
