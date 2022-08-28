"""Library for parsing and encoding DURATION values."""

import datetime
import re

from ical.parsing.property import ParsedProperty

from .data_types import DATA_TYPE

DATE_PART = r"(\d+)D"
TIME_PART = r"T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
DATETIME_PART = f"(?:{DATE_PART})?(?:{TIME_PART})?"
WEEKS_PART = r"(\d+)W"
DURATION_REGEX = re.compile(f"([-+]?)P(?:{WEEKS_PART}|{DATETIME_PART})$")


@DATA_TYPE.register("DURATION")
class DurationEncoder:
    """Class that can encode DURATION values."""

    @classmethod
    def __property_type__(cls) -> type:
        return datetime.timedelta

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> datetime.timedelta:
        """Parse a rfc5545 into a datetime.date."""
        if not isinstance(prop, ParsedProperty):
            raise ValueError(f"Expected ParsedProperty but was {prop}")
        if not (match := DURATION_REGEX.fullmatch(prop.value)):
            raise ValueError(f"Expected value to match DURATION pattern: {prop.value}")
        sign, weeks, days, hours, minutes, seconds = match.groups()
        result: datetime.timedelta
        if weeks:
            result = datetime.timedelta(weeks=int(weeks))
        else:
            result = datetime.timedelta(
                days=int(days or 0),
                hours=int(hours or 0),
                minutes=int(minutes or 0),
                seconds=int(seconds or 0),
            )
        if sign == "-":
            result = -result
        return result

    @classmethod
    def __encode_property_json__(cls, duration: datetime.timedelta) -> str:
        """Serialize a time delta as a DURATION ICS value."""
        parts = []
        if duration < datetime.timedelta(days=0):
            parts.append("-")
            duration = -duration
        parts.append("P")
        days = duration.days
        weeks = int(days / 7)
        days %= 7
        if weeks > 0:
            parts.append(f"{weeks}W")
        if days > 0:
            parts.append(f"{days}D")
        if duration.seconds != 0:
            parts.append("T")
            seconds = duration.seconds
            hours = int(seconds / 3600)
            seconds %= 3600
            if hours != 0:
                parts.append(f"{hours}H")
            minutes = int(seconds / 60)
            seconds %= 60
            if minutes != 0:
                parts.append(f"{minutes}M")
            if seconds != 0:
                parts.append(f"{seconds}S")
        return "".join(parts)
