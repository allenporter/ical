"""Library for handling rfc5545 components.

An iCalendar object consists of one or more components, that may have
properties or sub-components. An example of a component might be the
calendar itself, an event, a to-do, a journal entry, timezone info, etc.

Components created here have no semantic meaning, but hold all the
data needed to interpret based on the type (e.g. by a pydantic model)
"""

# mypy: allow-any-generics

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from collections.abc import Generator

from .const import (
    ATTR_BEGIN,
    ATTR_END,
    FOLD,
    FOLD_INDENT,
    FOLD_LEN,
    PARSE_NAME,
    PARSE_PARAMS,
    PARSE_VALUE,
)
from .parser import parse_contentlines
from .property import ParsedProperty, parse_property_params, parse_basic_ics_properties

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
    return textwrap.wrap(
        contentline,
        width=FOLD_LEN,
        subsequent_indent=FOLD_INDENT,
        drop_whitespace=False,
        replace_whitespace=False,
        expand_tabs=False,
        break_on_hyphens=False,
    )


def parse_content(content: str) -> list[ParsedComponent]:
    """Parse content into raw properties.

    This includes all necessary unfolding of long lines into full properties.

    This is fairly straight forward in that it walks through each line and uses
    a stack to associate properties with the current object. This does the absolute
    minimum possible parsing into a dictionary of objects to get the right structure.
    All the more detailed parsing of the objects is handled by pydantic, elsewhere.
    """
    lines = unfolded_lines(content)
    token_results = parse_contentlines(lines)

    stack: list[ParsedComponent] = [ParsedComponent(name="stream")]
    for result in token_results:
        result_dict = result.as_dict()
        if PARSE_NAME not in result_dict:
            raise ValueError(
                f"Missing fields {PARSE_NAME} or {PARSE_VALUE} in {result_dict}"
            )
        name = result_dict[PARSE_NAME]
        value = result_dict.get(PARSE_VALUE, "")
        if name == ATTR_BEGIN:
            stack.append(ParsedComponent(name=value.lower()))
        elif name == ATTR_END:
            value = value.lower()
            component = stack.pop()
            if value != component.name:
                raise ValueError(
                    f"Unexpected '{result}', expected {ATTR_END}:{component.name}"
                )
            stack[-1].components.append(component)
        else:
            name = name.lower()
            property_dict = {
                PARSE_NAME: name,
                PARSE_VALUE: value,
            }
            if property_params := parse_property_params(result_dict):
                property_dict[PARSE_PARAMS] = property_params
            stack[-1].properties.append(ParsedProperty(**property_dict))
    return stack[0].components


def encode_content(components: list[ParsedComponent]) -> str:
    """Encode a set of parsed properties into content."""
    return "\n".join([component.ics() for component in components])


def unfolded_lines(content: str) -> Generator[str, None, None]:
    """Read content and unfold lines."""
    content = FOLD_RE.sub("", content)
    yield from LINES_RE.split(content)
