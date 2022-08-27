"""Libraries for translating between rfc5545 parsed objects and pydantic data.

The data model returned by the contentlines parsing is a bag of ParsedProperty
objects that support all the flexibility of the rfc5545 spec. However in the
common case the spec has a lot more flexibility than is needed for handling
simple property types e.g. a single summary field that is specified only once.

This library helps reduce boilerplate for translating that complex structure
into the simpler pydantic data model, and handles custom field types and
validators.

Just as the pydantic model provides syntax glue for parsing data and
associating necessary validators, this is the same for the opposite
direction.

A custom class with the method `__encode_component__` is used to serialize
the object as a ParsedComponent.

A custom class with the optional methods `__encode_property_value__` and
`__encode_property_params__` are used to serialize the object as a
ParsedProperty.
"""

# pylint: disable=too-many-lines

from __future__ import annotations

import copy
import dataclasses
import datetime
import enum
import json
import logging
import re
import zoneinfo
from collections.abc import Callable
from typing import (
    Any,
    Generator,
    Iterable,
    Optional,
    TypeVar,
    Union,
    get_args,
    get_origin,
)
from urllib.parse import urlparse

from dateutil import rrule
from pydantic import BaseModel, Field, root_validator
from pydantic.dataclasses import dataclass
from pydantic.fields import SHAPE_LIST, ModelField

from .parsing.component import ParsedComponent
from .parsing.property import ParsedProperty, ParsedPropertyParameter

_LOGGER = logging.getLogger(__name__)


DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
DATE_REGEX = re.compile(r"^([0-9]{8})$")
DATE_PARAM = "DATE"

DATE_PART = r"(\d+)D"
TIME_PART = r"T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
DATETIME_PART = f"(?:{DATE_PART})?(?:{TIME_PART})?"
WEEKS_PART = r"(\d+)W"
DURATION_REGEX = re.compile(f"([-+]?)P(?:{WEEKS_PART}|{DATETIME_PART})$")
UTC_OFFSET_REGEX = re.compile(r"^([-+]?)([0-9]{2})([0-9]{2})$")
WEEKDAY_REGEX = re.compile(r"([-+]?[0-9]*)([A-Z]+)")

UNESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}
ESCAPE_CHAR = {v: k for k, v in UNESCAPE_CHAR.items()}


# This is a property parameter, currently used by the DATE-TIME type. It
# should probably be composed in the property or in a separate file of
# property parameters.
TZID = "TZID"
ATTR_VALUE = "VALUE"

# Repeated values can either be specified as multiple separate values, but
# also some values support repeated values within a single value with a
# comma delimiter, listed here.
ALLOW_REPEATED_VALUES = {
    "categories",
    "classification",
    "exdate",
    "rdate",
    "resources",
    "freebusy",
}


class EventStatus(str, enum.Enum):
    """Status or confirmation of the event."""

    CONFIRMED = "CONFIRMED"
    TENTATIVE = "TENTATIVE"
    CANCELLED = "CANCELLED"


class TodoStatus(str, enum.Enum):
    """Status or confirmation of the to-do."""

    NEEDS_ACTION = "NEEDS-ACTION"
    COMPLETED = "COMPLETED"
    IN_PROCESS = "IN-PROCESS"
    CANCELLED = "CANCELLED"


class JournalStatus(str, enum.Enum):
    """Status or confirmation of the journal entry."""

    DRAFT = "DRAFT"
    FINAL = "FINAL"
    CANCELLED = "CANCELLED"


class Classification(str, enum.Enum):
    """Defines the access classification for a calendar component."""

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"


class Priority(int):
    """Defines relative priority for a calendar component."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_priority

    @classmethod
    def parse_priority(cls, value: Any) -> int:
        """Parse a rfc5545 into a text value."""
        priority = IntEncoder.parse_int(value)
        if priority < 0 or priority > 9:
            raise ValueError("Expected priority between 0-9")
        return priority


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


def _all_fields(cls: BaseModel) -> dict[str, ModelField]:
    all_fields: dict[str, ModelField] = {}
    for model_field in cls.__fields__.values():
        all_fields[model_field.name] = model_field
        all_fields[model_field.alias] = model_field
    return all_fields


def parse_parameter_values(cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Convert property parameters to member variables."""
    if params := values.get("params"):
        all_fields = _all_fields(cls)
        for param in params:
            if not (field := all_fields.get(param["name"])):
                continue
            if field.shape == SHAPE_LIST:
                values[param["name"]] = param["values"]
            else:
                if len(param["values"]) > 1:
                    raise ValueError("Unexpected repeated property parameter")
                values[param["name"]] = param["values"][0]
    return values


