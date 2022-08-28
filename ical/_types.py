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
from collections.abc import Callable
from typing import Any, Generator, Optional, TypeVar, Union, get_args, get_origin
from urllib.parse import urlparse

from pydantic import BaseModel, Field, root_validator
from pydantic.dataclasses import dataclass
from pydantic.fields import SHAPE_LIST, ModelField

from .parsing.component import ParsedComponent
from .parsing.property import ParsedProperty, ParsedPropertyParameter
from .recur import Recur
from .types.boolean import BooleanEncoder
from .types.const import Classification, EventStatus, JournalStatus, TodoStatus
from .types.data_types import DATA_TYPE, encode_model_property_params
from .types.date_time import DateTimeEncoder
from .types.duration import DurationEncoder
from .types.integer import IntEncoder
from .types.text import TextEncoder

_LOGGER = logging.getLogger(__name__)


UTC_OFFSET_REGEX = re.compile(r"^([-+]?)([0-9]{2})([0-9]{2})$")

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


class Priority(int):
    """Defines relative priority for a calendar component."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable, None, None]:  # type: ignore[type-arg]
        yield cls.parse_priority

    @classmethod
    def parse_priority(cls, value: ParsedProperty) -> int:
        """Parse a rfc5545 into a text value."""
        priority = IntEncoder.__parse_property_value__(value)
        if priority < 0 or priority > 9:
            raise ValueError("Expected priority between 0-9")
        return priority


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
        return encode_model_property_params(cls.__fields__.values(), model_data)

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
        parts = TextEncoder.__parse_property_value__(value).split(";")
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


def parse_enum(prop: ParsedProperty) -> str:
    """Parse a rfc5545 into a text value."""
    return prop.value


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
    def __encode_property_json__(cls, value: UtcOffset) -> str:
        """Serialize a time delta as a UTC-OFFSET ICS value."""
        duration = value.offset
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
    CAL_ADDRESS = (
        "CAL-ADDRESS",
        CalAddress,
        dataclasses.asdict,
        None,  # Uses pydantic jason BaseModel encoder
    )
    UTC_OFFSET = (
        "UTC-OFFSET",
        UtcOffset,
        UtcOffset.parse_utc_offset,
        UtcOffset.__encode_property_json__,
    )
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
        decode_fn: Callable[[ParsedProperty], Any],
        encode_fn: Callable[[_T], str | dict[str, str]] | None,
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

    def decode(self, value: ParsedProperty) -> Any:
        """Decode a property value into a parsed object."""
        return self._decode_fn(value)

    def encode(self, value: _T) -> str | dict[str, str]:
        """Encode a parsed object into a string value."""
        if not self._encode_fn:
            raise ValueError(
                "Native type is never encoded using value-type json encoder"
            )
        return self._encode_fn(value)


VALUE_TYPES = {
    **{
        property_data_type.data_type_name: property_data_type
        for property_data_type in PropertyDataType
    },
}
ICS_ENCODERS: dict[type, Callable[[Any], str | dict[str, str]]] = {
    **{
        property_data_type.data_type: property_data_type.encode
        for property_data_type in PropertyDataType
    },
    **DATA_TYPE.encode_property_json,
    RequestStatus: RequestStatus.__encode_property_json__,
}
ICS_DECODERS: dict[type, Callable[[ParsedProperty], Any]] = {
    **{
        property_data_type.data_type: property_data_type.decode
        for property_data_type in PropertyDataType
    },
    **DATA_TYPE.parse_property_value,
    Classification: parse_enum,
    EventStatus: parse_enum,
    TodoStatus: parse_enum,
    JournalStatus: parse_enum,
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
        if func := DATA_TYPE.parse_parameter_by_name.get(value_type):
            return func(prop)
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
            _LOGGER.debug("field=%s", field)
            if field.alias == "extras":
                continue
            if not (value := values.get(field.alias)):
                continue
            if not (isinstance(value, list) and isinstance(value[0], ParsedProperty)):
                # The incoming value is not from the parse tree
                continue
            validators = _get_validators(field.type_)
            _LOGGER.debug("validators=%s", validators)
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
