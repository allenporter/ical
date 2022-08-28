"""Implementation of the REQUEST-STATUS property."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .data_types import DATA_TYPE
from .text import TextEncoder


@dataclass
@DATA_TYPE.register()
class RequestStatus:
    """Status code returned for a scheduling request."""

    statcode: float
    statdesc: str
    exdata: Optional[str] = None

    @classmethod
    def __parse_property_value__(cls, value: Any) -> RequestStatus:
        """Parse a rfc5545 request status value."""
        parts = TextEncoder.__parse_property_value__(value).split(";")
        if len(parts) < 2 or len(parts) > 3:
            raise ValueError(f"Value was not valid Request Status: {value}")
        exdata: str | None = None
        if len(parts) == 3:
            exdata = parts[2]
        return RequestStatus(
            statcode=float(parts[0]),
            statdesc=parts[1],
            exdata=exdata,
        )

    @classmethod
    def __encode_property_json__(cls, value: RequestStatus) -> str:
        """Encoded RequestStatus as an ICS property."""
        result = f"{value.statcode};{value.statdesc}"
        if value.exdata:
            result += f";{value.exdata}"
        return result
