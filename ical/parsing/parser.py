"""A pyparsing text parser for rfc5545 files.

This is a very simple parser that converts lines in an iCalendar file into a an object
structure with necessary relationships to interpret the meaning of the contentlines and
how the parts break down into properties and parameters. This library does not attempt
to interpret the meaning of the properties or types themselves.

For example, given a content line of:

  DUE;VALUE=DATE:20070501

This library would create a ParseResults object with this structure:

  {
    'name': 'DUE',
    'value': '20070501'
    'params': [{
            'param_name': 'VALUE',
            'param_value': 'DATE',
    }]
  }

Note: This specific example may be a bit confusing because one of the property parameters is named
"VALUE" which refers to the value type.
"""

from datetime import tzinfo
import logging
from functools import cache
import re
from typing import Iterable
from ical.exceptions import CalendarParseError
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

_LOGGER = logging.getLogger(__name__)

_RE_CONTROL_CHARS = re.compile("[\x00-\x08\x0a-\x1f\x7f]")
_RE_NAME = re.compile("[A-Z0-9-]+")


@cache
def parse_line(line: str) -> ParsedProperty:
    """Parse a single property line."""

    params: list[ParsedPropertyParameter] = []
    line_len = len(line)
    pos = 0

    # parse NAME
    while True:
        if pos >= line_len:
            raise CalendarParseError(
                f"Unexpected end of line. Expected ';' or ':'", detailed_error=line
            )
        if line[pos] in (";", ":"):
            name = line[0:pos]
            if not _RE_NAME.fullmatch(name):
                raise CalendarParseError(
                    f"Invalid property name '{name}'", detailed_error=line
                )
            property_name = name.lower()
            break
        pos += 1

    # parse PARAMS if any
    if line[pos] == ";":
        params = []
        pos += 1
        params_start = pos
        all_params_read = False

        while pos < line_len and not all_params_read:

            # Read until we hit name/value separator (=)
            if line[pos] != "=":
                pos += 1
                if pos >= line_len:
                    raise CalendarParseError(
                        f"Unexpected end of line. Expected '='", detailed_error=line
                    )
                continue

            # param name reached
            param_name = line[params_start:pos]
            if not _RE_NAME.fullmatch(param_name):
                raise CalendarParseError(
                    f"Invalid parameter name '{param_name}'", detailed_error=line
                )
            pos += 1

            # Now read parameter values. (comma separated)
            param_values: list[str | tzinfo] = []
            all_values_read = False

            while not all_values_read:

                if quoted := (line[pos] == '"'):
                    # parameter value is quoted
                    quoted = True
                    pos += 1

                param_value_read = False
                param_value_start = pos

                while not param_value_read:
                    if pos >= line_len:
                        if quoted:
                            raise CalendarParseError(
                                f"Unexpected end of line. Expected end of quoted string",
                                detailed_error=line,
                            )
                        else:
                            raise CalendarParseError(
                                f"Unexpected end of line. Expected ',', ';' or ':'",
                                detailed_error=line,
                            )

                    if (char := line[pos]) == '"':
                        if not quoted:
                            raise CalendarParseError(
                                f"Unexpected quote character outside parameter value",
                                detailed_error=line,
                            )

                        param_value_read = True
                        pos += 1

                        if not (char := line[pos]) in (",", ";", ":"):
                            raise CalendarParseError(
                                f"Expected ',' or ';' or ':' after parameter value, got '{char}'",
                                detailed_error=line,
                            )

                    elif not quoted and char in (",", ";", ":"):
                        param_value_read = True

                    if param_value_read:
                        param_value = line[
                            param_value_start : pos - (1 if quoted else 0)
                        ]
                        param_values.append(param_value)
                        all_values_read = char != ","
                        all_params_read = char == ":"

                    pos += 1

            params.append(ParsedPropertyParameter(name=param_name, values=param_values))

            if not all_params_read:
                # reset for next parameter
                params_start = pos
                pos += 1
    else:
        pos += 1

    property_value = line[pos:]
    if _RE_CONTROL_CHARS.search(property_value):
        raise CalendarParseError(
            f"Property value contains control characters: {property_value}",
            detailed_error=line,
        )

    return ParsedProperty(
        name=property_name, value=property_value, params=params if params else None
    )


def parse_contentlines(lines: Iterable[str]) -> list[ParsedProperty]:
    """Parse a set of unfolded lines into parse results."""

    try:
        return [parse_line(line) for line in lines if line]
    except Exception as err:
        raise CalendarParseError(
            f"Failed to parse calendar contents", detailed_error=str(err)
        ) from err
