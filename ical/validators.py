"""Libraries for translating parsed properties into pydantic data model.

The data model returned by the contentlines parsing is a bag of ParsedProperty
objects that support all the flexibility of the rfc5545 spec. However in the
common case the spec has a lot more flexibility than is needed for handling
simple property types e.g. a single summary field that is specified only once.

This library helps reduce boilerplate for translating that complex structure
into the simpler pydantic data model.
"""

from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import SHAPE_LIST

from .contentlines import ParsedProperty


def _is_single_property(value: Any, field_type: type) -> bool:
    """Return true if pydantic field typing indicates a single value property."""

    if not isinstance(value, list):
        return False

    origin = get_origin(field_type)
    if origin is Union:
        args = get_args(field_type)
        if args and args[0] is not list:
            return True
        return False

    if origin is not list:
        return True

    return False


def _parse_single_property(props: list[ParsedProperty]) -> ParsedProperty:
    """Convert a list of ParsedProperty into a single property."""
    if not props or len(props) > 1:
        raise ValueError(f"Expected one value for property: {props}")
    return props[0]


def parse_property_fields(cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Parse the contentlines schema of repeated items into single fields if needed."""
    for field in cls.__fields__.values():
        if not (prop_list := values.get(field.alias)):
            continue
        if field.shape != SHAPE_LIST and _is_single_property(prop_list, field.type_):
            values[field.alias] = _parse_single_property(prop_list)
    return values
