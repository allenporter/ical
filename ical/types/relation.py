"""Implementation of the RELATED-TO property."""

import enum
from dataclasses import dataclass
from collections.abc import Callable, Generator
from typing import Any
import logging

try:
    from pydantic.v1 import root_validator
except ImportError:
    from pydantic import root_validator  # type: ignore[no-redef]

from ical.parsing.property import ParsedProperty, ParsedPropertyParameter

from .data_types import DATA_TYPE
from .parsing import parse_parameter_values
from .enum import create_enum_validator


class RelationshipType(str, enum.Enum):
    """Type of hierarchical relationship associated with the calendar component."""

    PARENT = "PARENT"
    """Parent relationship - Default."""

    CHILD = "CHILD"
    """Child relationship."""

    SIBBLING = "SIBBLING"
    """Sibling relationship."""

    @classmethod
    def __get_validators__(cls) -> Generator[Callable[[Any], Any], None, None]:
        """Return a generator that validates the value against the enum."""
        yield create_enum_validator(RelationshipType)


@DATA_TYPE.register("RELATED-TO")
@dataclass
class RelatedTo:
    """Used to represent a relationship or reference between one calendar component and another."""

    uid: str
    """The value of the related-to property is the persistent, globally unique identifier of another calendar component."""

    reltype: RelationshipType = RelationshipType.PARENT
    """Indicate the type of hierarchical relationship associated with the calendar component specified by the uid."""

    @classmethod
    def __parse_property_value__(cls, prop: Any) -> dict[str, Any]:
        """Parse a rfc5545 int value."""
        logging.info("prop=%s", prop)
        if isinstance(prop, ParsedProperty):
            data: dict[str, Any] = {"uid": prop.value}
            for param in prop.params or ():
                if len(param.values) > 1:
                    raise ValueError("Expected only one value for RELATED-TO parameter")
                data[param.name] = param.values[0]
            return data
        return {"uid": prop}

    _parse_parameter_values = root_validator(pre=True, allow_reuse=True)(
        parse_parameter_values
    )

    @classmethod
    def __encode_property_value__(cls, model_data: dict[str, str]) -> str | None:
        return model_data.pop("uid")

    @classmethod
    def __encode_property_params__(
        cls, model_data: dict[str, Any]
    ) -> list[ParsedPropertyParameter]:
        if "reltype" not in model_data:
            return []
        return [ParsedPropertyParameter(name="RELTYPE", values=[model_data["reltype"]])]
