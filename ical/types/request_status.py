"""Implementation of the REQUEST-STATUS property."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE, _split_unescaped
from .text import TextEncoder


@dataclass
@DATA_TYPE.register()
class RequestStatus:
    """Status code returned for a scheduling request."""

    statcode: float
    statdesc: str
    exdata: Optional[str] = None

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> RequestStatus:
        """Parse a rfc5545 request status value."""
        parts = _split_unescaped(prop.value, ";")
        if len(parts) < 2 or len(parts) > 3:
            raise ValueError(f"Value was not valid Request Status: {prop}")
        statdesc = TextEncoder.__parse_property_value__(
            ParsedProperty(name=prop.name, value=parts[1])
        )
        exdata: str | None = None
        if len(parts) == 3:
            exdata = TextEncoder.__parse_property_value__(
                ParsedProperty(name=prop.name, value=parts[2])
            )
        return RequestStatus(
            statcode=float(parts[0]),
            statdesc=statdesc,
            exdata=exdata,
        )

    @classmethod
    def __encode_property_json__(cls, value: RequestStatus) -> str:
        """Encoded RequestStatus as an ICS property."""
        statdesc = TextEncoder.__encode_property__(value.statdesc).value
        result = f"{value.statcode};{statdesc}"
        if value.exdata:
            exdata = TextEncoder.__encode_property__(value.exdata).value
            result += f";{exdata}"
        return result
