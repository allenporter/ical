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
import logging
import re
import zoneinfo
from collections.abc import Callable
from typing import Any, Generator, Union, get_args, get_origin

from pydantic import BaseModel, root_validator
from pydantic.fields import SHAPE_LIST

from .contentlines import ParsedComponent, ParsedProperty

_LOGGER = logging.getLogger(__name__)


DATETIME_REGEX = re.compile(r"^([0-9]{8})T([0-9]{6})(Z)?$")
DATE_REGEX = re.compile(r"^([0-9]{8})$")
DATE_PARAM = "DATE"
DATETIME_PARAM = "DATE-TIME"

PROPERTY_VALUE = re.compile(r"^VALUE=([^:]+):(.*)$")

ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}


# This is a property parameter, currently used by the DATE-TIME type. It
# should probably be composed in the property or in a separate file of
# property parameters.
TZID = "TZID"


class Date(datetime.date):
    """Parser for rfc5545 date."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_date

    @classmethod
    def parse_date(cls, prop: ParsedProperty) -> datetime.date | None:
        """Parse a rfc5545 into a datetime.date."""
        value = prop.value
        if not (match := DATE_REGEX.fullmatch(value)):
            raise ValueError(f"Expected value to match {DATE_PARAM} pattern: {value}")
        date_value = match.group(1)
        year = int(date_value[0:4])
        month = int(date_value[4:6])
        day = int(date_value[6:])
        return datetime.date(year, month, day)

    @staticmethod
    def ics(value: datetime.date) -> str:
        """Serialize as an ICS value."""
        return value.strftime("%Y%m%d")


class DateTime(datetime.datetime):
    """Parser for rfc5545 date times."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_date_time

    @classmethod
    def parse_date_time(cls, prop: ParsedProperty) -> datetime.datetime:
        """Parse a rfc5545 into a datetime.datetime."""
        value = prop.value
        if value_match := PROPERTY_VALUE.fullmatch(value):
            if value_match.group(1) != DATETIME_PARAM:
                raise TypeError(f"Expected VALUE={DATETIME_PARAM} value: {value}")
            value = value_match.group(2)
        if not (match := DATETIME_REGEX.fullmatch(value)):
            raise ValueError(
                f"Expected value to match {DATETIME_PARAM} pattern: {value}"
            )

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

    @staticmethod
    def ics(value: datetime.datetime) -> str:
        """Serialize as an ICS value."""
        if value.tzinfo is None:
            return value.strftime("%Y%m%dT%H%M%S")
        # Does not yet handle timezones and encoding property parameters
        return value.strftime("%Y%m%dT%H%M%SZ")


class Text(str):
    """A type that contains human readable text."""

    ESCAPE_CHAR = {"\\\\": "\\", "\\;": ";", "\\,": ",", "\\N": "\n", "\\n": "\n"}

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_text
        yield cls.unescape_text

    @classmethod
    def parse_text(cls, prop: ParsedProperty) -> str:
        """Parse a rfc5545 into a text value."""
        return prop.value

    @classmethod
    def unescape_text(cls, value: str) -> str:
        """Escape human readable text items."""
        for key, vin in Text.ESCAPE_CHAR.items():
            value = value.replace(key, vin)
        return value


class Integer(int):
    """A type that contains a signed integer value."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_int

    @classmethod
    def parse_int(cls, prop: ParsedProperty) -> int:
        """Parse a rfc5545 into a text value."""
        return int(prop.value)


def is_single_property(field_type: type) -> bool:
    """Return true if pydantic field typing indicates a single value property."""
    origin = get_origin(field_type)
    if origin is Union:
        args = get_args(field_type)
        if args and args[0] is not list:
            return True
        return False

    if origin is not list:
        return True
    return False


def _parse_single_property(props: list[ParsedProperty]) -> ParsedProperty:
    """Convert a list of ParsedProperty into a single property."""
    if not props or len(props) > 1:
        raise ValueError(f"Expected one value for property: {props}")
    return props[0]


def parse_property_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty]]
) -> dict[str, ParsedProperty | list[ParsedProperty]]:
    """Parse the contentlines schema of repeated items into single fields if needed."""
    _LOGGER.debug("Parsing property fields %s", values)
    result: dict[str, ParsedProperty | list[ParsedProperty]] = {}
    for field in cls.__fields__.values():
        if not (prop_list := values.get(field.alias)):
            continue

        if (
            field.shape != SHAPE_LIST
            and isinstance(prop_list, list)
            and is_single_property(field.type_)
        ):
            result[field.alias] = _parse_single_property(prop_list)
        else:
            result[field.alias] = prop_list
    return result


def parse_extra_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty | ParsedComponent]]
) -> dict[str, Any]:
    """Parse extra fields not in the model."""
    _LOGGER.debug("Parsing extra fields: %s", values)
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
        values["extras"] = extras
    return values


def encode_component(name: str, model: dict[str, Any]) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    _LOGGER.debug("Encoding component %s: %s", name, model)
    parent = ParsedComponent(name=name)
    for (key, values) in model.items():
        if key == "extras":
            # Not supported yet
            continue
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    parent.components.append(encode_component(key, value))
                else:
                    parent.properties.append(ParsedProperty(name=key, value=value))
        else:
            if isinstance(values, dict):
                parent.components.append(encode_component(key, values))
            else:
                parent.properties.append(ParsedProperty(name=key, value=values))
    return parent


ICS_ENCODERS = {
    datetime.date: Date.ics,
    Date: Date.ics,
    datetime.datetime: DateTime.ics,
    DateTime: DateTime.ics,
    int: str,
}


class ComponentModel(BaseModel):
    """Abstract class for rfc5545 component model."""

    _parse_extra_fields = root_validator(pre=True, allow_reuse=True)(parse_extra_fields)
    _parse_property_fields = root_validator(pre=True, allow_reuse=True)(
        parse_property_fields
    )
