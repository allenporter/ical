"""Parse rfc5545 iCalendar content into a raw data model.

This is a very simple parser that converts lines into a very basic dictionary.
The motivation is to make something that can be fed into pydantic to then
handle the field/object specific parsing.
"""

# mypy: allow-any-generics

from __future__ import annotations

import re
from typing import Tuple

FOLD = re.compile("(\r?\n)+[ \t]")
VALUE = re.compile("VALUE=([^:]+):(.*)")

ATTR_BEGIN = "BEGIN"
ATTR_END = "END"
ATTR_PARAM = "param"
ATTR_VALUE = "value"


def parse_content(content: str) -> dict[str, list | dict]:
    """Parse content, including any necessary unfolding of long lines, into raw data model."""
    content = re.sub("\r?\n[ |\t]", "", content, flags=re.MULTILINE)
    return parse_contentlines(re.split("\r?\n", content))


def parse_contentlines(lines: list[str]) -> dict[str, list | dict]:
    """Parse content lines into a calendar raw data model.

    This is fairly straight forward in that it walks through each line and uses
    a stack to associate properties with the current object. This does the absolute
    minimum possible parsing into a dictionary of objects to get the right structure.
    All the more detailed parsing of the objects is handled by pydantic, elsewhere.
    """
    stack: list[Tuple[str, dict]] = [("", {})]
    for line in lines:
        (name, value) = re.split(":|;", line, maxsplit=1)
        if name == ATTR_BEGIN:
            value = value.lower()
            if stack and value not in stack[-1][1]:
                stack[-1][1][value] = []
            stack.append((value.lower(), {}))
        elif name == ATTR_END:
            value = value.lower()
            if value != stack[-1][0]:
                raise ValueError(
                    f"Unexpected '{line}' bug expected {ATTR_END}:{stack[-1][0]}"
                )
            (value, values) = stack.pop()
            # Add the built up dict to a new entry in the list
            stack[-1][1][value].append(values)
        else:
            name = name.lower()
            if match := VALUE.fullmatch(value):
                stack[-1][1][name] = {
                    ATTR_PARAM: match.group(1),
                    ATTR_VALUE: match.group(2),
                }
            else:
                stack[-1][1][name] = value
    return stack[0][1]
