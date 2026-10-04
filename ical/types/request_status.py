"""Implementation of the REQUEST-STATUS property."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .data_types import DATA_TYPE, EncodedJcalValue
from .text import TextEncoder


@dataclass
@DATA_TYPE.register("REQUEST-STATUS")
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
    def __parse_jcal_value__(cls, value: Any, params: dict[str, Any]) -> RequestStatus:
        """Parse an RFC 7265 jCal request-status property."""
        if isinstance(value, RequestStatus):
            return value
        if isinstance(value, (list, tuple)):
            if len(value) < 2:
                raise ValueError(f"Invalid jCal request-status: {value}")
            return RequestStatus(
                statcode=float(value[0]),
                statdesc=str(value[1]),
                exdata=str(value[2]) if len(value) > 2 else None,
            )
        return cls.__parse_property_value__(value)

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if not isinstance(value, RequestStatus):
            return None
        parts = [f"{value.statcode}", value.statdesc]
        if value.exdata:
            parts.append(value.exdata)
        return EncodedJcalValue({}, [parts], type_name="text")

    @classmethod
    def __encode_property_json__(cls, value: RequestStatus) -> str:
        """Encoded RequestStatus as an ICS property."""
        result = f"{value.statcode};{value.statdesc}"
        if value.exdata:
            result += f";{value.exdata}"
        return result
