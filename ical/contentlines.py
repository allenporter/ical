"""Parse rfc5545 iCalendar content into a raw data model."""

# mypy: allow-any-generics

from __future__ import annotations

import re
from typing import Tuple

FOLD = re.compile("(\r?\n)+[ \t]")
VALUE = re.compile("VALUE=([^:]+):(.*)")


def parse_content(content: str) -> dict[str, list | dict]:
    """Parse content, including any necessary unfolding of long lines, into raw data model."""
    content = re.sub("\r?\n[ |\t]", "", content, flags=re.MULTILINE)
    return parse_contentlines(re.split("\r?\n", content))


def parse_contentlines(lines: list[str]) -> dict[str, list | dict]:
    """Parse content lines into a calendar raw data model."""
    stack: list[Tuple[str, dict]] = [("", {})]
    for line in lines:
        (name, value) = re.split(":|;", line, maxsplit=1)
        if name == "BEGIN":
            value = value.lower()
            if stack and value not in stack[-1][1]:
                stack[-1][1][value] = []
            stack.append((value.lower(), {}))
        elif name == "END":
            value = value.lower()
            if value != stack[-1][0]:
                raise ValueError(f"Unexpected '{line}' bug expected END:{stack[-1][0]}")
            (value, values) = stack.pop()
            # Add the built up dict to a new entry in the list
            stack[-1][1][value].append(values)
        else:
            name = name.lower()
            if match := VALUE.fullmatch(value):
                stack[-1][1][name] = {"param": match.group(1), "value": match.group(2)}
            else:
                stack[-1][1][name] = value
    return stack[0][1]
