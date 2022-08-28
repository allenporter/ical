"""Library for parsing and encoding URI values."""

from __future__ import annotations

from urllib.parse import urlparse

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


@DATA_TYPE.register("URI")
class Uri(str):
    """A value type for a property that contains a uniform resource identifier."""

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> Uri:
        """Parse a calendar user address."""
        urlparse(prop.value)
        return Uri(prop.value)
