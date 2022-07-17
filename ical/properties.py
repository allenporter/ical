"""Properties that can appear within various calendar components.

This file contains properties that may appear in multiple components.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Generator

PROPERTY_ALTREP = re.compile(r"ALTREP=\"([^\"]+)\"")

ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}


def unescape(value: str) -> str:
    """Escape human readable text items."""
    for key, vin in ESCAPE_CHAR.items():
        value = value.replace(key, vin)
    return value


class Description(str):
    """A calendar description."""

    @classmethod
    def __get_validators__(
        cls,
    ) -> Generator[Callable[[str], str], None, None]:
        yield cls.parse_description

    @classmethod
    def parse_description(cls, value: Any) -> str:
        """Parse a rfc5545 description into a str."""
        if not isinstance(value, str):
            raise TypeError(f"Expected description as string: {value}")
        if value_match := PROPERTY_ALTREP.match(value):
            # This currently strips the altrep property, but needs to be updated
            # to preserve it.
            # altrep = value_match.group(1)
            index = value_match.span()[1] + 1
            value = value[index:]
        return unescape(value)
