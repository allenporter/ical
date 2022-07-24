"""Libraries for translating parsed properties into pydantic data model.

The data model returned by the contentlines parsing is a bag of ParsedProperty
objects that support all the flexibility of the rfc5545 spec. However in the
common case the spec has a lot more flexibility than is needed for handling
simple property types e.g. a single summary field that is specified only once.

This library helps reduce boilerplate for translating that complex structure
into the simpler pydantic data model.
"""

from __future__ import annotations

import logging
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import SHAPE_LIST

from .contentlines import ParsedComponent, ParsedProperty

_LOGGER = logging.getLogger(__name__)


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


def parse_property_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty]]
) -> dict[str, ParsedProperty | list[ParsedProperty]]:
    """Parse the contentlines schema of repeated items into single fields if needed."""
    _LOGGER.debug("Parsing property fields %s", values)
    result: dict[str, ParsedProperty | list[ParsedProperty]] = {}
    for field in cls.__fields__.values():
        if not (prop_list := values.get(field.alias)):
            continue
        if field.shape != SHAPE_LIST and _is_single_property(prop_list, field.type_):
            result[field.alias] = _parse_single_property(prop_list)
        else:
            result[field.alias] = prop_list
    return result


def parse_extra_fields(
    cls: BaseModel, values: dict[str, list[ParsedProperty | ParsedComponent]]
) -> dict[str, Any]:
    """Parse extra fields not in the model."""
    _LOGGER.debug("Parsing extra fields: %s", values)
    all_fields = {
        field.alias for field in cls.__fields__.values() if field.alias != "extras"
    }
    extras: list[ParsedProperty | ParsedComponent] = []
    for (field_name, value) in values.items():
        if field_name in all_fields:
            continue
        for prop in value:
            if isinstance(prop, ParsedProperty):
                extras.append(prop)
    if extras:
        values["extras"] = extras
    return values
