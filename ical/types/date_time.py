"""Library for parsing and encoding DATE-TIME types."""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from typing import Any

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.compat import timezone_compat
from ical.tzif import timezoneinfo
from .data_types import DATA_TYPE

_LOGGER = logging.getLogger(__name__)


DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
TZID = "TZID"
ATTR_VALUE = "VALUE"


def parse_property_value(
    prop: ParsedProperty, allow_invalid_timezone: bool = False
) -> datetime.datetime:
    """Parse a rfc5545 into a datetime.datetime."""
    if timezone_compat.is_allow_invalid_timezones_enabled():
        allow_invalid_timezone = True

    if not (match := DATETIME_REGEX.fullmatch(prop.value)):
        raise ValueError(f"Expected value to match DATE-TIME pattern: {prop.value}")

    # Example: TZID=America/New_York:19980119T020000
    timezone: datetime.tzinfo | None = None
    if param := prop.get_parameter(TZID):
        if param.values and (value := param.values[0]):
            if isinstance(value, datetime.tzinfo):
                timezone = value
            else:
                try:
                    timezone = zoneinfo.ZoneInfo(value)
                except zoneinfo.ZoneInfoNotFoundError:
                    try:
                        timezone = timezoneinfo.read_tzinfo(value)
                    except timezoneinfo.TimezoneInfoError:
                        if allow_invalid_timezone:
                            timezone = None
                        else:
                            raise ValueError(
                                f"Expected DATE-TIME TZID value '{value}' to be valid timezone"
                            )
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

    result = datetime.datetime(year, month, day, hour, minute, second, tzinfo=timezone)
    _LOGGER.debug("DateTimeEncoder returned %s", result)
    return result


@DATA_TYPE.register("DATE-TIME", parse_order=2)
class DateTimeEncoder:
    """Class to handle encoding for a datetime.datetime."""

    @classmethod
    def __property_type__(cls) -> type:
        return datetime.datetime

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        return parse_property_value(prop, allow_invalid_timezone=False)

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
        if isinstance(value, dict) and (tzid := value.get(TZID)):
            return [ParsedPropertyParameter(name=TZID, values=[str(tzid)])]
        return []
