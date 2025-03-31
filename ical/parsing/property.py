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

import re
import datetime
from dataclasses import dataclass
from collections.abc import Iterator, Generator, Iterable
from typing import Optional, Union

from .const import PARSE_PARAM_NAME, PARSE_PARAM_VALUE, PARSE_PARAMS
from .unicode import UNSAFE_CHAR_RE


@dataclass
class ParsedPropertyParameter:
    """An rfc5545 property parameter."""

    name: str

    values: list[Union[str, datetime.tzinfo]]
    """Values are typically strings, with a hack for TZID.

    The values may be overridden in the parse tree so that we can directly
    set the timezone information when parsing a date-time rather than
    combining with the calendar at runtime. That is, we update the tree
    with timezone infrmation replacing a string TZID with the zoneinfo.
    """


@dataclass
class ParsedProperty:
    """An rfc5545 property."""

    name: str
    value: str
    params: Optional[list[ParsedPropertyParameter]] = None

    def get_parameter(self, name: str) -> ParsedPropertyParameter | None:
        """Return a single ParsedPropertyParameter with the specified name."""
        if not self.params:
            return None
        for param in self.params:
            if param.name.lower() != name.lower():
                continue
            return param
        return None

    def get_parameter_value(self, name: str) -> str | None:
        """Return the property parameter value."""
        if not (param := self.get_parameter(name)):
            return None
        if len(param.values) > 1:
            raise ValueError(
                f"Expected only a single parameter string value, got {param.values}"
            )
        return param.values[0] if isinstance(param.values[0], str) else None

    def ics(self) -> str:
        """Encode a ParsedProperty into the serialized format."""
        result = [self.name.upper()]
        if self.params:
            result.append(";")
            result_params = []
            for parameter in self.params:
                result_param_values = []
                for value in parameter.values:
                    if not isinstance(value, str):
                        continue  # Shouldn't happen; only strings are set by parsing
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

    @classmethod
    def from_basic_ics(cls, contentline: str) -> "ParsedProperty":
        """Decode a ParsedProperty from an rfc5545 iCalendar content line.

        This does not support the full rfc5545 specification. This may only
        be used for narrower use cases that need more performance than invoking
        the full rfc5545 spec from the `parser` library.

        Will raise a ValueError on failure.
        """
        # Lines can be in either of these formats where the parameters are optional:
        # RRULE:FREQ=WEEKLY;COUNT=10
        # RDATE;VALUE=DATE:19970304T080000Z
        # RDATE:19970304T080000Z
        name, sep, value = contentline.partition(":")
        if not sep:
            raise ValueError(f"Expected ':' in contentline: {contentline}")
        if not (name_parts := name.split(";")) or not name_parts[0]:
            raise ValueError(f"Empty property name in contentline: {contentline}")
        name, property_parameters = name_parts[0], name_parts[1:]
        parsed_property_parameters = []
        for property_parameter in property_parameters:
            param_parts = property_parameter.split("=")
            if len(param_parts) < 2:
                raise ValueError(f"Invalid property parameter: {property_parameter}")
            parsed_property_parameters.append(
                ParsedPropertyParameter(
                    name=param_parts[0],
                    values=param_parts[1:],  # type: ignore[arg-type]
                )
            )

        return ParsedProperty(
            name=name.lower(),
            value=value,
            params=parsed_property_parameters or None,
        )


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
                    name=pair[PARSE_PARAM_NAME], values=pair.get(PARSE_PARAM_VALUE, [""])
                )
            )
    return params


def parse_basic_ics_properties(
    contentlines: Iterable[str],
) -> Generator[ParsedProperty, None, None]:
    for contentline in contentlines:
        if not contentline:
            continue
        yield ParsedProperty.from_basic_ics(contentline)
