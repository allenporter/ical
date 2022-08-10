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

A custom class with the method `__encode_property__` is used to serialize
the object as a ParsedProperty.
"""

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
from typing import Any, Generator, Optional, TypeVar, Union, get_args, get_origin
from urllib.parse import urlparse

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
        priority = parse_int(value)
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
        parts = parse_text(value).split(";", 2)
        if len(parts) != 2:
            raise ValueError(f"Value was not valid geo lat;long: {value}")
        return Geo(lat=float(parts[0]), lng=float(parts[1]))


def encode_geo_ics(value: Geo) -> str:
    """Serialize as an ICS value."""
    return f"{value.lat};{value.lng}"


def parse_parameter_values(cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Convert property parameters to member variables."""
    if params := values.get("params"):
        all_fields: dict[str, ModelField] = {}
        for model_field in cls.__fields__.values():
            all_fields[model_field.alias] = model_field
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


def encode_property_with_params(
    cls: BaseModel, name: str, model_data: dict[str, Any]
) -> ParsedProperty:
    """Encode a pydantic model as a property with parameters."""
    _LOGGER.debug("Encoding property with params %s: %s", name, model_data)
    prop = ParsedProperty(name=name, value=model_data.pop("value"))
    params = []
    for field in cls.__fields__.values():
        key = field.alias
        if (values := model_data.get(key)) is None:
            continue
        if field.shape != SHAPE_LIST:
            values = [values]
        if field.type_ == bool:
            values = [encode_boolean_ics(value) for value in values]
        params.append(ParsedPropertyParameter(name=key, values=values))
    if params:
        prop.params = params
    return prop


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

    __encode_property__ = encode_property_with_params

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
        parts = parse_text(value).split(";")
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


def encode_rstatus_ics(value: RequestStatus) -> str:
    """Encoded RequestStatus as an ICS property."""
    result = f"{value.statcode};{value.statdesc}"
    if value.exdata:
        result += f";{value.exdata}"
    return result


def parse_date(prop: ParsedProperty) -> datetime.date | None:
    """Parse a rfc5545 into a datetime.date."""
    if not (match := DATE_REGEX.fullmatch(prop.value)):
        raise ValueError(f"Expected value to match {DATE_PARAM} pattern: {prop.value}")
    date_value = match.group(1)
    year = int(date_value[0:4])
    month = int(date_value[4:6])
    day = int(date_value[6:])
    return datetime.date(year, month, day)


def encode_date_ics(value: datetime.date) -> str:
    """Serialize as an ICS value."""
    return value.strftime("%Y%m%d")


def parse_date_time(prop: ParsedProperty) -> datetime.datetime:
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

    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=timezone)


def encode_date_time_ics(value: datetime.datetime) -> str:
    """Serialize as an ICS value."""
    if value.tzinfo is None:
        return value.strftime("%Y%m%dT%H%M%S")
    # Does not yet handle timezones and encoding property parameters
    return value.strftime("%Y%m%dT%H%M%SZ")


def parse_duration(prop: ParsedProperty) -> datetime.timedelta:
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


def encode_duration_ics(value: Any) -> str:
    """Serialize a time delta as a DURATION ICS value."""
    if isinstance(value, str):
        return value  # Already encoded as ics
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
    return "".join(parts)


def parse_text(prop: Any) -> str:
    """Parse a rfc5545 into a text value."""
    if not isinstance(prop, ParsedProperty):
        return str(prop)
    for key, vin in UNESCAPE_CHAR.items():
        if key not in prop.value:
            continue
        prop.value = prop.value.replace(key, vin)
    return prop.value


def parse_enum(prop: ParsedProperty) -> str:
    """Parse a rfc5545 into a text value."""
    return prop.value


def encode_text(value: str) -> str:
    """Serialize text as an ICS value."""
    for key, vin in ESCAPE_CHAR.items():
        if key not in value:
            continue
        value = value.replace(key, vin)
    return value


