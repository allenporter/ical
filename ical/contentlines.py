"""Parse rfc5545 iCalendar content into a raw data model.

This is a very simple parser that converts lines into a very basic dictionary of
properties. The motivation is to make something that can be fed into pydantic to then
handle the field/object specific parsing.

Parsing expression grammar for rfc5545.

This grammar is defined using pyparsing. The responsibility here is to define
how the tokens fit together so they can be extracted. The meaning of the
sequence of tokens is handled elsewhere.
"""


# mypy: allow-any-generics

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass, field
from typing import Optional

from pyparsing import (
    Combine,
    Group,
    Or,
    ParserElement,
    ParseResults,
    QuotedString,
    Word,
    ZeroOrMore,
    alphanums,
    alphas,
    nums,
)

from .unicode import SAFE_CHAR, UNSAFE_CHAR_RE, VALUE_CHAR

_LOGGER = logging.getLogger(__name__)

FOLD = r"\r?\n[ |\t]"
FOLD_LEN = 75
FOLD_INDENT = " "
WSP = [" ", "\t"]
ATTR_BEGIN = "BEGIN"
ATTR_END = "END"

PARSE_NAME = "name"
PARSE_VALUE = "value"
PARSE_PARAMS = "params"
PARSE_PARAM_NAME = "param_name"
PARSE_PARAM_VALUE = "param_value"


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


def parse_content(content: str) -> list[ParsedComponent]:
    """Parse content into raw properties.

    This includes all necessary unfolding of long lines into full properties.
    """
    content = re.sub(FOLD, "", content, flags=re.MULTILINE)
    return parse_contentlines(re.split("\r?\n", content))


def parse_property_params(
    parse_result_dict: dict[str, str | list]
) -> list[ParsedPropertyParameter]:
    """Extract the property parameters in a ParseResult."""
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


def parse_contentlines(lines: list[str]) -> list[ParsedComponent]:
    """Parse content lines into a calendar raw properties data model.

    This is fairly straight forward in that it walks through each line and uses
    a stack to associate properties with the current object. This does the absolute
    minimum possible parsing into a dictionary of objects to get the right structure.
    All the more detailed parsing of the objects is handled by pydantic, elsewhere.
    """
    token_results = parse_content_tokens(lines)

    stack: list[ParsedComponent] = [ParsedComponent(name="stream")]
    for result in token_results:
        result_dict = result.as_dict()
        if PARSE_NAME not in result_dict or PARSE_VALUE not in result_dict:
            raise ValueError(
                f"Missing fields {PARSE_NAME} or {PARSE_VALUE} in {result_dict}"
            )
        name = result_dict[PARSE_NAME]
        value = result_dict[PARSE_VALUE]
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
                PARSE_VALUE: result_dict[PARSE_VALUE],
            }
            if property_params := parse_property_params(result_dict):
                property_dict[PARSE_PARAMS] = property_params
            stack[-1].properties.append(ParsedProperty(**property_dict))
    return stack[0].components


def create_parser() -> ParserElement:
    """Create rfc5545 parser."""
    iana_token = Word(alphanums + "-")
    vendor_id = Word(alphanums)
    x_name = Combine("X-" + ZeroOrMore(vendor_id + "-") + alphas + nums + "-")
    name = Or([iana_token, x_name])

    param_name = Or([iana_token, x_name])
    # rfc5545 Q-SAFE-CHAR is any character except CONTROL and DQUOTE which is
    # close enough to the pyparsing provided parser element
    param_text = Word(SAFE_CHAR)
    quoted_string = QuotedString('"')

    param_value = Or([param_text, quoted_string])
    # There are multiple levels of property parameter grouping since there can
    # either be repreated property parameters with the same name or property
    # parameters with repeated values. A two level structure is used to grab
    # both, which is then flattened when consuming the result.
    param = Group(
        param_name.set_results_name(PARSE_PARAM_NAME)
        + "="
        + param_value.set_results_name(PARSE_PARAM_VALUE, list_all_matches=True)
        + ZeroOrMore(
            "," + param_value.set_results_name(PARSE_PARAM_VALUE, list_all_matches=True)
        )
    ).set_results_name(PARSE_PARAMS, list_all_matches=True)

    contentline = (
        name.set_results_name(PARSE_NAME)
        + Group(ZeroOrMore(";" + param)).set_results_name(
            PARSE_PARAMS, list_all_matches=True
        )
        + ":"
        + Word(VALUE_CHAR).set_results_name(PARSE_VALUE)
    )
    contentline.set_whitespace_chars("")
    return contentline


def parse_content_tokens(lines: list[str]) -> list[ParseResults]:
    """Parse a set of unfolded lines into parse results."""
    parser = create_parser()
    if _LOGGER.isEnabledFor(logging.DEBUG):
        parser.set_debug(flag=True)
    return [parser.parse_string(line, parse_all=True) for line in lines]


def encode_property(prop: ParsedProperty) -> str:
    """Encode a ParsedProperty into the serialized format."""
    result = []
    if prop.params:
        result.append(";")
        result_params = []
        for parameter in prop.params:
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
    result.append(prop.value)
    return "".join(result)


def encode_component_property(prop: ParsedProperty) -> list[str]:
    """Encode a ParsedProperty into the serialized format."""
    encoded_property = encode_property(prop)
    contentline = f"{prop.name.upper()}{encoded_property}"
    return textwrap.wrap(
        contentline,
        width=FOLD_LEN,
        subsequent_indent=FOLD_INDENT,
        drop_whitespace=False,
        replace_whitespace=False,
        expand_tabs=False,
    )


def encode_content_lines(components: list[ParsedComponent]) -> list[str]:
    """Encode a set of parsed properties into content lines."""
    contentlines = []
    for component in components:
        contentlines.append(f"{ATTR_BEGIN}:{component.name.upper()}")
        for prop in component.properties:
            contentlines.extend(encode_component_property(prop))
        contentlines.extend(encode_content_lines(component.components))
        contentlines.append(f"{ATTR_END}:{component.name.upper()}")
    return contentlines


def encode_content(components: list[ParsedComponent]) -> str:
    """Encode a set of parsed properties into content."""
    return "\n".join(encode_content_lines(components))
