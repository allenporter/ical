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

from __future__ import annotations

import copy
import datetime
import json
import logging
from collections.abc import Callable
from typing import Any, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, root_validator
from pydantic.fields import SHAPE_LIST, ModelField

from .parsing.component import ParsedComponent
from .parsing.property import ParsedProperty
from .types.boolean import BooleanEncoder
from .types.const import Classification, EventStatus, JournalStatus, TodoStatus
from .types.data_types import DATA_TYPE
from .types.date_time import DateTimeEncoder
from .types.duration import DurationEncoder
from .types.text import TextEncoder

_LOGGER = logging.getLogger(__name__)


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


def parse_enum(prop: ParsedProperty) -> str:
    """Parse a rfc5545 into a text value."""
    return prop.value


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


ICS_ENCODERS: dict[type, Callable[[Any], str | dict[str, str]]] = {
    **DATA_TYPE.encode_property_json,
}
ICS_DECODERS: dict[type, Callable[[ParsedProperty], Any]] = {
    **DATA_TYPE.parse_property_value,
    Classification: parse_enum,
    EventStatus: parse_enum,
    TodoStatus: parse_enum,
    JournalStatus: parse_enum,
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
        # Property parameter specified a strong type
        if func := DATA_TYPE.parse_parameter_by_name.get(value_type):
            return func(prop)
        # Consider graceful degradation instead in the future
        raise ValueError(f"Property parameter specified unsupported type: {value_type}")

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
