"""Library for parsing TEXT values."""

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE

UNESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}
ESCAPE_CHAR = {v: k for k, v in UNESCAPE_CHAR.items()}


@DATA_TYPE.register("TEXT")
class TextEncoder:
    """Encode an rfc5545 TEXT value."""

    @classmethod
    def __property_type__(cls) -> type:
        return str

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> str:
        """Parse a rfc5545 into a text value."""
        for key, vin in UNESCAPE_CHAR.items():
            if key not in prop.value:
                continue
            prop.value = prop.value.replace(key, vin)
        return prop.value

    @classmethod
    def __encode_property_value__(cls, value: str) -> str:
        """Serialize text as an ICS value."""
        for key, vin in ESCAPE_CHAR.items():
            if key not in value:
                continue
            value = value.replace(key, vin)
        return value
