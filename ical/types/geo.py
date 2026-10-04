"""Library for parsing and encoding GEO values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ical.parsing.property import ParsedProperty
from .data_types import DATA_TYPE, EncodedJcalValue
from .text import TextEncoder


@DATA_TYPE.register("GEO")
@dataclass
class Geo:
    """Information related to the global position for an activity."""

    lat: float
    lng: float

    @classmethod
    def __parse_property_value__(cls, value: Any) -> Geo:
        """Parse a rfc5545 lat long geo values."""
        parts = TextEncoder.__parse_property_value__(value).split(";", 2)
        if len(parts) != 2:
            raise ValueError(f"Value was not valid geo lat;long: {value}")
        return Geo(lat=float(parts[0]), lng=float(parts[1]))

    @classmethod
    def __parse_jcal_value__(cls, value: Any, params: dict[str, Any]) -> Geo:
        """Parse an RFC 7265 jCal geo property."""
        if isinstance(value, Geo):
            return value
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return Geo(lat=float(value[0]), lng=float(value[1]))
        return cls.__parse_property_value__(value)

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if isinstance(value, Geo):
            return EncodedJcalValue({}, [[value.lat, value.lng]], type_name="float")
        return None

    @classmethod
    def __encode_property_json__(cls, value: Geo) -> str:
        """Serialize as an ICS value."""
        return f"{value.lat};{value.lng}"
