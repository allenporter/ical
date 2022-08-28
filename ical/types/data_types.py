"""Library for parsing rfc5545 types."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

_LOGGER = logging.getLogger(__name__)


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


class Registry(dict[str, type]):
    """Registry of data types."""

    def __init__(
        self,
    ) -> None:
        """Initialize Registry."""
        super().__init__()
        self._parse_property_value: dict[type, Callable[[ParsedProperty], Any]] = {}
        self._parse_parameter_by_name: dict[str, Callable[[ParsedProperty], Any]] = {}
        self._encode_property_json: dict[
            type, Callable[[Any], str | dict[str, str]]
        ] = {}
        self._encode_property_value: dict[type, Callable[[Any], str | None]] = {}
        self._encode_property_params: dict[
            type, Callable[[dict[str, Any]], list[ParsedPropertyParameter]]
        ] = {}

    def register(self, name: str) -> Callable[[type], type]:
        """Return decorator to register item with a specific name."""

        def decorator(func: type) -> type:
            """Register decorated function."""
            self[name] = func
            data_type = func
            if data_type_func := getattr(func, "__property_type__", None):
                data_type = data_type_func()
            if parse_property_value := getattr(func, "__parse_property_value__", None):
                self._parse_property_value[data_type] = parse_property_value
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
            return func

        return decorator

    @property
    def parse_property_value(self) -> dict[type, Callable[[ParsedProperty], Any]]:
        """Registry of python types to functions to parse into pydantic model."""
        _LOGGER.debug("parse_property_value")
        return self._parse_property_value

    @property
    def parse_parameter_by_name(self) -> dict[str, Callable[[ParsedProperty], Any]]:
        """Registry based on data value type string name."""
        _LOGGER.debug("parse_parameter_by_name=%s", self._parse_parameter_by_name)
        return self._parse_parameter_by_name

    @property
    def encode_property_json(self) -> dict[type, Callable[[Any], str | dict[str, str]]]:
        """Registry of encoders run during pydantic json serialization."""
        _LOGGER.debug("encode_property_json=%s", self._encode_property_json)
        return self._encode_property_json

    @property
    def encode_property_value(self) -> dict[type, Callable[[Any], str | None]]:
        """Registry of encoders that run on the output data model to ics."""
        _LOGGER.debug("encode_property_value=%s", self._encode_property_value)
        return self._encode_property_value

    @property
    def encode_property_params(
        self,
    ) -> dict[type, Callable[[dict[str, Any]], list[ParsedPropertyParameter]]]:
        """Registry of property parameter encoders run on output data model."""
        return self._encode_property_params


DATA_TYPE: Registry = Registry()
