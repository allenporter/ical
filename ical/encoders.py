"""Library for encoding pydantic model state to prepare for serialization."""

import logging
from typing import Any

from .contentlines import ParsedComponent, ParsedProperty

_LOGGER = logging.getLogger(__name__)


def encode_component(name: str, model: dict[str, Any]) -> ParsedComponent:
    """Encode a pydantic model for serialization as an iCalendar object."""
    _LOGGER.debug("Encoding component %s: %s", name, model)
    parent = ParsedComponent(name=name)
    for (key, values) in model.items():
        if key == "extras":
            # Not supported yet
            continue
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    parent.components.append(encode_component(key, value))
                else:
                    parent.properties.append(ParsedProperty(name=key, value=value))
        else:
            if isinstance(values, dict):
                parent.components.append(encode_component(key, values))
            else:
                parent.properties.append(ParsedProperty(name=key, value=values))
    return parent
