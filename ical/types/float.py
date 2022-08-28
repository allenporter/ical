"""Library for parsing and encoding FLOAT values."""

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


@DATA_TYPE.register("FLOAT")
class FloatEncoder:
    """Encode a float ICS value."""

    @classmethod
    def __property_type__(cls) -> type:
        return float

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> float:
        """Parse a rfc5545 property into a text value."""
        return float(prop.value)
