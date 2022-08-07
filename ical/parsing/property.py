"""Library for handling rfc5545 properties and parameters.

A property is the definition of an individual attribute describing a
calendar object or a calendar component. A property is also really
just a "contentline", however properties in this file are the
output of the parser and are provided in the context of where
they live on a component hierarchy (e.g. attached to a component,
or sub component).
"""

# mypy: allow-any-generics

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .const import PARSE_PARAM_NAME, PARSE_PARAM_VALUE, PARSE_PARAMS
from .unicode import UNSAFE_CHAR_RE


@dataclass
class ParsedPropertyParameter:
    """An rfc5545 property parameter."""

    name: str
    values: list[str]


@dataclass
class ParsedProperty:
    """An rfc5545 property."""

    name: str
    value: str
    params: Optional[list[ParsedPropertyParameter]] = None

    def get_parameter_values(self, name: str) -> list[str]:
        """Return the list of property parameter values."""
        if not self.params:
            return []
        for param in self.params:
            if param.name.lower() != name.lower():
                continue
            return param.values
        return []

    def get_parameter_value(self, name: str) -> str | None:
        """Return the property parameter value."""
        values = self.get_parameter_values(name)
        if not values:
            return None
        if len(values) > 1:
            raise ValueError(f"Expected only a single parameter value, got {values}")
        return values[0]

    def ics(self) -> str:
        """Encode a ParsedProperty into the serialized format."""
        result = [self.name.upper()]
        if self.params:
            result.append(";")
            result_params = []
            for parameter in self.params:
                result_param_values = []
                for value in parameter.values:
                    # Property parameters with values contain a colon, simicolon,
                    # or a comma character must be placed in quoted text
                    if UNSAFE_CHAR_RE.search(value):
                        result_param_values.append(f'"{value}"')
                    else:
                        result_param_values.append(value)
                values = ",".join(result_param_values)
                result_params.append(f"{parameter.name.upper()}={values}")
            result.append(";".join(result_params))
        result.append(":")
        result.append(str(self.value))
        return "".join(result)


def parse_property_params(
    parse_result_dict: dict[str, str | list]
) -> list[ParsedPropertyParameter]:
    """Extract the property parameters from a pyparsing ParseResult object."""
    if PARSE_PARAMS not in parse_result_dict:
        return []
    params: list[ParsedPropertyParameter] = []
    for parsed_params in parse_result_dict[PARSE_PARAMS]:
        if not isinstance(parsed_params, dict) or PARSE_PARAMS not in parsed_params:
            continue
        for pair in parsed_params[PARSE_PARAMS]:
            params.append(
                ParsedPropertyParameter(
                    name=pair[PARSE_PARAM_NAME], values=pair[PARSE_PARAM_VALUE]
                )
            )
    return params
