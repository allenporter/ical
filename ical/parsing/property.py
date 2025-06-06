"""Library for handling rfc5545 properties and parameters.

A property is the definition of an individual attribute describing a
calendar object or a calendar component. A property is also really
just a "contentline", however properties in this file are the
output of the parser and are provided in the context of where
they live on a component hierarchy (e.g. attached to a component,
or sub component).

This is a very simple parser that converts lines in an iCalendar file into a an object
structure with necessary relationships to interpret the meaning of the contentlines and
how the parts break down into properties and parameters. This library does not attempt
to interpret the meaning of the properties or types themselves.

For example, given a content line of:

  DUE;VALUE=DATE:20070501

This library would create a ParseResults object with this structure:

  ParsedProperty(
    name='due',
    value='20070501',
    params=[
        ParsedPropertyParameter(
            name='VALUE',
            values=['DATE']
        )
    ]
  }

Note: This specific example may be a bit confusing because one of the property parameters is named
"VALUE" which refers to the value type.
"""

# mypy: allow-any-generics

from __future__ import annotations

import re
import datetime
from dataclasses import dataclass
from collections.abc import Iterator, Generator, Iterable
from typing import Optional, Union, Sequence, Iterable

from ical.exceptions import CalendarParseError


# Characters that should be encoded in quotes
_UNSAFE_CHAR_RE = re.compile(r"[,:;]")
_RE_CONTROL_CHARS = re.compile("[\x00-\x08\x0a-\x1f\x7f]")
_RE_NAME = re.compile("[A-Z0-9-]+")
_NAME_DELIMITERS = (";", ":")
_PARAM_DELIMITERS = (",", ";", ":")
_QUOTE = '"'


def _find_first(
    line: str, chars: Sequence[str], start: int | None = None
) -> int | None:
    """Find the earliest occurrence of any of the given characters in the line."""
    if not chars:
        raise ValueError("At least one character must be provided to search for.")
    earliest: int | None = None
    for char in chars:
        pos = line.find(char, start)
        if pos != -1 and (earliest is None or pos < earliest):
            earliest = pos
    return earliest


@dataclass
class ParsedPropertyParameter:
    """An rfc5545 property parameter."""

    name: str

    values: Sequence[Union[str, datetime.tzinfo]]
    """Values are typically strings, with a hack for TZID.

    The values may be overridden in the parse tree so that we can directly
    set the timezone information when parsing a date-time rather than
    combining with the calendar at runtime. That is, we update the tree
    with timezone information replacing a string TZID with the zoneinfo.
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
                    # Property parameters with values contain a colon, semicolon,
                    # or a comma character must be placed in quoted text
                    if _UNSAFE_CHAR_RE.search(value):
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
    def from_ics(cls, contentline: str) -> "ParsedProperty":
        """Decode a ParsedProperty from an rfc5545 iCalendar content line.

        Will raise a CalendarParseError on failure.
        """
        return _parse_line(contentline)


def _parse_line(line: str) -> ParsedProperty:
    """Parse a single property line."""

    # parse NAME
    if (name_end_pos := _find_first(line, _NAME_DELIMITERS)) is None:
        raise CalendarParseError(
            f"Invalid property line, expected {_NAME_DELIMITERS} after property name",
            detailed_error=line,
        )
    property_name = line[0:name_end_pos]
    has_params = line[name_end_pos] == ";"
    pos = name_end_pos + 1
    line_len = len(line)

    # parse PARAMS if any
    params: list[ParsedPropertyParameter] = []
    if has_params:
        while pos < line_len:
            if (param_name_end_pos := line.find("=", pos)) == -1:
                raise CalendarParseError(
                    f"Invalid parameter format: missing '=' after parameter name part '{line[pos:]}'",
                    detailed_error=line,
                )
            param_name = line[pos:param_name_end_pos]
            pos = param_name_end_pos + 1

            # parse one or more comma-separated PARAM-VALUES
            param_values: list[str] = []
            delimiter: str | None = None
            while delimiter is None or delimiter == ",":
                if pos >= line_len:
                    raise CalendarParseError(
                        "Unexpected end of line. Expected parameter value or delimiter.",
                        detailed_error=line,
                    )
                param_value: str
                if line[pos] == _QUOTE:
                    if (end_quote_pos := line.find(_QUOTE, pos + 1)) == -1:
                        raise CalendarParseError(
                            "Unexpected end of line: unclosed quoted parameter value.",
                            detailed_error=line,
                        )
                    param_value = line[pos + 1 : end_quote_pos]
                    pos = end_quote_pos + 1
                else:
                    if (end_pos := _find_first(line, _PARAM_DELIMITERS, pos)) is None:
                        raise CalendarParseError(
                            "Unexpected end of line: missing parameter value delimiter.",
                            detailed_error=line,
                        )
                    param_value = line[pos:end_pos]
                    pos = end_pos

                param_values.append(param_value)

                # After extracting value, pos is at the delimiter or EOL.
                if pos >= line_len:
                    # E.g., quoted value ended right at EOL, or unquoted value consumed up to EOL.
                    # A delimiter is always expected after a value within parameters.
                    raise CalendarParseError(
                        f"Unexpected end of line after parameter value '{param_value}'. Expected delimiter {_PARAM_DELIMITERS}.",
                        detailed_error=line,
                    )

                if (delimiter := line[pos]) not in _PARAM_DELIMITERS:
                    raise CalendarParseError(
                        f"Expected {_PARAM_DELIMITERS} after parameter value, got '{delimiter}'",
                        detailed_error=line,
                    )
                pos += 1

            params.append(ParsedPropertyParameter(name=param_name, values=param_values))

            if delimiter == ":":
                break  # We are done with all parameters.

    property_name = property_name.upper()
    if not _RE_NAME.fullmatch(property_name):
        raise CalendarParseError(
            f"Invalid property name '{property_name}'", detailed_error=line
        )
    for param in params:
        if not _RE_NAME.fullmatch(param.name):
            raise CalendarParseError(
                f"Invalid parameter name '{param.name}'", detailed_error=line
            )
        for value in param.values:
            if not isinstance(value, str):
                raise ValueError(
                    f"Invalid parameter value type: {type(value).__name__}"
                )
            if value.find(_QUOTE) != -1:
                raise CalendarParseError(
                    f"Parameter value '{value}' for parameter '{param.name}' is improperly quoted",
                    detailed_error=line,
                )
            if _RE_CONTROL_CHARS.search(value):
                raise CalendarParseError(
                    f"Invalid parameter value '{value}' for parameter '{param.name}'",
                    detailed_error=line,
                )

    property_value = line[pos:]
    if _RE_CONTROL_CHARS.search(property_value):
        raise CalendarParseError(
            f"Property value contains control characters: {property_value}",
            detailed_error=line,
        )

    return ParsedProperty(
        name=property_name.lower(),
        value=property_value,
        params=params if params else None,
    )


def parse_contentlines(
    contentlines: Iterable[str],
) -> Generator[ParsedProperty, None, None]:
    """Parse a contentlines into ParsedProperty objects."""
    for contentline in contentlines:
        if not contentline:
            continue
        try:
            yield ParsedProperty.from_ics(contentline)
        except CalendarParseError as err:
            raise CalendarParseError(
                f"Failed to parse calendar contents", detailed_error=str(err)
            ) from err
