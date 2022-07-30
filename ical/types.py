"""Libraries for translating between rfc5545 parsed objects and pydantic data.

The data model returned by the contentlines parsing is a bag of ParsedProperty
objects that support all the flexibility of the rfc5545 spec. However in the
common case the spec has a lot more flexibility than is needed for handling
simple property types e.g. a single summary field that is specified only once.

This library helps reduce boilerplate for translating that complex structure
into the simpler pydantic data model, and handles custom field types and
validators.
"""

from __future__ import annotations

import datetime
import enum
import json
import logging
import re
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generator, TypeVar, Union, get_args, get_origin
from urllib.parse import urlparse

from pydantic import BaseModel, root_validator
from pydantic.fields import SHAPE_LIST

from .contentlines import ParsedComponent, ParsedProperty

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
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_geo

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


class CalAddress(str):
    """A value type for a property that contains a calendar user address."""

    @classmethod
    def parse(cls, prop: ParsedProperty) -> CalAddress:
        """Parse a calendar user address."""
        urlparse(prop.value)
        return CalAddress(prop.value)


class Uri(str):
    """A value type for a property that contains a uniform resource identifier."""

    @classmethod
    def __get_valiators__(cls) -> Generator[Callable[[Any], Any], None, None]:
        yield cls.parse

    @classmethod
    def parse(cls, prop: ParsedProperty) -> Uri:
        """Parse a calendar user address."""
        urlparse(prop.value)
        return Uri(prop.value)


def parse_date(prop: ParsedProperty) -> datetime.date | None:
    """Parse a rfc5545 into a datetime.date."""
    value = prop.value
    if not (match := DATE_REGEX.fullmatch(value)):
        raise ValueError(f"Expected value to match {DATE_PARAM} pattern: {value}")
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
    if not isinstance(prop, ParsedProperty):
        raise ValueError(f"Expected ParsedProperty but was {prop}")
    value = prop.value
    if not (match := DATETIME_REGEX.fullmatch(value)):
        raise ValueError(f"Expected value to match DATE-TIME pattern: {value}")

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
    value = prop.value
    _LOGGER.info("parse_duration=%s", value)
    if not isinstance(prop, ParsedProperty):
        raise ValueError(f"Expected ParsedProperty but was {prop}")
    value = prop.value
    if not (match := DURATION_REGEX.fullmatch(value)):
        raise ValueError(f"Expected value to match DURATION pattern: {value}")
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
    if not isinstance(value, float):
        raise ValueError("Unexpected value type")
    duration = datetime.timedelta(seconds=value)
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


def parse_text(prop: ParsedProperty) -> str:
    """Parse a rfc5545 into a text value."""
    for key, vin in UNESCAPE_CHAR.items():
        if key not in prop.value:
            continue
        prop.value = prop.value.replace(key, vin)
    return prop.value


def encode_text(value: str) -> str:
    """Serialize text as an ICS value."""
    for key, vin in ESCAPE_CHAR.items():
        if key not in value:
            continue
        value = value.replace(key, vin)
    return value


def parse_int(prop: ParsedProperty) -> int:
    """Parse a rfc5545 property into a text value."""
    return int(prop.value)


def parse_boolean(prop: ParsedProperty) -> bool:
    """Parse an rfc5545 property into a boolean."""
    if prop.value == "TRUE":
        return True
    if prop.value == "FALSE":
        return False
    raise ValueError(f"Invalid boolean value: {prop.value}")


def encode_boolean_ics(value: bool) -> str:
    """Serialize boolean as an ICS value."""
    return "TRUE" if value else "FALSE"


def parse_extra_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty | ParsedComponent]]
) -> dict[str, Any]:
    """Parse extra fields not in the model."""
    all_fields = {
        field.alias for field in cls.__fields__.values() if field.alias != "extras"
    }
    extras: list[ParsedProperty | ParsedComponent] = []
    for (field_name, value) in values.items():
        if field_name in all_fields:
            continue
        for prop in value:
            if isinstance(prop, ParsedProperty):
                extras.append(prop)
    if extras:
        _LOGGER.debug("Parsing extra fields: %s", extras)
        values["extras"] = extras
    return values


