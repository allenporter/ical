"""Library for parsing rfc5545 types."""

from __future__ import annotations

import logging
from typing import Any

try:
    from pydantic.v1 import BaseModel
    from pydantic.v1.fields import SHAPE_LIST, ModelField
except ImportError:
    from pydantic import BaseModel  # type: ignore[assignment]
    from pydantic.fields import SHAPE_LIST, ModelField  # type: ignore[attr-defined,no-redef]

_LOGGER = logging.getLogger(__name__)


def _all_fields(cls: BaseModel) -> dict[str, ModelField]:
    all_fields: dict[str, ModelField] = {}
    for model_field in cls.__fields__.values():
        all_fields[model_field.name] = model_field
        all_fields[model_field.alias] = model_field
    return all_fields


def parse_parameter_values(cls: BaseModel, values: dict[str, Any]) -> dict[str, Any]:
    """Convert property parameters to pydantic fields."""
    _LOGGER.debug("parse_parameter_values=%s", values)
    if params := values.get("params"):
        all_fields = _all_fields(cls)
        for param in params:
            if not (field := all_fields.get(param["name"])):
                continue
            if field.shape == SHAPE_LIST:
                values[param["name"]] = param["values"]
            else:
                if len(param["values"]) > 1:
                    raise ValueError("Unexpected repeated property parameter")
                values[param["name"]] = param["values"][0]
    return values
