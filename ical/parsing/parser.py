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

import logging
from functools import cache
import re
from typing import Iterable
from ical.exceptions import CalendarParseError
from ical.parsing.property import ParsedPropertyParameter


from .const import (
    PARSE_NAME,
    PARSE_PARAM_NAME,
    PARSE_PARAM_VALUE,
    PARSE_PARAMS,
    PARSE_VALUE,
)

_LOGGER = logging.getLogger(__name__)


_RE_CONTROL_CHARS = re.compile("[\x00-\x08\x0A-\x1F\x7F]")
_RE_NAME = re.compile("[A-Z0-9\-]+")

@cache
def parse_line(line: str) -> dict:
    """Parse a single line."""
    
    dict_result = {}
    pos = 0

    # parse NAME
    while True:
        if pos >= len(line):
            raise CalendarParseError(f"Unexpected end of line. Expected ';' or ':'", detailed_error = line)
        char = line[pos]
        if char == ';' or char == ':':
            name = line[0:pos]
            if not _RE_NAME.fullmatch(name):
                raise CalendarParseError(f"Invalid property name '{name}'", detailed_error = line)
            dict_result[PARSE_NAME] = name
            break
        pos += 1

    # parse PARAMS if any
    if line[pos] == ';':
        params: list[ParsedPropertyParameter] = []
        pos += 1
        params_start = pos
        value_start = 0
        while pos < len(line):
            
            # Read until we hit name/value separator (=)
            if line[pos] != '=':
                pos += 1
                if pos >= len(line):
                    raise CalendarParseError(f"Unexpected end of line. Expected '='", detailed_error = line)
                continue
                
            # param name reached
            param_name = line[params_start:pos]
            if not _RE_NAME.fullmatch(param_name):
                raise CalendarParseError(f"Invalid parameter name '{param_name}'", detailed_error = line)
            pos += 1
            
            # Now read values. (list separated by comma)
            param_values = []
            all_values_read = False
            while not all_values_read:
                value_start = pos
                quoted = False

                if line[pos] == '"':
                    # read all in quotes
                    quoted = True
                    pos += 1

                value_read = False
                while not value_read:
                    if pos >= len(line):
                        if quoted:
                            raise CalendarParseError(f"Unexpected end of line. Expected end of qouted string", detailed_error = line)
                        else:
                            raise CalendarParseError(f"Unexpected end of line. Expected ',', ';' or ':'", detailed_error = line)
                    
                    char = line[pos]

                    if char == '"':
                        if not quoted:
                            raise CalendarParseError(f"Unexpected quote character outside parameter value.", detailed_error = line)
                        param_value = line[value_start + 1:pos]
                        value_read = True
                        pos += 1
                        char = line[pos]
                    elif not quoted and (char == ',' or char == ';' or char == ':'):
                        param_value = line[value_start:pos]
                        value_read = True

                    if value_read:
                        if not (char == ',' or char == ';' or char == ':'):
                            raise CalendarParseError(
                                f"Expected ',' or ';' or ':' after parameter value, got '{char}'",
                                detailed_error=line,
                            )
                        param_values.append(param_value)
                        all_values_read = char != ','

                    pos += 1
                
            params.append(ParsedPropertyParameter(name=param_name, values=param_values))
            
            if char == ':':
                dict_result[PARSE_PARAMS] = params
                break
            params_start = pos
            pos += 1
    else:
        if line[pos] != ':':
            raise CalendarParseError(f"Expected ':' after property name", detailed_error = line)
        pos += 1

    value = line[pos:]
    if _RE_CONTROL_CHARS.search(value):
        raise CalendarParseError(
            f"Property value contains control characters: {value}",
            detailed_error=line,
        )
    dict_result[PARSE_VALUE] = value
    return dict_result        



def parse_contentlines(lines: Iterable[str]) -> list[dict]:
    """Parse a set of unfolded lines into parse results."""

    try:
        return [parse_line(line) for line in lines if line]
    except Exception as err:
        raise CalendarParseError(
                f"Failed to parse calendar contents", detailed_error=str(err)
        ) from err