class Uri(str):
    """A value type for a property that contains a uniform resource identifier."""

    @classmethod
    def parse(cls, prop: ParsedProperty) -> Uri:
        """Parse a calendar user address."""
        urlparse(prop.value)
        return Uri(prop.value)


def encode_property_params(
    fields: Iterable[ModelField], model_data: dict[str, Any]
) -> list[ParsedPropertyParameter]:
    """Encode a pydantic model's parameters."""
    params = []
    for field in fields:
        key = field.alias
        if key == "value" or (values := model_data.get(key)) is None:
            continue
        if field.shape != SHAPE_LIST:
            values = [values]
        if field.type_ == bool:
            values = [
                BooleanEncoder.__encode_property_value__(value) for value in values
            ]
        params.append(ParsedPropertyParameter(name=key, values=values))
    return params


class CalendarUserType(str, enum.Enum):
    """The type of calendar user."""

    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    RESOURCE = "GROUP"
    ROOM = "ROOM"
    UNKNOWN = "UNKNOWN"


class ParticipationStatus(str, enum.Enum):
    """Participation status for a calendar user."""

    NEEDS_ACTION = "NEEDS-ACTION"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    # Additional statuses for Events and Todos
    TENTATIVE = "TENTATIVE"
    DELEGATED = "DELEGATED"
    # Additional status for TODOs
    COMPLETED = "COMPLETED"


class Role(str, enum.Enum):
    """Role for the calendar user."""

    CHAIR = "CHAIR"
    REQUIRED = "REQ-PARTICIPANT"
    OPTIONAL = "OPT-PARTICIPANT"
    NON_PARTICIPANT = "NON-PARTICIPANT"


class CalAddress(BaseModel):
    """A value type for a property that contains a calendar user address.

    This is a subclass of string so that it can be used in place of a string
    to get the calendar address, but also supports additional properties.
    """

    uri: Uri = Field(alias="value")
    """The calendar user address as a uri."""

    common_name: Optional[str] = Field(alias="CN", default=None)
    """The common name associated with the calendar user."""

    user_type: Optional[str] = Field(alias="CUTYPE", default=None)
    """The type of calendar user specified by the property.

    Common values are defined in CalendarUserType, though also supports other
    values not known by this library so it uses a string.
    """

    delegator: Optional[list[Uri]] = Field(alias="DELEGATED-FROM", default=None)
    """The users that have delegated their participation to this user."""

    delegate: Optional[list[Uri]] = Field(alias="DELEGATED-TO", default=None)
    """The users to whom the user has delegated participation."""

    directory_entry: Optional[Uri] = Field(alias="DIR", default=None)
    """Reference to a directory entry associated with the calendar user."""

    member: Optional[list[Uri]] = Field(alias="MEMBER", default=None)
    """The group or list membership of the calendar user."""

    status: Optional[str] = Field(alias="PARTSTAT", default=None)
    """The participation status for the calendar user."""

    role: Optional[str] = Field(alias="ROLE", default=None)
    """The participation role for the calendar user."""

    rsvp: Optional[bool] = Field(alias="RSVP", default=None)
    """Whether there is an expectation of a favor of a reply from the calendar user."""

    sent_by: Optional[Uri] = Field(alias="SENT-BY", default=None)
    """Specifies the calendar user is acting on behalf of another user."""

    language: Optional[str] = Field(alias="LANGUAGE", default=None)

    _parse_parameter_values = root_validator(pre=True, allow_reuse=True)(
        parse_parameter_values
    )

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, str]) -> str | None:
        return model_data.pop("value")

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        return encode_property_params(cls.__fields__.values(), model_data)

    class Config:
        """Pyandtic model configuration."""

        allow_population_by_field_name = True


