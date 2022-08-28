"""Library for parsing and encoding BOOLEAN values."""

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE


@DATA_TYPE.register("BOOLEAN")
class BooleanEncoder:
    """Encode a boolean ICS value."""

    @classmethod
    def __property_type__(cls) -> type:
        return bool

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> bool:
        """Parse an rfc5545 property into a boolean."""
        if prop.value == "TRUE":
            return True
        if prop.value == "FALSE":
            return False
        raise ValueError(f"Unable to parse value as boolean: {prop}")

    @classmethod
    def __encode_property_value__(cls, value: bool) -> str:
        """Serialize boolean as an ICS value."""
        return "TRUE" if value else "FALSE"