def encode_model(name: str, model: BaseModel) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    model_data = json.loads(
        model.json(exclude_unset=True, by_alias=True, exclude_none=True)
    )
    return encode_component(name, model, model_data)


def encode_component(
    name: str, model: BaseModel, model_data: dict[str, Any]
) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    _LOGGER.debug("Encoding component %s: %s", name, model_data)
    parent = ParsedComponent(name=name)
    for field in model.__fields__.values():
        key = field.alias
        values = model_data.get(key)
        if not values or key == "extras":
            continue
        if isinstance(values, list):
            for value in values:
                if issubclass(field.type_, BaseModel):
                    parent.components.append(encode_component(key, field.type_, value))
                else:
                    if field.type_ == datetime.timedelta:
                        value = encode_duration_ics(value)
                    elif field.type_ == str:
                        value = encode_text(value)
                    parent.properties.append(ParsedProperty(name=key, value=value))
        elif get_origin(field.type_) is not Union and issubclass(
            field.type_, BaseModel
        ):
            parent.components.append(encode_component(key, field.type_, values))
        else:
            if field.type_ == datetime.timedelta:
                values = encode_duration_ics(values)
            elif field.type_ == str:
                values = encode_text(values)
            parent.properties.append(ParsedProperty(name=key, value=values))
    return parent


_T = TypeVar("_T")


class PropertyDataType(enum.Enum):
    """Strongly typed properties in rfc5545."""

    # Types to support
    #   BINARY
    #   FLOAT
    #   PERIOD
    #   RECUR
    #   TIME
    BOOLEAN = ("BOOLEAN", bool, parse_boolean, encode_boolean_ics)
    DURATION = ("DURATION", datetime.timedelta, parse_duration, encode_duration_ics)
    DATE = ("DATE", datetime.date, parse_date, encode_date_ics)
    DATE_TIME = ("DATE-TIME", datetime.datetime, parse_date_time, encode_date_time_ics)
    INTEGER = ("INTEGER", int, parse_int, str)
    # Note: Has special handling, not json encoder
    TEXT = ("TEXT", str, parse_text, encode_text)
    CAL_ADDRESS = ("CAL-ADDRESS", CalAddress, CalAddress.parse, str)
    URI = ("URI", Uri, Uri.parse, str)

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
}
ICS_DECODERS: dict[Any, Callable[[ParsedProperty], Any]] = {
    **{
        property_data_type.data_type: property_data_type.decode
        for property_data_type in PropertyDataType
    },
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


def _validate_field(value: Any, validators: list[Callable[[Any], Any]]) -> Any:
    """Return the validated field from the first validator that succeeds."""
    if not isinstance(value, ParsedProperty):
        # Not from rfc5545 parser true so ignore
        raise ValueError(f"Expected ParsedProperty: {value}")

    if value_type := value.get_parameter_value(ATTR_VALUE):
        # Property parameter specified a very specific type
        if not (data_type := VALUE_TYPES.get(value_type)):
            # Consider graceful degredation instead in the future
            raise ValueError(
                f"Property parameter specified unsupported type: {value_type}"
            )
        return data_type.decode(value)

    for validator in validators:
        try:
            return validator(value)
        except ValueError as err:
            _LOGGER.debug("Failed to validate: %s", err)
    raise ValueError(f"Failed to validate: {value}")


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
        if field.shape == SHAPE_LIST:
            _LOGGER.debug("Parsing repeated value with validators: %s", validators)
            values[field.alias] = [_validate_field(prop, validators) for prop in value]
        else:
            # Collapse repeated value from the parse tree into a single value
            if len(value) > 1:
                raise ValueError(f"Expected one value for field: {field.alias}")
            values[field.alias] = _validate_field(value[0], validators)

    return values


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    _parse_extra_fields = root_validator(pre=True, allow_reuse=True)(parse_extra_fields)
    _parse_property_value = root_validator(pre=True, allow_reuse=True)(
        parse_property_value
    )
