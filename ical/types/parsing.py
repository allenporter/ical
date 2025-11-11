"""Library for parsing rfc5545 types."""

from __future__ import annotations

import logging
from typing import Any, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ical.util import get_field_type

_LOGGER = logging.getLogger(__name__)


def _all_fields(cls: type[BaseModel]) -> dict[str, FieldInfo]:
    all_fields: dict[str, FieldInfo] = {}
    for name, model_field in cls.model_fields.items():
        all_fields[name] = model_field
        if model_field.alias is not None:
            all_fields[model_field.alias] = model_field
    return all_fields


def parse_parameter_values(
    cls: type[BaseModel], values: dict[str, Any]
) -> dict[str, Any]:
    """Convert property parameters to pydantic fields."""
    _LOGGER.debug("parse_parameter_values=%s", values)
    if params := values.get("params"):
        all_fields = _all_fields(cls)
        for param in params:
            if not (field := all_fields.get(param["name"])):
                continue
            annotation = get_field_type(field.annotation)
            if get_origin(annotation) is list:
                values[param["name"]] = param["values"]
            else:
                if len(param["values"]) > 1:
                    raise ValueError("Unexpected repeated property parameter")
                values[param["name"]] = param["values"][0]
    return values