@dataclass
class RequestStatus:
    """Status code returned for a scheduling request."""

    statcode: float
    statdesc: str
    exdata: Optional[str] = None

    @classmethod
    def parse_rstatus(cls, value: Any) -> RequestStatus:
        """Parse a rfc5545 request status value."""
        parts = TextEncoder.parse_text(value).split(";")
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
    def __encode_property_json__(cls, value: RequestStatus) -> str:
        """Encoded RequestStatus as an ICS property."""
        result = f"{value.statcode};{value.statdesc}"
        if value.exdata:
            result += f";{value.exdata}"
        return result


class DateEncoder:
    """Encode and decode an rfc5545 DATE and datetime.date."""

    @classmethod
    def parse_date(cls, prop: ParsedProperty) -> datetime.date | None:
        """Parse a rfc5545 into a datetime.date."""
        if not (match := DATE_REGEX.fullmatch(prop.value)):
            raise ValueError(
                f"Expected value to match {DATE_PARAM} pattern: {prop.value}"
            )
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        return datetime.date(year, month, day)

    @classmethod
    def __encode_property_json__(cls, value: datetime.date) -> str:
        """Serialize as an ICS value."""
        return value.strftime("%Y%m%d")


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
    def __encode_property_json__(cls, value: datetime.datetime) -> str | dict[str, Any]:
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


class DurationEncoder:
    """Class that can encode DURATION values."""

    @classmethod
    def parse_duration(cls, prop: ParsedProperty) -> datetime.timedelta:
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
    def __encode_property_json__(cls, value: Any) -> str:
        """Serialize a time delta as a DURATION ICS value."""
        duration: datetime.timedelta
        if isinstance(value, datetime.timedelta):
            duration = value
        elif isinstance(value, float):
            duration = datetime.timedelta(seconds=value)
        else:
            raise ValueError(f"Unexpected value type: {value}")
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
        _LOGGER.debug("__encode_property_json__=%s", parts)
        return "".join(parts)


def parse_enum(prop: ParsedProperty) -> str:
    """Parse a rfc5545 into a text value."""
    return prop.value


class TextEncoder:
    """Encode an rfc5545 TEXT value."""

    @classmethod
    def parse_text(cls, prop: Any) -> str:
        """Parse a rfc5545 into a text value."""
        if not isinstance(prop, ParsedProperty):
            return str(prop)
        for key, vin in UNESCAPE_CHAR.items():
            if key not in prop.value:
                continue
            prop.value = prop.value.replace(key, vin)
        return prop.value

    @classmethod
    def __encode_property_value__(cls, value: str) -> str:
        """Serialize text as an ICS value."""
        for key, vin in ESCAPE_CHAR.items():
            if key not in value:
                continue
            value = value.replace(key, vin)
        return value


class IntEncoder:
    """Encode an int ICS value."""

    @classmethod
    def parse_int(cls, prop: Any) -> int:
        """Parse a rfc5545 int value."""
        if isinstance(prop, ParsedProperty):
            return int(prop.value)
        return int(prop)


class FloatEncoder:
    """Encode a float ICS value."""

    @classmethod
    def parse_float(cls, prop: Any) -> float:
        """Parse a rfc5545 property into a text value."""
        if isinstance(prop, ParsedProperty):
            return float(prop.value)
        return float(prop)


class BooleanEncoder:
    """Encode a boolean ICS value."""

    @classmethod
    def parse_boolean(cls, prop: Any) -> bool:
        """Parse an rfc5545 property into a boolean."""
        if isinstance(prop, bool):
            return prop
        value = prop
        if isinstance(prop, ParsedProperty):
            value = prop.value
        if value == "TRUE":
            return True
        if value == "FALSE":
            return False
        raise ValueError(f"Unable to parse value as boolean: {prop}")

    @classmethod
    def __encode_property_value__(cls, value: bool) -> str:
        """Serialize boolean as an ICS value."""
        return "TRUE" if value else "FALSE"


class FreeBusyType(str, enum.Enum):
    """Specifies the free/busy time type."""

    FREE = "FREE"
    """The time interval is free for scheduling."""

    BUSY = "BUSY"
    """One or more events have been scheduled for the interval."""

    BUSY_UNAVAILABLE = "BUSY-UNAVAILABLE"
    """The interval can not be scheduled."""

    BUSY_TENTATIVE = "BUSY-TENTATIVE"
    """One or more events have been tentatively scheduled for the interval."""


