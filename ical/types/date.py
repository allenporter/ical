"""Library for parsing and encoding DATE values."""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any
from ical.compat.date_compat import is_allow_invalid_dates_enabled

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .data_types import DATA_TYPE

_LOGGER = logging.getLogger(__name__)

DATE_REGEX = re.compile(r"^([0-9]{8})$")


@DATA_TYPE.register("DATE", parse_order=1)
class DateEncoder:
    """Encode and decode an rfc5545 DATE and datetime.date."""

    @classmethod
    def __property_type__(cls) -> type:
        return datetime.date

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> datetime.date | None:
        """Parse a rfc5545 into a datetime.date."""
        val = prop.value
        if len(val) > 8 and "T" in val:
            if is_allow_invalid_dates_enabled():
                _LOGGER.debug("Stripping time suffix from DATE value: %s", prop.value)
                val = val.split("T")[0]

        if not (match := DATE_REGEX.fullmatch(val)):
            raise ValueError(f"Expected value to match DATE pattern: '{prop.value}'")
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])

        result = datetime.date(year, month, day)
        _LOGGER.debug("DateEncoder returned %s", result)
        return result

    @classmethod
    def __encode_property_json__(cls, value: datetime.date) -> str:
        """Serialize as an ICS value."""
        return value.strftime("%Y%m%d")

    @classmethod
    def __encode_property__(cls, value: str | dict[str, Any]) -> ParsedProperty | None:
        """Encode the ParsedProperty."""
        if isinstance(value, str) and "T" not in value:
            return ParsedProperty(
                name="",
                value=value,
                params=[ParsedPropertyParameter(name="VALUE", values=["DATE"])],
            )
        return None
