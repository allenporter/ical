"""Library for parsing and encoding DATE-TIME types."""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from typing import Any

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

_LOGGER = logging.getLogger(__name__)


DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
TZID = "TZID"
ATTR_VALUE = "VALUE"


class DateTimeEncoder:
    """Class to handle encoding for a datetime.datetime."""

    @classmethod
    def parse_datetime(cls, prop: ParsedProperty) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        if not (match := DATETIME_REGEX.fullmatch(prop.value)):
            raise ValueError(f"Expected value to match DATE-TIME pattern: {prop.value}")

        # Example: TZID=America/New_York:19980119T020000
        timezone: datetime.tzinfo | None = None
        if tzid := prop.get_parameter_value(TZID):
            timezone = zoneinfo.ZoneInfo(tzid)
        elif match.group(3):  # Example: 19980119T070000Z
            timezone = datetime.timezone.utc

        # Example: 19980118T230000
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        time_value = match.group(2)
        hour = int(time_value[0:2])
        minute = int(time_value[2:4])
        second = int(time_value[4:6])

        return datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=timezone
        )

    @classmethod
    def __encode_property_json__(cls, value: datetime.datetime) -> str | dict[str, str]:
        """Encode an ICS value during json serializaton."""
        if value.tzinfo is None:
            return value.strftime("%Y%m%dT%H%M%S")
        # Does not yet handle timezones and encoding property parameters
        if not value.utcoffset():
            return value.strftime("%Y%m%dT%H%M%SZ")
        return {
            ATTR_VALUE: value.strftime("%Y%m%dT%H%M%S"),
            TZID: str(value.tzinfo),  # Timezone key
        }

    @classmethod
    def __encode_property_value__(cls, value: str | dict[str, Any]) -> str | None:
        """Encode the ParsedProperty value."""
        if isinstance(value, str):
            return value
        return value.get(ATTR_VALUE)

    @classmethod
    def __encode_property_params__(
        cls, value: str | dict[str, str]
    ) -> list[ParsedPropertyParameter]:
        """Encode parameters for the property value."""
        _LOGGER.debug("__encode_property_params__=%s", value)
        if isinstance(value, dict) and (tzid := value.get(TZID)):
            return [ParsedPropertyParameter(name=TZID, values=[tzid])]
        return []
