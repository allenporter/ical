"""Library for parsing and encoding DATE-TIME types."""

from __future__ import annotations

import datetime
import logging
import re
import zoneinfo
from typing import Any

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.tzif import timezoneinfo
from ical.exceptions import ParameterValueError
from .data_types import DATA_TYPE, EncodedJcalValue

_LOGGER = logging.getLogger(__name__)


DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
TZID = "TZID"
ATTR_VALUE = "VALUE"


def parse_property_value(
    prop: ParsedProperty, allow_invalid_timezone: bool = False
) -> datetime.datetime:
    """Parse a rfc5545 or ISO 8601 string into a datetime.datetime."""
    # Example: TZID=America/New_York:19980119T020000
    timezone: datetime.tzinfo | None = None
    if param := prop.get_parameter(TZID):
        if param.values and (value := param.values[0]):
            if isinstance(value, datetime.tzinfo):
                timezone = value
            else:
                try:
                    timezone = timezoneinfo.resolve_tzinfo(
                        value, allow_invalid=allow_invalid_timezone
                    )
                except timezoneinfo.TimezoneInfoError:
                    raise ParameterValueError(
                        f"Expected DATE-TIME TZID value '{value}' to be valid timezone"
                    )

    if isinstance(prop.value, datetime.datetime):
        return prop.value.replace(tzinfo=timezone) if timezone else prop.value

    if not (match := DATETIME_REGEX.fullmatch(prop.value)):
        raise ValueError(f"Expected value to match DATE-TIME pattern: {prop.value}")

    if not timezone and match.group(3):  # Example: 19980119T070000Z
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
    def __parse_jcal_value__(
        cls, value: Any, params: dict[str, Any]
    ) -> datetime.datetime:
        """Parse an RFC 7265 jCal date-time into a datetime.datetime."""
        if isinstance(value, datetime.datetime):
            return value
        if not isinstance(value, str):
            raise ValueError(f"Expected string for jCal date-time, got {type(value)}")

        timezone: datetime.tzinfo | None = None
        if tzid := params.get("tzid"):
            try:
                timezone = timezoneinfo.resolve_tzinfo(str(tzid), allow_invalid=False)
            except timezoneinfo.TimezoneInfoError as err:
                raise ParameterValueError(
                    f"Expected DATE-TIME TZID value '{tzid}' to be valid timezone"
                ) from err

        val = value
        if val.endswith("Z"):
            if timezone is None:
                timezone = datetime.timezone.utc
            val = val[:-1]

        try:
            dt = datetime.datetime.fromisoformat(val)
            if timezone is not None:
                dt = dt.replace(tzinfo=timezone)
            return dt
        except ValueError as err:
            raise ValueError(f"Invalid jCal date-time value: {value}") from err

    @classmethod
    def __encode_property_json__(cls, value: datetime.datetime) -> str | dict[str, str]:
        """Encode an ICS value during json serialization."""
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
    def __encode_property__(cls, value: str | dict[str, Any]) -> ParsedProperty | None:
        """Encode the ParsedProperty."""
        if isinstance(value, str):
            if "T" not in value:
                return None
            return ParsedProperty(name="", value=value)
        prop = ParsedProperty(name="", value=value[ATTR_VALUE])
        if tzid := value.get(TZID):
            prop.params = [ParsedPropertyParameter(name=TZID, values=[str(tzid)])]
        return prop

    @classmethod
    def __encode_jcal_value__(cls, value: Any) -> EncodedJcalValue | None:
        """Encode as jCal parameters and value list."""
        if not isinstance(value, datetime.datetime):
            return None
        if value.tzinfo is None:
            return EncodedJcalValue({}, [value.strftime("%Y-%m-%dT%H:%M:%S")])
        if not value.utcoffset():
            return EncodedJcalValue({}, [value.strftime("%Y-%m-%dT%H:%M:%SZ")])
        return EncodedJcalValue(
            {"tzid": str(value.tzinfo)}, [value.strftime("%Y-%m-%dT%H:%M:%S")]
        )
