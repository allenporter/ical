"""Library for parsing and encoding URI values."""

from __future__ import annotations

from typing import Any, Self
from urllib.parse import urlparse

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


@DATA_TYPE.register("URI")
class Uri(str):
    """A value type for a property that contains a uniform resource identifier."""

    @classmethod
    def __parse_property_value__(cls, value: ParsedProperty | str) -> Self:
        """Parse a calendar user address."""
        if isinstance(value, ParsedProperty):
            value = value.value
        urlparse(value)
        return cls(value)

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        return core_schema.no_info_before_validator_function(
            cls.__parse_property_value__, handler(source_type)
        )
