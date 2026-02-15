"""Library for parsing and encoding rfc5545 types."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, SerializationInfo
from pydantic.fields import FieldInfo

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.util import get_field_type
from ical.exceptions import ParameterValueError

_LOGGER = logging.getLogger(__name__)

T_TYPE = TypeVar("T_TYPE", bound=type)


class DataType(Protocol):
    """Defines the protocol implemented by data types in this library.

    The methods defined in this protocol are all optional.
    """

    @classmethod
    def __property_type__(cls) -> type:
        """Defines the python type to match, if different from the type itself."""

    @classmethod
    def __parse_property_value__(cls, prop: ParsedProperty) -> type:
        """Parse the specified property value as a python type."""

    @classmethod
    def __encode_property__(cls, value: Any) -> ParsedProperty | None:
        """Encode the property from the object model to a ParsedProperty."""

    @classmethod
    def __encode_property_json__(cls, value: Any) -> str | dict[str, str]:
        """Encode the property during pydantic serialization to object model."""

    @classmethod
    def __encode_property_value__(cls, value: Any) -> str | None:
        """Encoded the property from the object model to the ics string value."""

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        """Encode the property parameters from the object model."""


class Registry:
    """Registry of data types."""

    def __init__(
        self,
    ) -> None:
        """Initialize Registry."""
        self._items: dict[str, type] = {}
        self._parse_property_value: dict[type, Callable[[ParsedProperty], Any]] = {}
        self._parse_parameter_by_name: dict[str, Callable[[ParsedProperty], Any]] = {}
        self._encode_property: dict[type, Callable[[Any], ParsedProperty | None]] = {}
        self._encode_property_json: dict[
            type, Callable[[Any], str | dict[str, str]]
        ] = {}
        self._encode_property_value: dict[type, Callable[[Any], str | None]] = {}
        self._encode_property_params: dict[
            type, Callable[[dict[str, Any]], list[ParsedPropertyParameter]]
        ] = {}
        self._disable_value_param: set[type] = set()
        self._parse_order: dict[type, int] = {}

    def get_field_types(self, field_type: type) -> list[type]:
        """Return type to attempt for encoding/decoding based on the field type."""
        origin = get_origin(field_type)
        if origin is list:
            if not (args := get_args(field_type)):
                raise ValueError(f"Unable to determine args of type: {field_type}")
            field_type = args[0]
            origin = get_origin(field_type)
        if origin is Union:
            if not (args := get_args(field_type)):
                raise ValueError(f"Unable to determine args of type: {field_type}")

            # get_args does not have a deterministic order, so use the order supplied
            # in the registry. Ignore None as its not a parseable type.
            sortable_args = [
                (self._parse_order.get(arg, 0), arg)
                for arg in args
                if arg is not type(None)  # noqa: E721
            ]
            sortable_args.sort(reverse=True)
            return [arg for (order, arg) in sortable_args]
        return [field_type]

    def parse_property(self, field_type: type, prop: ParsedProperty) -> Any:
        """Parse an individual field value from a ParsedProperty as the specified types."""
        field_types = self.get_field_types(field_type)
        _LOGGER.debug(
            "Parsing field '%s' with value '%s' as types %s",
            prop.name,
            prop.value,
            field_types,
        )
        errors = []
        for sub_type in field_types:
            try:
                return self._parse_single_property(sub_type, prop)
            except ParameterValueError as err:
                _LOGGER.debug("Invalid property value of type %s: %s", sub_type, err)
                raise err
            except ValueError as err:
                _LOGGER.debug(
                    "Unable to parse property value as type %s: %s", sub_type, err
                )
                errors.append(str(err))
                continue
        raise ValueError(
            f"Failed to validate: {prop.value} as {' or '.join(sub_type.__name__ for sub_type in field_types)}, due to: ({errors})"
        )

    def _parse_single_property(self, field_type: type, prop: ParsedProperty) -> Any:
        """Parse an individual field as a single type."""
        if (
            value_type := prop.get_parameter_value("VALUE")
        ) and field_type not in self._disable_value_param:
            # Property parameter specified a strong type
            if func := self._parse_parameter_by_name.get(value_type):
                _LOGGER.debug("Parsing %s as value type '%s'", prop.name, value_type)
                return func(prop)

            # Graceful degradation: fall back to TEXT parsing for unknown VALUE types
            _LOGGER.debug(
                "Property '%s' has unsupported VALUE type '%s', falling back to TEXT",
                prop.name,
                value_type,
            )
            # We assume TextEncoder is already registered in Registry
            if func := self._parse_parameter_by_name.get("TEXT"):
                return func(prop)

        if decoder := self._parse_property_value.get(field_type):
            _LOGGER.debug("Decoding '%s' as type '%s'", prop.name, field_type)
            return decoder(prop)

        _LOGGER.debug("Using '%s' bare property value '%s'", prop.name, prop.value)
        return prop.value

    def encode_property(self, key: str, field_type: type, value: Any) -> ParsedProperty:
        """Encode an individual property for the specified field."""
        # A property field may have multiple possible types, like for
        # a Union. Pick the first type that is able to encode the value.
        errors = []
        for sub_type in self.get_field_types(field_type):
            if encoder := self._encode_property.get(sub_type):
                try:
                    if prop := encoder(value):
                        if not prop.name:
                            prop.name = key
                        return prop
                except ValueError as err:
                    _LOGGER.debug(
                        "Encoding failed for property type %s: %s", sub_type, err
                    )
                    errors.append(str(err))
                    continue

            encoded_value: Any | None = None
            if value_encoder := self._encode_property_value.get(sub_type):
                try:
                    encoded_value = value_encoder(value)
                except ValueError as err:
                    _LOGGER.debug("Encoding failed for property value: %s", err)
                    errors.append(str(err))
                    continue
            else:
                encoded_value = value

            if encoded_value is not None:
                if isinstance(encoded_value, ParsedProperty):
                    return encoded_value
                prop = ParsedProperty(name=key, value=encoded_value)
                if params_encoder := self._encode_property_params.get(sub_type, None):
                    if params := params_encoder(value):
                        prop.params = params
                return prop

        raise ValueError(f"Unable to encode property: {value}, errors: {errors}")

    def register(
        self,
        name: str | None = None,
        disable_value_param: bool = False,
        parse_order: int | None = None,
    ) -> Callable[[T_TYPE], T_TYPE]:
        """Return decorator to register a type.

        The name when specified is the Property Data Type value name.
        """

        def decorator(func: T_TYPE) -> T_TYPE:
            """Register decorated function."""
            if name:
                self._items[name] = func
            data_type = func
            if data_type_func := getattr(func, "__property_type__", None):
                data_type = data_type_func()
            if parse_property_value := getattr(func, "__parse_property_value__", None):
                self._parse_property_value[data_type] = parse_property_value
                if name:
                    self._parse_parameter_by_name[name] = parse_property_value
            if encode_property := getattr(func, "__encode_property__", None):
                self._encode_property[data_type] = encode_property
            if encode_property_json := getattr(func, "__encode_property_json__", None):
                self._encode_property_json[data_type] = encode_property_json
            if encode_property_value := getattr(
                func, "__encode_property_value__", None
            ):
                self._encode_property_value[data_type] = encode_property_value
            if encode_property_params := getattr(
                func, "__encode_property_params__", None
            ):
                self._encode_property_params[data_type] = encode_property_params
            if disable_value_param:
                self._disable_value_param |= set({data_type})
            if parse_order:
                self._parse_order[data_type] = parse_order
            return func

        return decorator

    @property
    def encode_property_json(self) -> dict[type, Callable[[Any], str | dict[str, str]]]:
        """Registry of encoders run during pydantic json serialization."""
        return self._encode_property_json

    @property
    def encode_property_value(self) -> dict[type, Callable[[Any], str | None]]:
        """Registry of encoders that run on the output data model to ics."""
        return self._encode_property_value


DATA_TYPE: Registry = Registry()


def encode_model_property_params(
    fields: dict[str, FieldInfo], model_data: dict[str, Any]
) -> list[ParsedPropertyParameter]:
    """Encode a pydantic model's parameters as property params."""
    params = []
    for name, field in fields.items():
        key = field.alias or name
        if key == "value" or (values := model_data.get(key)) is None:
            continue
        annotation = get_field_type(field.annotation)
        origin = get_origin(annotation)
        if origin is not list:
            values = [values]
        if annotation is bool:
            values = [
                DATA_TYPE.encode_property("", bool, value).value for value in values
            ]
        params.append(ParsedPropertyParameter(name=key, values=values))
    return params


def serialize_field(self: BaseModel, value: Any, info: SerializationInfo) -> Any:
    if not info.context or not info.context.get("ics"):
        return value
    if isinstance(value, list):
        res = []
        for val in value:
            for base in val.__class__.__mro__[:-1]:
                if (func := DATA_TYPE.encode_property_json.get(base)) is not None:
                    res.append(func(val))
                    break
            else:
                res.append(val)
        return res

    for base in value.__class__.__mro__[:-1]:
        if (func := DATA_TYPE.encode_property_json.get(base)) is not None:
            return func(value)
    return value
