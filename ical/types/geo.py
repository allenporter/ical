"""Library for parsing and encoding GEO values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .text import TextEncoder


@dataclass
class Geo:
    """Information related tot he global position for an activity."""

    lat: float
    lng: float

    @classmethod
    def parse_geo(cls, value: Any) -> Geo:
        """Parse a rfc5545 lat long geo values."""
        parts = TextEncoder.parse_text(value).split(";", 2)
        if len(parts) != 2:
            raise ValueError(f"Value was not valid geo lat;long: {value}")
        return Geo(lat=float(parts[0]), lng=float(parts[1]))

    @classmethod
    def __encode_property_json__(cls, value: Geo) -> str:
        """Serialize as an ICS value."""
        return f"{value.lat};{value.lng}"