class Period(BaseModel):
    """A value with a precise period of time."""

    start: datetime.datetime
    """Start of the period of time."""

    end: Optional[datetime.datetime] = None
    """End of the period of the time (duration is implicit)."""

    duration: Optional[datetime.timedelta] = None
    """Duration of the period of time (end time is implicit)."""

    # Context specific property parameters
    free_busy_type: Optional[FreeBusyType] = Field(alias="FBTYPE", default=None)
    """Specifies the free or busy time type."""

    _parse_parameter_values = root_validator(pre=True, allow_reuse=True)(
        parse_parameter_values
    )

    @property
    def end_value(self) -> datetime.datetime:
        """A computed end value based on either or duration."""
        if self.end:
            return self.end
        if not self.duration:
            raise ValueError("Invalid period missing both end and duration")
        return self.start + self.duration

    @root_validator(pre=True, allow_reuse=True)
    def parse_period_fields(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse a rfc5545 prioriry value."""
        if not (value := values.pop("value", None)):
            return values
        parts = value.split("/")
        if len(parts) != 2:
            raise ValueError(f"Period did not have two time values: {value}")
        try:
            start = DateTimeEncoder.parse_datetime(
                ParsedProperty(name="ignored", value=parts[0])
            )
        except ValueError as err:
            _LOGGER.debug("Failed to parse start date as date time: %s", parts[0])
            raise err
        values["start"] = start
        try:
            end = DateTimeEncoder.parse_datetime(
                ParsedProperty(name="ignored", value=parts[1])
            )
        except ValueError:
            pass
        else:
            values["end"] = end
            return values
        try:
            duration = DurationEncoder.parse_duration(
                ParsedProperty(name="ignored", value=parts[1])
            )
        except ValueError as err:
            raise err
        values["duration"] = duration
        return values

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, Any]) -> str:
        """Encode property value."""
        if not (start := model_data.pop("start", None)):
            raise ValueError(f"Invalid period object missing start: {model_data}")
        end = model_data.pop("end", None)
        duration = model_data.pop("duration", None)
        if not end and not duration:
            raise ValueError(
                f"Invalid period missing both end and duration: {model_data}"
            )
        # End and duration are already encoded values
        if end:
            return "/".join([start, end])
        return "/".join([start, duration])

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        return encode_property_params(
            cls.__fields__.values(),
            {
                k: v
                for k, v in model_data.items()
                if k not in ("end", "duration", "start")
            },
        )

    class Config:
        """Pyandtic model configuration."""

        allow_population_by_field_name = True


@dataclass
class UtcOffset:
    """Contains an offset from UTC to local time."""

    offset: datetime.timedelta

    @classmethod
    def parse_utc_offset(cls, prop: Any) -> UtcOffset:
        """Parse a UTC Offset."""
        if isinstance(prop, UtcOffset):
            return prop
        value = prop
        if isinstance(prop, ParsedProperty):
            value = prop.value
        if not (match := UTC_OFFSET_REGEX.fullmatch(value)):
            raise ValueError(f"Expected value to match UTC-OFFSET pattern: {value}")
        sign, hours, minutes = match.groups()
        result = datetime.timedelta(
            hours=int(hours or 0),
            minutes=int(minutes or 0),
        )
        if sign == "-":
            result = -result
        return UtcOffset(result)

    @classmethod
    def __encode_property_json__(cls, value: Any) -> str:
        """Serialize a time delta as a UTC-OFFSET ICS value."""
        if isinstance(value, str):
            return value  # Already encoded as ics
        duration: datetime.timedelta
        if isinstance(value, UtcOffset):
            duration = value.offset
        else:
            raise ValueError(f"Unexpected UTC OFFSET value type: {value}")
        parts = []
        if duration < datetime.timedelta(days=0):
            parts.append("-")
            duration = -duration
        seconds = duration.seconds
        hours = int(seconds / 3600)
        seconds %= 3600
        parts.append(f"{hours:02}")
        minutes = int(seconds / 60)
        seconds %= 60
        parts.append(f"{minutes:02}")
        return "".join(parts)


class Weekday(str, enum.Enum):
    """Corresponds to a day of the week."""

    SUNDAY = "SU"
    MONDAY = "MO"
    TUESDAY = "TU"
    WEDNESDAY = "WE"
    THURSDAY = "TH"
    FRIDAY = "FR"
    SATURDAY = "SA"


@dataclass
class WeekdayValue:
    """Holds a weekday value and optional occurrence value."""

    weekday: Weekday
    """Day of the week value."""

    occurrence: Optional[int] = None
    """The occurrence value indicates the nth occurrence.

    Indicates the nth occurrence of a specific day within the MONTHLY or
    YEARLY "RRULE". For example +1 represents the first Monday of the
    month, or -1 represents the last Monday of the month.
    """


class Frequency(str, enum.Enum):
    """Type of recurrence rule.

    Frequencies SECONDLY, MINUTELY, HOURLY, YEARLY are not supported.
    """

    DAILY = "DAILY"
    """Repeating events based on an interval of a day or more."""

    WEEKLY = "WEEKLY"
    """Repeating events based on an interval of a week or more."""

    MONTHLY = "MONTHLY"
    """Repeating events based on an interval of a month or more."""

    YEARLY = "YEARLY"
    """Repeating events based on an interval of a year or more."""


RRULE_FREQ = {
    Frequency.DAILY: rrule.DAILY,
    Frequency.WEEKLY: rrule.WEEKLY,
    Frequency.MONTHLY: rrule.MONTHLY,
    Frequency.YEARLY: rrule.YEARLY,
}
RRULE_WEEKDAY = {
    Weekday.MONDAY: rrule.MO,
    Weekday.TUESDAY: rrule.TU,
    Weekday.WEDNESDAY: rrule.WE,
    Weekday.THURSDAY: rrule.TH,
    Weekday.FRIDAY: rrule.FR,
    Weekday.SATURDAY: rrule.SA,
    Weekday.SUNDAY: rrule.SU,
}


class Recur(BaseModel):
    """A type used to identify properties that contain a recurrence rule specification.

    The by properties reduce or limit the number of occurrences generated. Only by day
    of the week and by month day are supported.

    Parts of rfc5545 recurrence spec not supported:
      By second, minute, hour
      By yearday, weekno, month
      Wkst rules are
      Bysetpos rules
      Negative "by" rules.
    """

    freq: Frequency

    until: Union[datetime.datetime, datetime.date, None] = None
    """The inclusive end date of the recurrence, or the last instance."""

    count: Optional[int] = None
    """The number of occurrences to bound the recurrence."""

    interval: int = 1
    """Interval at which the recurrence rule repeats."""

    by_weekday: list[WeekdayValue] = Field(alias="byday", default_factory=list)
    """Supported days of the week."""

    by_month_day: list[int] = Field(alias="bymonthday", default_factory=list)
    """Days of the month between 1 to 31."""

    by_month: list[int] = Field(alias="bymonth", default_factory=list)
    """Month number between 1 and 12."""

    def as_rrule(self, dtstart: datetime.datetime | datetime.date) -> rrule.rrule:
        """Create a dateutil rrule for the specified event."""
        if (freq := RRULE_FREQ.get(self.freq)) is None:
            raise ValueError(f"Unsupported frequency in rrule: {self.freq}")

        byweekday: list[rrule.weekday] | None = None
        if self.by_weekday:
            byweekday = [
                RRULE_WEEKDAY[weekday.weekday](
                    1 if weekday.occurrence is None else weekday.occurrence
                )
                for weekday in self.by_weekday
            ]
        return rrule.rrule(
            freq=freq,
            dtstart=dtstart,
            interval=self.interval,
            count=self.count,
            until=self.until,
            byweekday=byweekday,
            bymonthday=self.by_month_day if self.by_month_day else None,
            bymonth=self.by_month if self.by_month else None,
            cache=True,
        )

    class Config:
        """Pydantic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True

    @classmethod
    def __encode_property_value__(cls, data: dict[str, Any]) -> str:
        """Encode the recurence rule in ICS format."""
        result = []
        for key, value in data.items():
            # Need to encode based on field type also using json encoders
            if key in ("bymonthday", "bymonth"):
                if not value:
                    continue
                value = ",".join([str(val) for val in value])
            elif key == "byday":
                values = []
                for weekday_dict in value:
                    weekday = weekday_dict["weekday"]
                    occurrence = weekday_dict.get("occurrence")
                    if occurrence is None:
                        occurrence = ""
                    values.append(f"{occurrence}{weekday}")
                value = ",".join(values)
            if not value:
                continue
            result.append(f"{key.upper()}={value}")
        return ";".join(result)

    @classmethod
    def parse_recur(cls, prop: Any) -> dict[str, Any]:
        """Parse the recurrence rule text as a dictionary as Pydantic input.

        An input rule like 'FREQ=YEARLY;BYMONTH=4' is converted
        into dictionary.
        """
        if isinstance(prop, str):
            value = prop
        elif not isinstance(prop, ParsedProperty):
            raise ValueError(f"Expected recurrence rule as ParsedProperty: {prop}")
        else:
            value = prop.value
        result: dict[
            str, datetime.datetime | str | list[str] | list[dict[str, str]]
        ] = {}
        for part in value.split(";"):
            if "=" not in part:
                raise ValueError(
                    f"Recurrence rule had unexpected format missing '=': {prop.value}"
                )
            key, value = part.split("=")
            key = key.lower()
            if key == "until":
                result[key] = DateTimeEncoder.parse_datetime(
                    ParsedProperty(name="ignored", value=value)
                )
            elif key in ("bymonthday", "bymonth"):
                result[key] = value.split(",")
            elif key == "byday":
                # Build inputs for WeekdayValue dataclass
                results: list[dict[str, str]] = []
                for value in value.split(","):
                    if not (match := WEEKDAY_REGEX.fullmatch(value)):
                        raise ValueError(
                            f"Expected value to match UTC-OFFSET pattern: {value}"
                        )
                    occurrence, weekday = match.groups()
                    weekday_result = {"weekday": weekday}
                    if occurrence:
                        weekday_result["occurrence"] = occurrence
                    results.append(weekday_result)
                result[key] = results
            else:
                result[key] = value
        return result


def validate_until_dtstart(_cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Verify the until time and dtstart are the same."""
    if (
        (rule := values.get("rrule"))
        and (until := rule.until)
        and (dtstart := values.get("dtstart"))
    ):
        if isinstance(dtstart, datetime.datetime) and isinstance(
            until, datetime.datetime
        ):
            if dtstart.tzinfo is None:
                if until.tzinfo is not None:
                    raise ValueError("DTSTART is date local but UNTIL was not")
            else:
                if until.utcoffset():
                    raise ValueError("DTSTART had UTC or local and UNTIL must be UTC")
        elif isinstance(dtstart, datetime.datetime) or isinstance(
            until, datetime.datetime
        ):
            raise ValueError("DTSTART and UNTIL must be the same value type")
    return values


# For additional decoding of properties after they have already
# been handled by the json encoder.
ENCODERS = {
    datetime.datetime: DateTimeEncoder,
    datetime.timedelta: DurationEncoder,
    bool: BooleanEncoder,
    str: TextEncoder,
}


_T = TypeVar("_T")


class PropertyDataType(enum.Enum):
    """Strongly typed properties in rfc5545."""

    # Types to support
    #   BINARY
    #   TIME
    BOOLEAN = (
        "BOOLEAN",
        bool,
        BooleanEncoder.parse_boolean,
        BooleanEncoder.__encode_property_value__,
    )
    CAL_ADDRESS = (
        "CAL-ADDRESS",
        CalAddress,
        dataclasses.asdict,
        None,  # Uses pydantic jason BaseModel encoder
    )
    DATE = (
        "DATE",
        datetime.date,
        DateEncoder.parse_date,
        DateEncoder.__encode_property_json__,
    )
    DATE_TIME = (
        "DATE-TIME",
        datetime.datetime,
        DateTimeEncoder.parse_datetime,
        DateTimeEncoder.__encode_property_json__,
    )
    UTC_OFFSET = (
        "UTC-OFFSET",
        UtcOffset,
        UtcOffset.parse_utc_offset,
        UtcOffset.__encode_property_json__,
    )
    DURATION = (
        "DURATION",
        datetime.timedelta,
        DurationEncoder.parse_duration,
        DurationEncoder.__encode_property_json__,
    )
    FLOAT = ("FLOAT", float, FloatEncoder.parse_float, str)
    INTEGER = ("INTEGER", int, IntEncoder.parse_int, str)
    PERIOD = (
        "PERIOD",
        Period,
        dataclasses.asdict,
        None,
    )  # Uses pydantic jason BaseModel encoder
    # Note: Has special handling, not json encoder
    TEXT = ("TEXT", str, TextEncoder.parse_text, None)  # Uses native encoder
    URI = ("URI", Uri, Uri.parse, str)
    RECUR = (
        "RECUR",
        Recur,
        Recur.parse_recur,
        None,
    )  # Uses pydantic json BaseModel encoder

    def __init__(
        self,
        name: str,
        data_type: Any,
        decode_fn: Callable[[_T], ParsedProperty],
        encode_fn: Callable[[ParsedProperty], _T] | None,
    ):
        self._name = name
        self._data_type = data_type
        self._decode_fn = decode_fn
        self._encode_fn = encode_fn

    @property
    def data_type_name(self) -> str:
        """Property value name from rfc5545."""
        return self._name

    @property
    def data_type(self) -> Any:
        """Python type that this property can handle."""
        return self._data_type

    def encode(self, value: ParsedProperty) -> Any:
        """Encode a parsed object into a string value."""
        if not self._encode_fn:
            raise ValueError(
                "Native type is never encoded using value-type json encoder"
            )
        return self._encode_fn(value)

    def decode(self, value: _T) -> Any:
        """Decode a property value into a parsed object."""
        return self._decode_fn(value)


VALUE_TYPES = {
    **{
        property_data_type.data_type_name: property_data_type
        for property_data_type in PropertyDataType
    },
}
ICS_ENCODERS: dict[Any, Callable[[Any], str]] = {
    **{
        property_data_type.data_type: property_data_type.encode
        for property_data_type in PropertyDataType
    },
    Geo: Geo.__encode_property_json__,
    RequestStatus: RequestStatus.__encode_property_json__,
}
ICS_DECODERS: dict[Any, Callable[[ParsedProperty], Any]] = {
    **{
        property_data_type.data_type: property_data_type.decode
        for property_data_type in PropertyDataType
    },
    Classification: parse_enum,
    EventStatus: parse_enum,
    TodoStatus: parse_enum,
    JournalStatus: parse_enum,
    Geo: Geo.parse_geo,
    RequestStatus: RequestStatus.parse_rstatus,
}


def _identity(value: Any) -> Any:
    return value


def _get_field_types(field_type: type) -> list[type]:
    """Return type to attempt for encoding/decoding based on the field type."""
    origin = get_origin(field_type)
    if origin is Union:
        if not (args := get_args(field_type)):
            raise ValueError(f"Unable to determine args of type: {field_type}")
        # Decoder for any type in the union
        return list(args)
    return [field_type]


def _get_validators(field_type: type) -> list[Callable[[Any], Any]]:
    """Return validators for the specified field."""
    field_types = _get_field_types(field_type)
    decoder_types = list(filter(None, [ICS_DECODERS.get(arg) for arg in field_types]))
    if not decoder_types:
        return [_identity]
    return decoder_types


def _validate_field(prop: Any, validators: list[Callable[[Any], Any]]) -> Any:
    """Return the validated field from the first validator that succeeds."""
    if not isinstance(prop, ParsedProperty):
        # Not from rfc5545 parser true so ignore
        raise ValueError(f"Expected ParsedProperty: {prop}")

    if value_type := prop.get_parameter_value(ATTR_VALUE):
        # Property parameter specified a very specific type
        if not (data_type := VALUE_TYPES.get(value_type)):
            # Consider graceful degradation instead in the future
            raise ValueError(
                f"Property parameter specified unsupported type: {value_type}"
            )
        return data_type.decode(prop)

    errors: list[str] = []
    for validate in validators:
        try:
            return validate(prop)
        except ValueError as err:
            _LOGGER.debug("Failed to validate: %s", err)
            errors.append(str(err))
    raise ValueError(f"Failed to validate: {prop}, errors: ({errors})")


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    @root_validator(pre=True, allow_reuse=True)
    def parse_extra_fields(
        cls, values: dict[str, list[ParsedProperty | ParsedComponent]]
    ) -> dict[str, Any]:
        """Parse extra fields not in the model."""
        all_fields = _all_fields(cls).keys()
        extras: list[ParsedProperty | ParsedComponent] = []
        for (field_name, value) in values.items():
            if field_name in all_fields:
                continue
            for prop in value:
                if isinstance(prop, ParsedProperty):
                    extras.append(prop)
        if extras:
            values["extras"] = extras
        return values

    @root_validator(pre=True, allow_reuse=True)
    def parse_property_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse individual ParsedProperty value fields."""
        _LOGGER.debug("Parsing value data %s", values)

        for field in cls.__fields__.values():
            if field.alias == "extras":
                continue
            if not (value := values.get(field.alias)):
                continue
            if not (isinstance(value, list) and isinstance(value[0], ParsedProperty)):
                # The incoming value is not from the parse tree
                continue
            validators = _get_validators(field.type_)
            validated = []
            for prop in value:
                # This property value may contain repeated values itself
                if field.alias in ALLOW_REPEATED_VALUES and "," in prop.value:
                    for sub_value in prop.value.split(","):
                        sub_prop = copy.deepcopy(prop)
                        sub_prop.value = sub_value
                        validated.append(_validate_field(sub_prop, validators))
                else:
                    validated.append(_validate_field(prop, validators))

            if field.shape == SHAPE_LIST:
                values[field.alias] = validated
            elif len(validated) > 1:
                raise ValueError(f"Expected one value for field: {field.alias}")
            else:
                # Collapse repeated value from the parse tree into a single value
                values[field.alias] = validated[0]

        return values

    def __encode_component_root__(self) -> ParsedComponent:
        """Encode the calendar stream as an rfc5545 iCalendar content."""
        # The overall data model hierarchy is created by pydantic and properties
        # are encoded by default with ICS_ENCODERS then loaded back into a dict
        # with string values. Then there are additional passes to get the data in
        # the right shape for ics encoding.
        model_data = json.loads(
            self.json(by_alias=True, exclude_none=True, exclude_defaults=True)
        )
        # The component name is ignored as we're really only encoding children components
        return self.__encode_component__(self.__class__.__name__, model_data)

    @classmethod
    def __encode_component__(
        cls, name: str, model_data: dict[str, Any]
    ) -> ParsedComponent:
        """Encode this object as a component to prepare for serialization.

        The data passed in have already been encoded with one pass from the root json
        encoder. This method takes additional passes to add more field specific encoding,
        as well as overall component objects.
        """
        parent = ParsedComponent(name=name)
        for field in cls.__fields__.values():
            key = field.alias
            values = model_data.get(key)
            if values is None or key == "extras":
                continue
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if component_encoder := getattr(
                    field.type_, "__encode_component__", None
                ):
                    parent.components.append(component_encoder(key, value))
                    continue
                if prop := cls._encode_property(key, field.type_, value):
                    parent.properties.append(prop)
        return parent

    @classmethod
    def _encode_property(
        cls, key: str, field_type: type, value: Any
    ) -> ParsedProperty | None:
        """Encode an individual property for the specified field."""
        # A property field may have multiple possible types, like for
        # a Union. The field type itself may be responsible for
        # encoding, or there may be a separate class that knows
        # how to encode that type.
        encoder: type | None = None
        encoded_value: str | None = None
        for sub_type in _get_field_types(field_type):
            encoder = ENCODERS.get(sub_type, field_type)
            value_encoder = getattr(encoder, "__encode_property_value__", _identity)
            try:
                encoded_value = value_encoder(value)
            except ValueError as err:
                _LOGGER.debug("Encoding failed for property: %s", err)
                continue
            break

        if encoder and encoded_value is not None:
            prop = ParsedProperty(name=key, value=encoded_value)
            if params_encoder := getattr(encoder, "__encode_property_params__", None):
                if params := params_encoder(value):
                    prop.params = params
            return prop

        return None

    class Config:
        """Pyandtic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True
