"""Implementation of the REQUEST-STATUS property."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional, Union

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE, _split_unescaped
from .text import TextEncoder

_STATCODE_RE = re.compile(r"^\d+(\.\d+){1,2}$")


@dataclass
@DATA_TYPE.register()
class RequestStatus:
    """Status code returned for a scheduling request."""

    statcode: Union[str, float]
    statdesc: str
    exdata: Optional[str] = None

    @classmethod
    def __parse_property_value__(cls, value: Any) -> RequestStatus:
        """Parse a rfc5545 request status value."""
        raw = value.value if isinstance(value, ParsedProperty) else str(value)
        parts = _split_unescaped(raw, ";")
        if len(parts) < 2 or len(parts) > 3:
            raise ValueError(f"Value was not valid Request Status: {value}")
        code_str = parts[0]
        if not _STATCODE_RE.fullmatch(code_str):
            raise ValueError(f"Invalid Request Status statcode: {code_str}")
        statcode: str | float
        if code_str.count(".") == 1 and str(float(code_str)) == code_str:
            statcode = float(code_str)
        else:
            statcode = code_str
        statdesc = TextEncoder.__parse_property_value__(
            ParsedProperty(name="request-status", value=parts[1])
        )
        exdata: str | None = None
        if len(parts) == 3:
            exdata = TextEncoder.__parse_property_value__(
                ParsedProperty(name="request-status", value=parts[2])
            )
        return RequestStatus(
            statcode=statcode,
            statdesc=statdesc,
            exdata=exdata,
        )

    @classmethod
    def __encode_property_json__(cls, value: RequestStatus) -> str:
        """Encoded RequestStatus as an ICS property."""
        statdesc = TextEncoder.__encode_property__(value.statdesc).value
        result = f"{value.statcode};{statdesc}"
        if value.exdata is not None:
            exdata = TextEncoder.__encode_property__(value.exdata).value
            result += f";{exdata}"
        return result