def parse_int(prop: Any) -> int:
    """Parse a rfc5545 property into a text value."""
    if isinstance(prop, ParsedProperty):
        return int(prop.value)
    return int(prop)


def parse_float(prop: Any) -> float:
    """Parse a rfc5545 property into a text value."""
    if isinstance(prop, ParsedProperty):
        return float(prop.value)
    return float(prop)


def parse_boolean(prop: Any) -> bool:
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


def encode_boolean_ics(value: bool) -> str:
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
            start = parse_date_time(ParsedProperty(name="ignored", value=parts[0]))
        except ValueError as err:
            _LOGGER.debug("Failed to parse start date as date time: %s", parts[0])
            raise err
        values["start"] = start
        try:
            end = parse_date_time(ParsedProperty(name="ignored", value=parts[1]))
        except ValueError:
            pass
        else:
            values["end"] = end
            return values
        try:
            duration = parse_duration(ParsedProperty(name="ignored", value=parts[1]))
        except ValueError as err:
            raise err
        values["duration"] = duration
        return values

    def __encode_property__(
        cls, name: str, model_data: dict[str, Any]
    ) -> ParsedProperty:
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
            model_data["value"] = "/".join([start, end])
        else:
            model_data["value"] = "/".join([start, duration])
        return encode_property_with_params(cls, name, model_data)

    class Config:
        """Pyandtic model configuration."""

        allow_population_by_field_name = True


