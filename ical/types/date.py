"""Library for parsing and encoding DATE values."""

from __future__ import annotations

import datetime
import re

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE

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
        if not (match := DATE_REGEX.fullmatch(prop.value)):
            raise ValueError(f"Expected value to match DATE pattern: '{prop.value}'")
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        return datetime.date(year, month, day)

    @classmethod
    def __encode_property_json__(cls, value: datetime.date) -> str:
        """Serialize as an ICS value."""
        return value.strftime("%Y%m%d")
