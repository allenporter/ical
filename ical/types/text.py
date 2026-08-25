"""Library for parsing TEXT values."""

import re
from typing import Any

from ical.parsing.property import ParsedProperty, RE_CONTROL_CHARS

from .data_types import DATA_TYPE, EncodedJcalValue

_UNESCAPE_RE = re.compile(r"\\([\\;,Nn])")
_UNESCAPE_MAP = {
    "\\": "\\",
    ";": ";",
    ",": ",",
    "N": "\n",
    "n": "\n",
}
ESCAPE_CHAR = {
    "\\": "\\\\",
    ";": "\\;",
    ",": "\\,",
    "\n": "\\n",
}


@DATA_TYPE.register("TEXT")
class TextEncoder:
    """Encode an rfc5545 TEXT value."""

    @classmethod
    def __property_type__(cls) -> type:
        return str

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> str:
        """Parse a rfc5545 into a text value."""
        return _UNESCAPE_RE.sub(lambda m: _UNESCAPE_MAP[m.group(1)], prop.value)

    @classmethod
    def __parse_jcal_value__(cls, value: Any, params: dict[str, Any]) -> str:
        """Parse an RFC 7265 jCal text into a string."""
        return str(value)

    @classmethod
    def __encode_property__(cls, value: str) -> ParsedProperty:
        """Serialize text as an ICS value."""
        for key, vin in ESCAPE_CHAR.items():
            if key not in value:
                continue
            value = value.replace(key, vin)
        value = RE_CONTROL_CHARS.sub("", value)
        return ParsedProperty(name="", value=value)

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue:
        """Encode as jCal parameters and value list."""
        if isinstance(value, (list, tuple)):
            values = [v.value if hasattr(v, "value") else str(v) for v in value]
            return EncodedJcalValue({}, values)
        str_val = value.value if hasattr(value, "value") else str(value)
        return EncodedJcalValue({}, [str_val])
