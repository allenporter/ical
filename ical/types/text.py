"""Library for parsing TEXT values."""

from typing import Any

from ical.parsing.property import ParsedProperty

UNESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}
ESCAPE_CHAR = {v: k for k, v in UNESCAPE_CHAR.items()}


class TextEncoder:
    """Encode an rfc5545 TEXT value."""

    @classmethod
    def parse_text(cls, prop: Any) -> str:
        """Parse a rfc5545 into a text value."""
        if not isinstance(prop, ParsedProperty):
            return str(prop)
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
