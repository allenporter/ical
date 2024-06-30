"""Library for parsing and encoding rfc5545 types."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Iterable, Protocol, TypeVar

try:
    from pydantic.v1.fields import SHAPE_LIST, ModelField
except ImportError:
    from pydantic.fields import SHAPE_LIST, ModelField  # type: ignore[attr-defined, no-redef]

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

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
        self._encode_property_json: dict[
            type, Callable[[Any], str | dict[str, str]]
        ] = {}
        self._encode_property_value: dict[type, Callable[[Any], str | None]] = {}
        self._encode_property_params: dict[
            type, Callable[[dict[str, Any]], list[ParsedPropertyParameter]]
        ] = {}
        self._disable_value_param: set[type] = set()
        self._parse_order: dict[type, int] = {}

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
    def parse_property_value(self) -> dict[type, Callable[[ParsedProperty], Any]]:
        """Registry of python types to functions to parse into pydantic model."""
        return self._parse_property_value

    @property
    def parse_parameter_by_name(self) -> dict[str, Callable[[ParsedProperty], Any]]:
        """Registry based on data value type string name."""
        return self._parse_parameter_by_name

    @property
    def encode_property_json(self) -> dict[type, Callable[[Any], str | dict[str, str]]]:
        """Registry of encoders run during pydantic json serialization."""
        return self._encode_property_json

    @property
    def encode_property_value(self) -> dict[type, Callable[[Any], str | None]]:
        """Registry of encoders that run on the output data model to ics."""
        return self._encode_property_value

    @property
    def encode_property_params(
        self,
    ) -> dict[type, Callable[[dict[str, Any]], list[ParsedPropertyParameter]]]:
        """Registry of property parameter encoders run on output data model."""
        return self._encode_property_params

    @property
    def disable_value_param(self) -> set[type]:
        """Return set of types that do not allow VALUE overrides by component parsing."""
        return self._disable_value_param

    @property
    def parse_order(self) -> dict[type, int]:
        """Return the parse ordering of the specified type."""
        return self._parse_order


DATA_TYPE: Registry = Registry()


def encode_model_property_params(
    fields: Iterable[ModelField], model_data: dict[str, Any]
) -> list[ParsedPropertyParameter]:
    """Encode a pydantic model's parameters as property params."""
    params = []
    for field in fields:
        key = field.alias
        if key == "value" or (values := model_data.get(key)) is None:
            continue
        if field.shape != SHAPE_LIST:
            values = [values]
        if field.type_ is bool:
            encoder = DATA_TYPE.encode_property_value[bool]
            values = [encoder(value) for value in values]
        params.append(ParsedPropertyParameter(name=key, values=values))
    return params
