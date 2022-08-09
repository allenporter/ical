"""Parameters or meta information associated with a property.

Property parameters are additional modifiers on a property to specify extra
information about the value for the property (e.g. language, value type, a
display attribute, etc).

Property parameters are stored as additional fields on a dataclass.
"""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any, Callable

from .parsing.property import ParsedPropertyParameter

_LOGGER = logging.getLogger(__name__)


def quoted_decode(value: str) -> str:
    """Decode the specified quoted value."""
    if len(value) > 1 and value[0] == '"' and value[-1] == '"':
        raise ValueError(f"Quoted value was of the wrong format {value}")
    return value


def quoted_encode(value: str) -> str:
    """Encode the specific quoted value."""
    return f'"{value}"'


class ParameterType(ABC):
    """Property parameter type protocol."""

    ics_name: str
    attribute_name: str
    decode: Callable[[str], str]
    encode: Callable[[str], str]


class AlternateText(ParameterType):
    """An alternate text representation for the property value."""

    ics_name = "ALTREP"
    attribute_name = "alternate_text"
    decode = quoted_decode
    encode = quoted_encode


class CommonName(ParameterType):
    """The common name associated with the user specified by the property."""

    ics_name = "CN"
    attribute_name = "common_name"
    decode = str
    encode = str


# Known values of the CalendarUserType string.
USER_TYPE_INDIVIDUAL = "INDIVIDUAL"
USER_TYPE_GROUP = "GROUP"
USER_TYPE_RESOURCE = "RESOURCE"
USER_TYPE_ROOM = "ROOM"
USER_TYPE_UNKNOWN = "UNKNOWN"


class CalendarUserType(ParameterType):
    """Identifies the type of calendar user specified by the property."""

    ics_name = "CUTYPE"
    attribute_name = "user_type"
    decode = str
    encode = str


PARAMETER_TYPES: list[type[ParameterType]] = [
    AlternateText,
    CommonName,
    CalendarUserType,
]
PARAMETERS_BY_ICS_MAP = {param.ics_name: param for param in PARAMETER_TYPES}
PARAMETERS_BY_ATTR_MAP = {param.attribute_name: param for param in PARAMETER_TYPES}


def set_parameter_attributes(
    target: Any, params: list[ParsedPropertyParameter]
) -> None:
    """Parse any known parameters and set as attributes on the target."""
    for param in params:
        if len(param.values) != 1:
            raise ValueError("Unexpected parameter with multiple value")
        param_value = param.values[0]
        if not (param_type := PARAMETERS_BY_ICS_MAP.get(param.name)):
            continue
        if hasattr(target, param_type.attribute_name):
            try:
                decoded_value = param_type.decode(param_value)
            except ValueError as err:
                raise ValueError(
                    "Failed to decode parameter {param.name}: {param_value}"
                ) from err
            setattr(target, param_type.attribute_name, decoded_value)


def encode_parameter_attributes(values: Any) -> list[ParsedPropertyParameter] | None:
    """Encode any present parameter attributes as a list of encoded ICS parameters."""
    result: list[ParsedPropertyParameter] = []
    for attr, value in values.items():
        if not value or not (param_type := PARAMETERS_BY_ATTR_MAP.get(attr)):
            continue
        encoded_value = param_type.encode(value)
        result.append(
            ParsedPropertyParameter(name=param_type.ics_name, values=[encoded_value])
        )
    if result:
        return result
    return None