class Weekday(str, enum.Enum):
    """Corresponds to a day of the week."""

    SUNDAY = "SU"
    MONDAY = "MO"
    TUESDAY = "TU"
    WEDNESDAY = "WE"
    THURSDAY = "TH"
    FRIDAY = "FR"
    SATURDAY = "SA"


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

    by_week_day: list[Weekday] = Field(alias="byday", default_factory=list)
    """Supported days of the week."""

    by_month_day: list[int] = Field(alias="bymonthday", default_factory=list)
    """Days of the month between 1 to 31."""

    class Config:
        """Pydantic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True

    def __encode_property__(cls, name: str, values: dict[str, Any]) -> ParsedProperty:
        """Encode this object as a property."""
        return ParsedProperty(name, encode_recur_ics(values))


def parse_recur(prop: Any) -> dict[str, Any]:
    """Parse the recurrence rule text as a dictionary as Pydantic input.

    An input rule like 'FREQ=YEARLY;BYMONTH=4' is converted
    into dictionary.
    """
    if not isinstance(prop, ParsedProperty):
        raise ValueError(f"Expected recurrence rule as ParsedProperty: {prop}")
    result: dict[str, datetime.datetime | str | list[str]] = {}
    for part in prop.value.split(";"):
        if "=" not in part:
            raise ValueError(
                f"Recurrence rule had unexpected format missing '=': {prop.value}"
            )
        key, value = part.split("=")
        key = key.lower()
        if key == "until":
            result[key] = parse_date_time(ParsedProperty(name="ignored", value=value))
        elif key in ("byday", "bymonthday"):
            result[key] = value.split(",")
        else:
            result[key] = value
    return result


def encode_recur_ics(data: dict[str, Any]) -> str:
    """Encode the recurence rule in ICS format."""
    result = []
    for key, value in data.items():
        # Need to encode based on field type also using json encoders
        if key == "until":
            value = encode_date_time_ics(value)
        elif key in ("byday", "bymonthday"):
            if not value:
                continue
            value = ",".join([str(val) for val in value])
        result.append(f"{key.upper()}={value}")
    return ";".join(result)


def parse_extra_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty | ParsedComponent]]
) -> dict[str, Any]:
    """Parse extra fields not in the model."""
    all_fields = set()
    for field in cls.__fields__.values():
        if field.alias == "extras":
            continue
        all_fields |= {field.name, field.alias}
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


def encode_model(name: str, model: ComponentModel) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    model_data = json.loads(
        model.json(by_alias=True, exclude_none=True, exclude_defaults=True)
    )
    return encode_component(name, model, model_data)


# For additional decoding of properties after they have already
# been handled by the json encoder.
POST_JSON_ENCODERS: dict[Any, Callable[[Any], str]] = {
    datetime.timedelta: encode_duration_ics,
    bool: encode_boolean_ics,
    str: encode_text,
}


def encode_component(
    name: str, model: BaseModel, model_data: dict[str, Any]
) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    _LOGGER.debug("Encoding component %s: %s", name, model_data)
    parent = ParsedComponent(name=name)
    for field in model.__fields__.values():
        key = field.alias
        values = model_data.get(key)
        if values is None or key == "extras":
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if component_encoder := getattr(field.type_, "__encode_component__", None):
                parent.components.append(component_encoder(field.type_, key, value))
                continue
            if property_encoder := getattr(field.type_, "__encode_property__", None):
                parent.properties.append(property_encoder(field.type_, key, value))
                continue
            if value_encoder := POST_JSON_ENCODERS.get(field.type_):
                value = value_encoder(value)
            parent.properties.append(ParsedProperty(name=key, value=value))
    return parent


_T = TypeVar("_T")


class PropertyDataType(enum.Enum):
    """Strongly typed properties in rfc5545."""

    # Types to support
    #   BINARY
    #   PERIOD
    #   TIME
    BOOLEAN = ("BOOLEAN", bool, parse_boolean, encode_boolean_ics)
    CAL_ADDRESS = (
        "CAL-ADDRESS",
        CalAddress,
        dataclasses.asdict,
        dataclasses.asdict,
    )
    DATE = ("DATE", datetime.date, parse_date, encode_date_ics)
    DATE_TIME = ("DATE-TIME", datetime.datetime, parse_date_time, encode_date_time_ics)
    DURATION = ("DURATION", datetime.timedelta, parse_duration, encode_duration_ics)
    FLOAT = ("FLOAT", float, parse_float, str)
    INTEGER = ("INTEGER", int, parse_int, str)
    PERIOD = ("PERIOD", Period, dataclasses.asdict, dataclasses.asdict)
    # Note: Has special handling, not json encoder
    TEXT = ("TEXT", str, parse_text, encode_text)
    URI = ("URI", Uri, Uri.parse, str)
    RECUR = ("RECUR", Recur, parse_recur, encode_recur_ics)

    def __init__(
        self,
        name: str,
        data_type: Any,
        decode_fn: Callable[[_T], ParsedProperty],
        encode_fn: Callable[[ParsedProperty], _T],
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
    Geo: encode_geo_ics,
    RequestStatus: encode_rstatus_ics,
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


def _parse_identity(value: Any) -> Any:
    return value


def _get_validators(field_type: type) -> list[Callable[[Any], Any]]:
    """Return validators for the specified field."""
    origin = get_origin(field_type)
    if origin is Union:
        if not (args := get_args(field_type)):
            raise ValueError(f"Unable to determine args of type: {field_type}")
        # Decoder for any type in the union
        return list(filter(None, [ICS_DECODERS.get(arg) for arg in args]))
    # Decoder for single value
    if field_type in ICS_DECODERS:
        return [ICS_DECODERS[field_type]]
    return [_parse_identity]


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

    for validator in validators:
        try:
            return validator(prop)
        except ValueError as err:
            _LOGGER.debug("Failed to validate: %s", err)
    raise ValueError(f"Failed to validate: {prop}")


def parse_property_value(cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Parse individual property value fields."""
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


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    _parse_extra_fields = root_validator(pre=True, allow_reuse=True)(parse_extra_fields)
    _parse_property_value = root_validator(pre=True, allow_reuse=True)(
        parse_property_value
    )

    def __encode_component__(cls, name: str, values: dict[str, Any]) -> ParsedComponent:
        """Encode this object as a component."""
        return encode_component(name, cls, values)

    class Config:
        """Pyandtic model configuration."""

        validate_assignment = True
        allow_population_by_field_name = True
