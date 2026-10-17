"""Library for handling rfc5545 components.

An iCalendar object consists of one or more components, that may have
properties or sub-components. An example of a component might be the
calendar itself, an event, a to-do, a journal entry, timezone info, etc.

Components created here have no semantic meaning, but hold all the
data needed to interpret based on the type (e.g. by a pydantic model)
"""

# ty: allow-any-generics

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections.abc import Generator

from ical.exceptions import CalendarParseError

from .const import (
    ATTR_BEGIN,
    ATTR_END,
    FOLD,
    FOLD_INDENT,
    FOLD_LEN,
    ATTR_BEGIN_LOWER,
    ATTR_END_LOWER,
)
from .property import ParsedProperty, parse_contentlines

FOLD_RE = re.compile(FOLD, flags=re.MULTILINE)
LINES_RE = re.compile(r"\r?\n")


@dataclass
class ParsedComponent:
    """An rfc5545 component."""

    name: str
    properties: list[ParsedProperty] = field(default_factory=list)
    components: list[ParsedComponent] = field(default_factory=list)

    def as_dict(self) -> dict[str, str | list[ParsedProperty | dict]]:
        """Convert the component into a pydantic parseable dictionary."""
        result: dict[str, list[ParsedProperty | dict]] = {}
        for prop in self.properties:
            result.setdefault(prop.name, [])
            result[prop.name].append(prop)
        for component in self.components:
            result.setdefault(component.name, [])
            result[component.name].append(component.as_dict())
        return {
            "name": self.name,
            **result,
        }

    def ics(self) -> str:
        """Encode a component as rfc5545 text."""
        contentlines = []
        name = self.name.upper()
        contentlines.append(f"{ATTR_BEGIN}:{name}")
        for prop in self.properties:
            contentlines.extend(_fold(prop.ics()))
        contentlines.extend([component.ics() for component in self.components])
        contentlines.append(f"{ATTR_END}:{name}")
        return "\n".join(contentlines)


def _fold(contentline: str) -> list[str]:
    if not contentline:
        return []
    n = len(contentline)
    if n <= FOLD_LEN:
        return [contentline]
    lines: list[str] = []
    pos = 0
    width = FOLD_LEN
    indent = ""
    stride = FOLD_LEN - len(FOLD_INDENT)
    while pos < n:
        if n - pos <= width:
            lines.append(indent + contentline[pos:])
            break
        split_at = pos + width
        space = contentline.rfind(" ", pos, split_at + 1)
        tab = contentline.rfind("\t", pos, split_at + 1)
        ws = max(space, tab)
        if ws >= pos:
            if ws == split_at:
                start_ws = ws
                while start_ws > pos and contentline[start_ws - 1] in (" ", "\t"):
                    start_ws -= 1
                if start_ws > pos:
                    split_at = start_ws
            else:
                split_at = ws + 1
        lines.append(indent + contentline[pos:split_at])
        pos = split_at
        width = stride
        indent = FOLD_INDENT
    return lines


def parse_content(content: str) -> list[ParsedComponent]:
    """Parse content into raw properties.

    This includes all necessary unfolding of long lines into full properties.

    This is fairly straight forward in that it walks through each line and uses
    a stack to associate properties with the current object. This does the absolute
    minimum possible parsing into a dictionary of objects to get the right structure.
    All the more detailed parsing of the objects is handled by pydantic, elsewhere.
    """
    lines = unfolded_lines(content)
    properties = parse_contentlines(lines)

    stack: list[ParsedComponent] = [ParsedComponent(name="stream")]
    for prop in properties:
        if prop.name == ATTR_BEGIN_LOWER:
            stack.append(ParsedComponent(name=prop.value.lower()))
        elif prop.name == ATTR_END_LOWER:
            if len(stack) <= 1:
                raise CalendarParseError(
                    "Calendar contents are not valid ICS format, see the detailed_error for more information",
                    detailed_error=f"Unexpected '{prop.ics()}' without matching BEGIN",
                )
            component = stack.pop()
            if prop.value.lower() != component.name:
                raise CalendarParseError(
                    "Calendar contents are not valid ICS format, see the detailed_error for more information",
                    detailed_error=f"Unexpected '{prop}', expected {ATTR_END}:{component.name}",
                )
            stack[-1].components.append(component)
        else:
            stack[-1].properties.append(prop)

    if len(stack) > 1:
        raise CalendarParseError(
            "Calendar contents are not valid ICS format, see the detailed_error for more information",
            detailed_error=f"Unexpected end of input, missing {ATTR_END}:{stack[-1].name.upper()}",
        )

    return stack[0].components


def encode_content(components: list[ParsedComponent]) -> str:
    """Encode a set of parsed properties into content."""
    return "\n".join([component.ics() for component in components])


def unfolded_lines(content: str) -> Generator[str, None, None]:
    """Read content and unfold lines."""
    content = FOLD_RE.sub("", content)
    yield from LINES_RE.split(content)
